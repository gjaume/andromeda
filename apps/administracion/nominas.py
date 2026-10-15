"""Descarga de las nóminas que manda la gestoría al buzón de administración.

Los correos están en la etiqueta GMAIL["NOMINAS_LABEL"] ("Gastos/Nominas"). De cada correo se
guardan dos PDF: el que tiene las nóminas de todos los empleados y el resumen. Muchos correos
traen además un PDF por empleado; esos solo se guardan si falta el de todos (hay meses en que
la gestoría no lo manda), para que el mes no se quede sin nóminas. Los PDF no se procesan.

Cada correo se procesa una sola vez (CorreoNomina), tenga o no nóminas. Se guardan también
las correcciones: el último PDF recibido de cada documento es el bueno y los anteriores quedan
marcados como sustituidos (Nomina.sustituida_por).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePath

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from integrations.gmail import GmailAuthError, GmailClient, GmailError, GmailMessage, get_client

from .extraccion.servicio import detectar_empresa
from .facturas import consulta_gmail, es_factura
from .models import CorreoNomina, Empresa, Nomina
from .utils import normalizar

logger = logging.getLogger(__name__)

Tipo = Nomina.Tipo


@dataclass
class ResultadoNominas:
    correos_nuevos: int = 0
    nominas_nuevas: int = 0
    etiqueta_no_encontrada: bool = False
    errores: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        partes = [f"{self.nominas_nuevas} PDF de nóminas nuevos en {self.correos_nuevos} correos"]
        if self.etiqueta_no_encontrada:
            partes.append(f"no existe la etiqueta {settings.GMAIL['NOMINAS_LABEL']}")
        if self.errores:
            partes.append(f"{len(self.errores)} errores")
        return "; ".join(partes)


def _sin_prefijos(nombre: str) -> str:
    """Sin el mes delante ni "ok" detrás: "202609 - Nóminas X SL ok.pdf" → "nominas x sl"."""
    texto = normalizar(PurePath(nombre).stem)
    texto = re.sub(r"^\d{6}\s*-?\s*", "", texto)
    return re.sub(r"\s+ok$", "", texto)


def clasificar(nombre: str, empresas: list[Empresa]) -> str:
    """Tipo de PDF según su nombre.

    - Resumen: "202609 Resumen nóminas Andromeda Solutions SLU.pdf".
    - Todas: "Nóminas <empresa>" sin nada detrás; los de cada empleado añaden " - <nombre>"
      ("…SL - Nombre Apellido.pdf") o solo llevan el nombre ("202602 APELLIDO, NOMBRE.pdf").
    """
    texto = _sin_prefijos(nombre)
    if "resumen" in texto:
        return Tipo.RESUMEN
    if (
        re.match(r"nominas?\b", texto)
        and "-" not in texto
        and detectar_empresa(texto, empresas) is not None
    ):
        return Tipo.NOMINAS
    return Tipo.EMPLEADO


def periodo(nombre: str, recibido_en) -> date:
    """Mes de las nóminas: el prefijo AAAAMM del fichero o, si no lo lleva, el del correo."""
    if m := re.match(r"\s*(20\d{2})(0[1-9]|1[0-2])", PurePath(nombre).stem):
        return date(int(m[1]), int(m[2]), 1)
    return timezone.localtime(recibido_en).date().replace(day=1)


def sincronizar_nominas(
    dias: int | None = None, *, desde: date | None = None, client: GmailClient | None = None
) -> ResultadoNominas:
    """Busca nóminas nuevas desde la fecha `desde`, o de los últimos `dias` días (0 = todas)."""
    query = consulta_gmail(dias, desde)
    resultado = ResultadoNominas()
    etiqueta = settings.GMAIL["NOMINAS_LABEL"]

    gmail = client or get_client()
    try:
        etiquetas = {nombre.casefold(): id_ for nombre, id_ in gmail.labels().items()}
        label_id = etiquetas.get(etiqueta.casefold())
        if not label_id:
            logger.warning("No existe la etiqueta de Gmail %s", etiqueta)
            resultado.etiqueta_no_encontrada = True
            return resultado
        _sincronizar_etiqueta(gmail, label_id, query, resultado)
    finally:
        if client is None:
            gmail.close()

    logger.info("Sincronización de nóminas: %s", resultado)
    return resultado


def _sincronizar_etiqueta(gmail, label_id, query, resultado) -> None:
    ids = list(gmail.message_ids(label_id, query))
    ya_procesados = set(
        CorreoNomina.objects.filter(gmail_id__in=ids).values_list("gmail_id", flat=True)
    )
    empresas = list(Empresa.objects.all())
    # Del más antiguo al más reciente. Un correo que falla no se marca y se reintenta luego.
    for message_id in reversed(ids):
        if message_id in ya_procesados:
            continue
        try:
            mensaje = gmail.message(message_id)
            resultado.nominas_nuevas += _guardar_correo(gmail, mensaje, empresas)
            resultado.correos_nuevos += 1
        except IntegrityError:
            logger.info("El correo de nóminas %s ya estaba procesado", message_id)
        except GmailAuthError:
            raise
        except GmailError as exc:
            logger.exception("Error procesando el correo de nóminas %s", message_id)
            resultado.errores.append(f"correo {message_id}: {exc}")


def _guardar_correo(gmail: GmailClient, mensaje: GmailMessage, empresas: list[Empresa]) -> int:
    pdfs = [(a, clasificar(a.filename, empresas)) for a in mensaje.attachments]
    pdfs = [(a, tipo) for a, tipo in pdfs if es_factura(a.filename)]
    trae_todas = any(tipo == Tipo.NOMINAS for _, tipo in pdfs)
    pdfs = [(a, tipo) for a, tipo in pdfs if tipo != Tipo.EMPLEADO or not trae_todas]
    contenidos = [(a, tipo, gmail.attachment_content(mensaje.id, a)) for a, tipo in pdfs]
    # Los PDF de cada empleado no suelen nombrar la empresa: la del resto del correo
    detectadas = {detectar_empresa(a.filename, empresas) for a, _ in pdfs} - {None}
    empresa_del_correo = (
        detectadas.pop() if len(detectadas) == 1 else detectar_empresa(mensaje.subject, empresas)
    )

    meses = set()
    with transaction.atomic():
        correo = CorreoNomina.objects.create(
            gmail_id=mensaje.id,
            asunto=mensaje.subject[:500],
            remitente=mensaje.sender[:320],
            recibido_en=mensaje.received_at,
        )
        for adjunto, tipo, contenido in contenidos:
            nomina = Nomina(
                correo=correo,
                empresa=detectar_empresa(adjunto.filename, empresas) or empresa_del_correo,
                periodo=periodo(adjunto.filename, mensaje.received_at),
                tipo=tipo,
                gmail_part_id=adjunto.part_id,
                nombre_archivo=adjunto.filename[:255],
                tamano=len(contenido),
                recibida_en=mensaje.received_at,
            )
            nomina.archivo.save(adjunto.filename, ContentFile(contenido), save=False)
            nomina.save()
            meses.add((nomina.empresa_id, nomina.periodo))
        for empresa_id, mes in meses:
            marcar_versiones(empresa_id, mes)
    return len(contenidos)


def clave_documento(nomina: Nomina) -> tuple[str, str]:
    """Qué documento es: el tipo y, si es de un empleado, su nombre (sin mes ni "OK")."""
    nombre = _sin_prefijos(nomina.nombre_archivo) if nomina.tipo == Tipo.EMPLEADO else ""
    return nomina.tipo, nombre


def marcar_versiones(empresa_id: int | None, mes: date) -> int:
    """En cada documento del mes, el último recibido es el bueno y los anteriores apuntan a él.

    Devuelve cuántas nóminas han cambiado.
    """
    documentos = defaultdict(list)
    nominas = Nomina.objects.filter(empresa_id=empresa_id, periodo=mes)
    for nomina in nominas.order_by("-recibida_en", "-pk"):
        documentos[clave_documento(nomina)].append(nomina)
    cambiadas = 0
    for ultima, *anteriores in documentos.values():
        for nomina in [ultima, *anteriores]:
            sustituida_por = None if nomina is ultima else ultima.pk
            if nomina.sustituida_por_id != sustituida_por:
                nomina.sustituida_por_id = sustituida_por
                nomina.save(update_fields=["sustituida_por"])
                cambiadas += 1
    return cambiadas


def marcar_todas_las_versiones() -> int:
    meses = Nomina.objects.values_list("empresa_id", "periodo").distinct()
    return sum(marcar_versiones(empresa_id, mes) for empresa_id, mes in meses)
