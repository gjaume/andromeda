"""Copia de las facturas recibidas en Google Drive, para el equipo de contabilidad.

Cada empresa del grupo tiene su carpeta (Empresa.carpeta_drive), con una carpeta por año:

    Administración / ANDROMEDA SOLUTIONS / Facturas recibidas AS /
        2026/                   ← aquí se suben las facturas de 2026
            CONTABILIZADO/      ← contabilidad mueve aquí las que ya ha contabilizado

El año es el de la fecha de la factura (o el del correo si aún no se ha leído del PDF).

En cada pasada se recorre la carpeta de la empresa entera y se busca cada factura por su id en
Drive o, si no, por su contenido (MD5), así que se reconoce aunque contabilidad la renombre o
alguien la hubiera subido antes a mano. Entonces:

- Está en <año>/CONTABILIZADO (o en una subcarpeta suya) → subida y contabilizada.
- Está en otro sitio dentro de <año> → subida, pendiente de contabilizar.
- Está en Drive pero fuera de <año> (otro año, una carpeta CONTABILIZADO suelta…) → no se
  vuelve a subir: se avisa como "fuera de sitio" para que contabilidad la mueva.
- No está → se sube a la raíz de <año>, creando <año> y <año>/CONTABILIZADO si no existen.

Los ficheros se llaman "Proveedor fecha nº.pdf" y todos los ligados a una factura del sistema
llevan el proveedor delante, aunque los haya subido otro (ver nombre_corregido).

Solo se suben facturas y abonos con la empresa identificada: no los recibos de pago, ni los
anexos, ni las duplicadas.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePath

from django.conf import settings
from django.utils import timezone

from integrations import drive
from integrations.drive import DriveAuthError, DriveClient, DriveError

from .models import Empresa, FacturaRecibida, Proveedor
from .utils import normalizar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Ubicacion:
    drive_id: str
    nombre: str
    ruta: str  # "2026/CONTABILIZADO/1T/fichero.pdf", relativa a la carpeta de la empresa
    anio: int | None  # carpeta de año en la que está, si está dentro de una
    contabilizada: bool  # dentro de <año>/CONTABILIZADO

    def prioridad(self, anio: int) -> int:
        """Si el mismo PDF está varias veces, la copia que cuenta (menor = mejor)."""
        if self.anio == anio:
            return 0 if self.contabilizada else 1
        return 2


@dataclass
class Resumen:
    subidas: list[str] = field(default_factory=list)
    renombradas: list[str] = field(default_factory=list)
    ya_subidas: int = 0
    contabilizadas: int = 0
    nuevas_contabilizadas: list[str] = field(default_factory=list)
    fuera_de_sitio: list[str] = field(default_factory=list)
    sin_empresa: list[str] = field(default_factory=list)
    carpetas_creadas: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        partes = [
            f"{len(self.subidas)} subidas",
            f"{self.ya_subidas} ya estaban en Drive",
            f"{self.contabilizadas} contabilizadas ({len(self.nuevas_contabilizadas)} nuevas)",
        ]
        if self.renombradas:
            partes.append(f"{len(self.renombradas)} renombradas")
        if self.fuera_de_sitio:
            partes.append(f"{len(self.fuera_de_sitio)} fuera de sitio")
        if self.sin_empresa:
            partes.append(f"{len(self.sin_empresa)} sin empresa identificada")
        if self.carpetas_creadas:
            partes.append(f"carpetas creadas: {', '.join(self.carpetas_creadas)}")
        if self.errores:
            partes.append(f"{len(self.errores)} errores")
        return ", ".join(partes)


def nombre_en_drive(factura: FacturaRecibida) -> str:
    """ "Hetzner 2026-01-31 R0012345.pdf": siempre con el proveedor delante."""
    fecha = factura.fecha_factura or timezone.localdate(factura.recibida_en)
    original = PurePath(factura.nombre_archivo)
    partes = [factura.proveedor.nombre, fecha.isoformat()]
    if factura.tipo == FacturaRecibida.Tipo.ABONO:
        partes.append("factura rectificativa")
    partes.append(factura.numero_factura or original.stem)
    nombre = re.sub(r'[\\/:*?"<>|\s]+', " ", " ".join(partes)).strip()
    return f"{nombre}{original.suffix.lower() or '.pdf'}"


def nombre_corregido(factura: FacturaRecibida, ubicacion: Ubicacion, anio: int):
    """Nuevo nombre para el fichero de la factura en Drive, o None si está bien como está.

    Todos los ficheros ligados a una factura llevan el proveedor delante:

    - Los que subimos nosotros y nadie ha tocado, mientras sigan en la carpeta de su año sin
      contabilizar, se ponen al día con `nombre_en_drive` (p. ej. si se subieron antes de
      leer la fecha del PDF).
    - Los del formato antiguo ("2026-01-31 Hetzner R001.pdf") pasan a "Hetzner 2026-01-31
      R001.pdf".
    - A los demás (subidos a mano, renombrados por contabilidad…) se les antepone el proveedor,
      salvo que ya empiecen por él. Si empiezan por el de otro proveedor (la factura se ha
      reasignado), se cambia ese prefijo.

    Devuelve (nombre, es_nuestro): es_nuestro indica que el nombre lo ponemos nosotros entero.
    """
    proveedor = factura.proveedor.nombre
    actual = ubicacion.nombre
    deseado = nombre_en_drive(factura)
    nuestro = bool(factura.drive_nombre) and actual == factura.drive_nombre
    if nuestro and ubicacion.anio == anio and not ubicacion.contabilizada:
        return (deseado, True) if actual != deseado else None
    if normalizar(actual).startswith(normalizar(proveedor)):
        return None
    if m := re.fullmatch(rf"(\d{{4}}-\d{{2}}-\d{{2}}) {re.escape(proveedor)} (.+)", actual):
        return f"{proveedor} {m[1]} {m[2]}", True
    for otro in otros_proveedores(factura.proveedor_id):
        if actual.startswith(f"{otro} "):
            return f"{proveedor} {actual[len(otro) + 1 :]}", nuestro
    return f"{proveedor} {actual}", False


def otros_proveedores(proveedor_id: int) -> list[str]:
    """Nombres de los demás proveedores, los más largos primero ("PYR Asesores" antes que "PYR")."""
    nombres = Proveedor.objects.exclude(pk=proveedor_id).values_list("nombre", flat=True)
    return sorted(nombres, key=len, reverse=True)


def leer_pdf(factura: FacturaRecibida) -> bytes:
    with factura.archivo.open("rb") as fichero:
        return fichero.read()


def md5_de(factura: FacturaRecibida) -> str:
    """MD5 del PDF, guardado en la factura para no tener que descargarlo en cada pasada."""
    if not factura.md5:
        factura.md5 = hashlib.md5(leer_pdf(factura)).hexdigest()
        factura.save(update_fields=["md5"])
    return factura.md5


def indexar(client: DriveClient, raiz: str, contabilizado: str) -> dict[str, list[Ubicacion]]:
    """{id o md5: [Ubicacion]} de todos los ficheros bajo la carpeta de la empresa."""
    indice: dict[str, list[Ubicacion]] = defaultdict(list)
    # (carpeta, ruta, año, contabilizada)
    pendientes: list[tuple[str, str, int | None, bool]] = [(raiz, "", None, False)]
    while pendientes:
        carpeta, ruta, anio, contabilizada = pendientes.pop()
        for f in client.hijos(carpeta):
            ruta_f = f"{ruta}{f.name}"
            if f.es_carpeta:
                if carpeta == raiz and re.fullmatch(r"\d{4}", f.name):
                    pendientes.append((f.id, f"{ruta_f}/", int(f.name), False))
                else:
                    es_contabilizado = anio is not None and ruta.count("/") == 1
                    es_contabilizado = es_contabilizado and f.name == contabilizado
                    pendientes.append((f.id, f"{ruta_f}/", anio, contabilizada or es_contabilizado))
            else:
                ubicacion = Ubicacion(f.id, f.name, ruta_f, anio, contabilizada)
                indice[f.id].append(ubicacion)
                if f.md5:
                    indice[f.md5].append(ubicacion)
    return indice


def facturas_a_subir():
    return (
        FacturaRecibida.objects.sin_duplicados()
        .exclude(tipo__in=FacturaRecibida.TIPOS_NO_GASTO)
        .con_fecha()
        .select_related("proveedor", "empresa")
    )


def sincronizar_drive(
    *, probar: bool = False, anio: int | None = None, client: DriveClient | None = None
) -> Resumen:
    """Sube las facturas que falten y actualiza cuáles están contabilizadas.

    Con `probar`, solo consulta Drive y cuenta lo que haría: no sube, no crea carpetas y no
    guarda nada.
    """
    resumen = Resumen()
    facturas = facturas_a_subir()
    if anio:
        facturas = facturas.filter(fecha__year=anio)
    por_empresa: dict[Empresa, list[FacturaRecibida]] = defaultdict(list)
    for factura in facturas.order_by("fecha", "id"):
        if factura.empresa is None:
            resumen.sin_empresa.append(str(factura))
        elif factura.empresa.carpeta_drive:
            por_empresa[factura.empresa].append(factura)
    if not por_empresa:
        return resumen

    client = client or drive.get_client()
    with client:
        for empresa, grupo in por_empresa.items():
            _sincronizar_empresa(client, empresa, grupo, resumen, probar)
    return resumen


def _sincronizar_empresa(client, empresa, facturas, resumen, probar) -> None:
    contabilizado = settings.DRIVE["CARPETA_CONTABILIZADO"]
    unidad, _, ruta = empresa.carpeta_drive.strip("/").partition("/")
    raiz = client.ruta(unidad, ruta)
    indice = indexar(client, raiz, contabilizado)
    carpetas_anio: dict[int, str | None] = {}

    def carpeta_del_anio(anio: int) -> str | None:
        """Id de <año>, creándola (con su CONTABILIZADO) si hace falta. None en modo prueba."""
        if anio not in carpetas_anio:
            carpeta = client.subcarpeta(raiz, str(anio))
            if carpeta is None:
                resumen.carpetas_creadas.append(f"{empresa} / {anio}")
                carpeta = None if probar else client.crear_carpeta(raiz, str(anio))
            if carpeta and client.subcarpeta(carpeta.id, contabilizado) is None:
                resumen.carpetas_creadas.append(f"{empresa} / {anio} / {contabilizado}")
                if not probar:
                    client.crear_carpeta(carpeta.id, contabilizado)
            carpetas_anio[anio] = carpeta.id if carpeta else None
        return carpetas_anio[anio]

    for factura in facturas:
        try:
            _sincronizar_factura(client, factura, indice, carpeta_del_anio, resumen, probar)
        except DriveAuthError:
            raise  # sin permisos no va a funcionar ninguna: mejor parar
        except (DriveError, OSError) as exc:
            logger.exception("No se pudo sincronizar con Drive la factura %s", factura.pk)
            resumen.errores.append(f"#{factura.pk} {factura}: {exc}")


def _sincronizar_factura(client, factura, indice, carpeta_del_anio, resumen, probar) -> None:
    anio = factura.fecha.year
    candidatas = indice.get(factura.drive_id, []) or indice.get(md5_de(factura), [])
    ubicacion = min(candidatas, key=lambda u: u.prioridad(anio), default=None)
    ahora = timezone.now()
    if ubicacion is None:
        nombre = nombre_en_drive(factura)
        carpeta = carpeta_del_anio(anio)
        resumen.subidas.append(f"{factura.empresa} / {anio} / {nombre}")
        if probar:
            return
        subida = client.subir(carpeta, nombre, leer_pdf(factura))
        logger.info("Factura %s subida a Drive (%s)", factura.pk, subida.id)
        factura.drive_id = subida.id
        factura.drive_nombre = subida.name
        factura.subida_a_drive_en = ahora
        factura.contabilizada_en = None
    else:
        resumen.ya_subidas += 1
        if ubicacion.anio != anio:
            resumen.fuera_de_sitio.append(
                f"{factura} ({anio}) está en «{ubicacion.ruta}» de {factura.empresa}"
            )
        resumen.contabilizadas += ubicacion.contabilizada and ubicacion.anio == anio
        contabilizada = ubicacion.contabilizada and ubicacion.anio == anio
        if contabilizada and not factura.contabilizada_en:
            resumen.nuevas_contabilizadas.append(str(factura))
        renombrar = nombre_corregido(factura, ubicacion, anio)
        if renombrar:
            resumen.renombradas.append(f"{ubicacion.ruta} → {renombrar[0]}")
        if probar:
            return
        if renombrar:
            nombre, es_nuestro = renombrar
            nuevo = client.renombrar(ubicacion.drive_id, nombre).name
            # Si el nombre es de otro (solo le añadimos el proveedor), no lo volvemos a cambiar
            factura.drive_nombre = nuevo if es_nuestro else ""
        factura.drive_id = ubicacion.drive_id
        factura.subida_a_drive_en = factura.subida_a_drive_en or ahora
        factura.contabilizada_en = (factura.contabilizada_en or ahora) if contabilizada else None
    factura.save(
        update_fields=["drive_id", "drive_nombre", "subida_a_drive_en", "contabilizada_en"]
    )
