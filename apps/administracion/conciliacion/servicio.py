"""Conciliación de las facturas recibidas con los pagos del banco y de la tarjeta.

1. Se importan de Drive los extractos de cada empresa (Empresa.extracto_banco y
   extracto_tarjeta) a MovimientoPago.
2. Cada factura (y abono) se empareja con el movimiento que la paga:
   - Mismo importe: en euros, o en la moneda original si es un cargo de tarjeta en dólares.
     Los abonos (negativos) casan con entradas de dinero.
   - Si el proveedor tiene "textos del pago", el concepto del movimiento debe contener alguno
     (p. ej. PUIGSERVER para PYR Asesores). Si no tiene, solo se acepta un movimiento con ese
     importe cerca de la fecha, y únicamente si no hay otro igual.
   - Fecha del pago entre VENTANA_ANTES días antes y VENTANA_DESPUES después de la factura.
     Entre varias candidatas gana la más cercana (penalizando los pagos anteriores a la
     factura), y cada movimiento paga una sola factura...
   - ...salvo una transferencia que pague varias facturas seguidas del mismo proveedor de una
     vez (p. ej. cinco meses de alquiler): se acepta si la suma cuadra exactamente.
3. El método (tarjeta, domiciliación o transferencia) sale del movimiento.

Las facturas con el pago marcado a mano (pago_manual) no se tocan. El resto se recalcula en
cada pasada, así que corregir los textos de un proveedor corrige sus facturas.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from integrations import drive
from integrations.drive import DriveClient, DriveNotFound

from ..models import Empresa, FacturaRecibida, MovimientoPago
from ..utils import normalizar
from .hojas import HojaError, Movimiento, asignar_claves, leer_banco, leer_tarjeta

logger = logging.getLogger(__name__)

VENTANA_ANTES = 60  # días: hay pagos por adelantado (p. ej. Validated ID)
VENTANA_DESPUES = 90  # días: transferencias que se hacen un par de meses después
VENTANA_SOLO_IMPORTE = (5, 45)  # proveedores sin textos del pago: más estricto
TOLERANCIA = Decimal("0.01")


@dataclass
class Resumen:
    movimientos: int = 0
    ficheros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    pagadas: int = 0
    pendientes: int = 0
    por_metodo: dict[str, int] = field(default_factory=dict)

    def __str__(self) -> str:
        metodos = ", ".join(f"{n} {m}" for m, n in sorted(self.por_metodo.items()))
        texto = (
            f"{self.movimientos} movimientos importados; {self.pagadas} facturas pagadas "
            f"({metodos or 'ninguna'}), {self.pendientes} sin pago encontrado"
        )
        return texto + (f"; {len(self.avisos)} avisos" if self.avisos else "")


# --- Importación ----------------------------------------------------------------------------


def _ruta(client: DriveClient, ruta: str):
    """Fichero de Drive a partir de "Unidad/carpeta/…/fichero.xlsx"."""
    unidad, _, resto = ruta.strip("/").partition("/")
    carpeta, _, nombre = resto.rpartition("/")
    carpeta_id = client.ruta(unidad, carpeta)
    fichero = client.fichero(carpeta_id, nombre)
    if fichero is None:
        raise DriveNotFound(f"No encuentro «{nombre}» en {unidad}/{carpeta}")
    return fichero


def leer_extractos(client: DriveClient, empresa: Empresa, anios: list[int], resumen: Resumen):
    """Movimientos de los extractos de la empresa, o None si falta el del banco."""
    movimientos: list[Movimiento] = []
    if empresa.extracto_banco:
        fichero = _ruta(client, empresa.extracto_banco)
        movimientos += leer_banco(
            client.descargar(fichero), empresa.extracto_banco_pestana, empresa.extracto_banco
        )
        resumen.ficheros.append(empresa.extracto_banco)
    if empresa.extracto_tarjeta:
        for anio in anios:
            ruta = empresa.extracto_tarjeta.replace("{anio}", str(anio))
            try:
                fichero = _ruta(client, ruta)
            except DriveNotFound as exc:
                resumen.avisos.append(str(exc))
                continue
            movimientos += leer_tarjeta(client.descargar(fichero), anio, ruta, resumen.avisos)
            resumen.ficheros.append(ruta)
    return asignar_claves(movimientos)


@transaction.atomic
def guardar_movimientos(empresa: Empresa, movimientos: list[Movimiento], ficheros: list[str]):
    """Crea o actualiza los movimientos y borra los que ya no están en los ficheros leídos."""
    existentes = {m.clave: m for m in empresa.movimientos.all()}
    nuevos = []
    for m in movimientos:
        datos = {
            "origen": m.origen,
            "fecha": m.fecha,
            "concepto": m.concepto,
            "importe": m.importe,
            "importe_original": m.importe_original,
            "moneda_original": m.moneda_original,
            "metodo": m.metodo,
            "hoja": m.hoja,
        }
        if actual := existentes.pop(m.clave, None):
            if any(getattr(actual, k) != v for k, v in datos.items()):
                for k, v in datos.items():
                    setattr(actual, k, v)
                actual.save()
        else:
            nuevos.append(MovimientoPago(empresa=empresa, clave=m.clave, **datos))
    MovimientoPago.objects.bulk_create(nuevos)
    # Solo se borran los de ficheros que se han leído (un año de tarjeta que falta no se toca)
    sobran = [
        m.pk for m in existentes.values() if any(m.hoja.startswith(f"{f} ›") for f in ficheros)
    ]
    MovimientoPago.objects.filter(pk__in=sobran).delete()


# --- Emparejamiento -------------------------------------------------------------------------


def _importe_casa(factura: FacturaRecibida, m: MovimientoPago) -> bool:
    if factura.moneda in ("EUR", ""):
        return abs(m.importe - factura.total) <= TOLERANCIA
    if m.moneda_original != factura.moneda or m.importe_original is None:
        return False
    # El importe original viene sin signo: lleva el del cargo (o devolución) en euros
    original = m.importe_original if m.importe >= 0 else -m.importe_original
    return abs(original - factura.total) <= TOLERANCIA


def _textos_casan(textos: list[str], m: MovimientoPago) -> bool:
    concepto = normalizar(m.concepto)
    return any(normalizar(t) in concepto for t in textos)


def _distancia(factura: FacturaRecibida, m: MovimientoPago) -> int | None:
    """Días de la factura al pago (los pagos anteriores cuentan doble); None si fuera de rango."""
    referencia = factura.fecha_factura or factura.recibida_en.date()
    dias = (m.fecha - referencia).days
    antes, despues = (
        (VENTANA_ANTES, VENTANA_DESPUES)
        if factura.proveedor.lista_textos_pago
        else VENTANA_SOLO_IMPORTE
    )
    if not -antes <= dias <= despues:
        return None
    return dias if dias >= 0 else -2 * dias


def emparejar(
    facturas: list[FacturaRecibida], movimientos: list[MovimientoPago]
) -> dict[int, MovimientoPago]:
    """{id de factura: movimiento que la paga}."""
    candidatos = []  # (distancia, factura, movimiento)
    for f in facturas:
        textos = f.proveedor.lista_textos_pago
        posibles = [
            m
            for m in movimientos
            if _importe_casa(f, m) and (not textos or _textos_casan(textos, m))
        ]
        if not textos:
            posibles = [m for m in posibles if _distancia(f, m) is not None]
            if len(posibles) != 1:
                continue  # sin textos, solo si es inequívoco
        candidatos += [(d, f, m) for m in posibles if (d := _distancia(f, m)) is not None]

    pagos: dict[int, MovimientoPago] = {}
    usados: set[int] = set()
    for _, f, m in sorted(candidatos, key=lambda c: (c[0], c[1].pk, c[2].pk)):
        if f.pk not in pagos and m.pk not in usados:
            pagos[f.pk] = m
            usados.add(m.pk)

    # Un pago para varias facturas seguidas del mismo proveedor (solo con textos del pago)
    por_proveedor = defaultdict(list)
    for f in facturas:
        if f.pk not in pagos and f.proveedor.lista_textos_pago and f.total:
            por_proveedor[f.proveedor_id].append(f)
    for pendientes in por_proveedor.values():
        pendientes.sort(key=lambda f: (f.fecha_factura or f.recibida_en.date(), f.pk))
        textos = pendientes[0].proveedor.lista_textos_pago
        for m in movimientos:
            if m.pk in usados or not _textos_casan(textos, m):
                continue
            grupo = _grupo_que_suma(pendientes, m, pagos)
            if grupo:
                for f in grupo:
                    pagos[f.pk] = m
                usados.add(m.pk)
    return pagos


def _grupo_que_suma(pendientes, m: MovimientoPago, pagos) -> list[FacturaRecibida] | None:
    libres = [f for f in pendientes if f.pk not in pagos and f.moneda in ("EUR", "")]
    for inicio in range(len(libres)):
        suma = Decimal(0)
        for fin in range(inicio, len(libres)):
            suma += libres[fin].total
            if fin > inicio and abs(suma - m.importe) <= TOLERANCIA:
                grupo = libres[inicio : fin + 1]
                # Paga atrasos: basta con que la última esté en la ventana y la primera, antes
                primera = grupo[0].fecha_factura or grupo[0].recibida_en.date()
                if _distancia(grupo[-1], m) is not None and primera <= m.fecha:
                    return grupo
            if suma > m.importe + TOLERANCIA:
                break
    return None


def facturas_a_conciliar(empresa: Empresa):
    return (
        FacturaRecibida.objects.sin_duplicados()
        .exclude(tipo__in=FacturaRecibida.TIPOS_NO_GASTO)
        .filter(empresa=empresa, total__isnull=False)
        .select_related("proveedor")
    )


@transaction.atomic
def conciliar(empresa: Empresa, resumen: Resumen | None = None) -> Resumen:
    """Recalcula qué facturas de la empresa están pagadas y con qué movimiento."""
    resumen = resumen or Resumen()
    facturas = list(facturas_a_conciliar(empresa))
    manuales = {f.pago_id for f in facturas if f.pago_manual and f.pago_id}
    automaticas = [f for f in facturas if not f.pago_manual]
    movimientos = [m for m in empresa.movimientos.all() if m.pk not in manuales]
    pagos = emparejar(automaticas, movimientos)

    for f in automaticas:
        m = pagos.get(f.pk)
        nuevo = (m.pk, m.metodo, m.fecha) if m else (None, "", None)
        if (f.pago_id, f.metodo_pago, f.pagada_el) != nuevo:
            f.pago_id, f.metodo_pago, f.pagada_el = nuevo
            f.save(update_fields=["pago", "metodo_pago", "pagada_el"])
    for f in facturas:
        if f.metodo_pago:
            resumen.pagadas += 1
            metodo = f.get_metodo_pago_display().lower()
            resumen.por_metodo[metodo] = resumen.por_metodo.get(metodo, 0) + 1
        else:
            resumen.pendientes += 1
    return resumen


def conciliar_pagos(*, client: DriveClient | None = None) -> Resumen:
    """Importa los extractos de Drive de cada empresa que los tenga y concilia sus facturas."""
    resumen = Resumen()
    empresas = [e for e in Empresa.objects.all() if e.concilia_pagos]
    if not empresas:
        return resumen
    client = client or drive.get_client()
    with client:
        for empresa in empresas:
            anios = sorted(
                {d.year for d in facturas_a_conciliar(empresa).con_fecha().dates("fecha", "year")}
            )
            try:
                movimientos = leer_extractos(client, empresa, anios, resumen)
            except (DriveNotFound, HojaError) as exc:
                # Falta el extracto o cambió de formato: se avisa y se sigue con las demás
                logger.warning("No se pueden leer los extractos de %s: %s", empresa, exc)
                resumen.avisos.append(f"{empresa}: {exc}")
                continue
            guardar_movimientos(empresa, movimientos, resumen.ficheros)
            resumen.movimientos += len(movimientos)
            conciliar(empresa, resumen)
    return resumen
