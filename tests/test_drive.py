"""Subida de facturas a Google Drive y detección de las contabilizadas."""

import hashlib
import itertools
from datetime import date, datetime

import httpx
import pytest
import respx
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from apps.administracion.drive import nombre_en_drive, sincronizar_drive
from apps.administracion.models import CorreoFactura, Empresa, FacturaRecibida, Proveedor
from apps.administracion.tasks import sincronizar_facturas_drive
from integrations.drive import DriveAuthError, DriveError, DriveFile, DriveNotFound, get_client
from integrations.drive.client import CARPETA

# --- Drive falso en memoria -----------------------------------------------------------------


class DriveFalso:
    """Mismo interfaz que DriveClient, con las carpetas y ficheros en un diccionario."""

    def __init__(self):
        self._ids = (f"id{n}" for n in itertools.count(1))
        self.items: dict[str, dict] = {}  # id → {name, parent, mime, md5, contenido}
        self.unidad = self.carpeta("Administración", None)
        self.facturas = self.carpeta(
            "Facturas recibidas AS", self.carpeta("ANDROMEDA SOLUTIONS", self.unidad)
        )
        self.tech = self.carpeta(
            "Facturas recibidas", self.carpeta("ANDROMEDA TECH GROUP", self.unidad)
        )
        self.subidas: list[str] = []
        self.renombradas: list[str] = []

    def carpeta(self, nombre, padre):
        return self._nuevo(nombre, padre, CARPETA)

    def fichero(self, nombre, padre, contenido: bytes):
        return self._nuevo(nombre, padre, "application/pdf", contenido)

    def _nuevo(self, nombre, padre, mime, contenido=b""):
        item_id = next(self._ids)
        md5 = hashlib.md5(contenido).hexdigest() if mime != CARPETA else ""
        self.items[item_id] = {"name": nombre, "parent": padre, "mime": mime, "md5": md5}
        return item_id

    def mover(self, item_id, padre):
        self.items[item_id]["parent"] = padre

    def buscar(self, nombre, padre):
        return next(
            i for i, d in self.items.items() if d["name"] == nombre and d["parent"] == padre
        )

    def ruta_de(self, item_id):
        partes = []
        while item_id is not None and item_id not in (self.facturas, self.tech):
            partes.append(self.items[item_id]["name"])
            item_id = self.items[item_id]["parent"]
        return "/".join(reversed(partes))

    # Interfaz de DriveClient
    def hijos(self, carpeta_id, *, solo_carpetas=False):
        for i, d in list(self.items.items()):
            if d["parent"] == carpeta_id and (not solo_carpetas or d["mime"] == CARPETA):
                yield DriveFile(i, d["name"], d["mime"], d["md5"])

    def subcarpeta(self, carpeta_id, nombre):
        return next(
            (f for f in self.hijos(carpeta_id, solo_carpetas=True) if f.name == nombre), None
        )

    def ruta(self, unidad, ruta):
        assert unidad == "Administración"
        return {
            "ANDROMEDA SOLUTIONS/Facturas recibidas AS": self.facturas,
            "ANDROMEDA TECH GROUP/Facturas recibidas": self.tech,
        }[ruta]

    def crear_carpeta(self, padre_id, nombre):
        return DriveFile(self.carpeta(nombre, padre_id), nombre, CARPETA)

    def renombrar(self, fichero_id, nombre):
        self.items[fichero_id]["name"] = nombre
        self.renombradas.append(nombre)
        return DriveFile(fichero_id, nombre, self.items[fichero_id]["mime"])

    def subir(self, padre_id, nombre, contenido, mime_type="application/pdf"):
        item_id = self.fichero(nombre, padre_id, contenido)
        self.subidas.append(nombre)
        return DriveFile(item_id, nombre, mime_type, self.items[item_id]["md5"])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


@pytest.fixture
def drive():
    return DriveFalso()


@pytest.fixture
def solutions(db):
    return Empresa.objects.get(nombre="ANDROMEDA SOLUTIONS")  # las crea la migración 0009


@pytest.fixture
def tech(db):
    return Empresa.objects.get(nombre="ANDROMEDA TECH GROUP")


@pytest.fixture
def crear(solutions):
    proveedor = Proveedor.objects.create(nombre="Acme", etiqueta_gmail="Acme")

    def crear(contenido=b"%PDF-1.4 a", *, fecha_factura=date(2026, 3, 31), numero="F-1", **extra):
        cuando = timezone.make_aware(datetime(2026, 4, 2, 9))
        correo = CorreoFactura.objects.create(
            proveedor=proveedor, gmail_id=f"m{CorreoFactura.objects.count()}", recibido_en=cuando
        )
        factura = FacturaRecibida(
            proveedor=proveedor,
            correo=correo,
            gmail_part_id="1",
            nombre_archivo="Invoice.PDF",
            recibida_en=cuando,
            fecha_factura=fecha_factura,
            numero_factura=numero,
            **{"tipo": "factura", "empresa": solutions, **extra},
        )
        factura.archivo.save("f.pdf", ContentFile(contenido), save=False)
        factura.save()
        return factura

    return crear


# --- Lógica ---------------------------------------------------------------------------------


def test_crea_la_carpeta_del_anio_y_sube_la_factura(drive, crear):
    factura = crear()
    resumen = sincronizar_drive(client=drive)

    factura.refresh_from_db()
    assert resumen.carpetas_creadas == [
        "ANDROMEDA SOLUTIONS / 2026",
        "ANDROMEDA SOLUTIONS / 2026 / CONTABILIZADO",
    ]
    assert drive.ruta_de(factura.drive_id) == "2026/Acme 2026-03-31 F-1.pdf"
    assert drive.subcarpeta(drive.buscar("2026", drive.facturas), "CONTABILIZADO")
    assert factura.subida_a_drive_en is not None
    assert factura.contabilizada_en is None
    assert factura.md5 == hashlib.md5(b"%PDF-1.4 a").hexdigest()


def test_usa_la_carpeta_del_anio_si_existe_y_no_vuelve_a_subir(drive, crear):
    anio = drive.carpeta("2026", drive.facturas)
    drive.carpeta("CONTABILIZADO", anio)
    crear()

    sincronizar_drive(client=drive)
    resumen = sincronizar_drive(client=drive)

    assert drive.subidas == ["Acme 2026-03-31 F-1.pdf"]
    assert (resumen.subidas, resumen.ya_subidas, resumen.carpetas_creadas) == ([], 1, [])


def test_crea_contabilizado_si_el_anio_no_lo_tiene(drive, crear):
    anio = drive.carpeta("2026", drive.facturas)
    crear()
    resumen = sincronizar_drive(client=drive)
    assert resumen.carpetas_creadas == ["ANDROMEDA SOLUTIONS / 2026 / CONTABILIZADO"]
    assert drive.subcarpeta(anio, "CONTABILIZADO")


def test_detecta_cuando_contabilidad_la_mueve_a_contabilizado(drive, crear):
    factura = crear()
    sincronizar_drive(client=drive)
    factura.refresh_from_db()
    anio = drive.buscar("2026", drive.facturas)

    # Contabilidad la mueve (y renombra) dentro de una subcarpeta de CONTABILIZADO
    trimestre = drive.carpeta("1T", drive.buscar("CONTABILIZADO", anio))
    drive.mover(factura.drive_id, trimestre)
    drive.items[factura.drive_id]["name"] = "acme marzo.pdf"
    resumen = sincronizar_drive(client=drive)

    factura.refresh_from_db()
    assert resumen.nuevas_contabilizadas == [str(factura)]
    assert factura.contabilizada_en is not None
    assert drive.subidas == ["Acme 2026-03-31 F-1.pdf"]

    # Si la devuelven a la carpeta del año, vuelve a estar pendiente
    drive.mover(factura.drive_id, anio)
    sincronizar_drive(client=drive)
    factura.refresh_from_db()
    assert factura.contabilizada_en is None


def test_reconoce_por_contenido_las_que_ya_estaban_en_drive(drive, crear):
    anio = drive.carpeta("2026", drive.facturas)
    contabilizado = drive.carpeta("CONTABILIZADO", anio)
    drive.fichero("subida a mano.pdf", contabilizado, b"%PDF-1.4 a")
    drive.fichero("otra.pdf", anio, b"%PDF-1.4 b")
    ya_contabilizada = crear(b"%PDF-1.4 a")
    pendiente = crear(b"%PDF-1.4 b", numero="F-2")
    nueva = crear(b"%PDF-1.4 c", numero="F-3")

    sincronizar_drive(client=drive)

    for f in (ya_contabilizada, pendiente, nueva):
        f.refresh_from_db()
    assert drive.subidas == ["Acme 2026-03-31 F-3.pdf"]
    assert ya_contabilizada.contabilizada_en is not None
    assert pendiente.subida_a_drive_en and not pendiente.contabilizada_en
    assert nueva.subida_a_drive_en and not nueva.contabilizada_en


def test_si_la_borran_de_drive_se_vuelve_a_subir(drive, crear):
    factura = crear()
    sincronizar_drive(client=drive)
    factura.refresh_from_db()
    del drive.items[factura.drive_id]

    sincronizar_drive(client=drive)
    assert len(drive.subidas) == 2


def test_el_anio_sale_de_la_fecha_de_la_factura_o_del_correo(drive, crear):
    crear(fecha_factura=date(2025, 12, 31))
    crear(b"%PDF-1.4 b", fecha_factura=None, numero="")

    sincronizar_drive(client=drive)
    assert sorted(drive.ruta_de(drive.buscar(n, p)) for n, p in [
        ("Acme 2025-12-31 F-1.pdf", drive.buscar("2025", drive.facturas)),
        ("Acme 2026-04-02 Invoice.pdf", drive.buscar("2026", drive.facturas)),
    ]) == ["2025/Acme 2025-12-31 F-1.pdf", "2026/Acme 2026-04-02 Invoice.pdf"]  # fmt: skip


def test_no_sube_duplicadas_recibos_ni_anexos(drive, crear):
    original = crear()
    crear(duplicada_de=original)
    crear(b"%PDF-1.4 r", tipo="recibo", numero="R-1")
    crear(b"%PDF-1.4 x", tipo="anexo", numero="")
    crear(b"%PDF-1.4 ab", tipo="abono", numero="A-1")
    sincronizar_drive(client=drive)
    assert drive.subidas == [
        "Acme 2026-03-31 F-1.pdf",
        "Acme 2026-03-31 factura rectificativa A-1.pdf",
    ]


def test_cada_empresa_en_su_carpeta(drive, crear, tech):
    crear()
    crear(b"%PDF-1.4 t", numero="T-1", empresa=tech)
    sincronizar_drive(client=drive)
    anio_tech = drive.buscar("2026", drive.tech)
    assert drive.buscar("Acme 2026-03-31 T-1.pdf", anio_tech)
    assert drive.buscar("Acme 2026-03-31 F-1.pdf", drive.buscar("2026", drive.facturas))


def test_sin_empresa_no_se_sube_y_se_avisa(drive, crear):
    factura = crear(empresa=None)
    resumen = sincronizar_drive(client=drive)
    assert drive.subidas == []
    assert resumen.sin_empresa == [str(factura)]


def test_fuera_de_sitio_no_se_vuelve_a_subir(drive, crear, tech):
    # Como en TECH GROUP: un CONTABILIZADO suelto, al lado de las carpetas de año
    drive.carpeta("CONTABILIZADO", drive.carpeta("2026", drive.tech))
    suelto = drive.carpeta("CONTABILIZADO", drive.tech)
    drive.fichero("t.pdf", suelto, b"%PDF-1.4 t")
    factura = crear(b"%PDF-1.4 t", empresa=tech)

    resumen = sincronizar_drive(client=drive)

    factura.refresh_from_db()
    assert drive.subidas == []
    assert resumen.fuera_de_sitio == [f"{factura} (2026) está en «CONTABILIZADO/t.pdf» de {tech}"]
    assert factura.contabilizada_en is None  # no cuenta hasta que esté en 2026/CONTABILIZADO


def test_otra_copia_en_su_sitio_gana_a_la_de_fuera(drive, crear):
    anio = drive.carpeta("2026", drive.facturas)
    drive.fichero("copia.pdf", drive.carpeta("2025", drive.facturas), b"%PDF-1.4 a")
    drive.fichero("buena.pdf", drive.carpeta("CONTABILIZADO", anio), b"%PDF-1.4 a")
    factura = crear()

    resumen = sincronizar_drive(client=drive)

    factura.refresh_from_db()
    assert resumen.fuera_de_sitio == []
    assert factura.contabilizada_en is not None


def test_modo_prueba_no_toca_nada(drive, crear):
    factura = crear()
    resumen = sincronizar_drive(client=drive, probar=True)

    factura.refresh_from_db()
    assert resumen.subidas == ["ANDROMEDA SOLUTIONS / 2026 / Acme 2026-03-31 F-1.pdf"]
    assert resumen.carpetas_creadas == ["ANDROMEDA SOLUTIONS / 2026"]
    assert drive.subidas == []
    assert drive.subcarpeta(drive.facturas, "2026") is None
    assert factura.subida_a_drive_en is None


def test_sin_permisos_se_para(drive, crear, monkeypatch):
    crear()
    crear(b"%PDF-1.4 b", numero="F-2")

    def subir(*args, **kwargs):
        raise DriveAuthError("403")

    monkeypatch.setattr(drive, "subir", subir)
    with pytest.raises(DriveAuthError):
        sincronizar_drive(client=drive)


@pytest.mark.parametrize(
    ("tipo", "numero", "esperado"),
    [
        ("factura", "A/23: 7", "Acme 2026-03-31 A 23 7.pdf"),
        ("abono", "R-1", "Acme 2026-03-31 factura rectificativa R-1.pdf"),
    ],
)
def test_nombre_en_drive(crear, tipo, numero, esperado):
    factura = crear(numero=numero)
    factura.tipo = tipo
    assert nombre_en_drive(factura) == esperado


def test_la_tarea_no_hace_nada_si_no_esta_activada(settings, crear):
    settings.DRIVE = {**settings.DRIVE, "ACTIVO": False}
    assert "desactivada" in sincronizar_facturas_drive()


def test_comando_en_modo_prueba(drive, crear, monkeypatch, capsys):
    crear()
    monkeypatch.setattr("integrations.drive.get_client", lambda: drive)
    call_command("sincronizar_drive", "--probar")
    salida = capsys.readouterr().out
    assert "Subiría ANDROMEDA SOLUTIONS / 2026 / Acme 2026-03-31 F-1.pdf" in salida
    assert drive.subidas == []


# --- Cliente HTTP ---------------------------------------------------------------------------

API = "https://www.googleapis.com/drive/v3"


def ficheros(*items, siguiente=None):
    """Respuesta de files.list con (id, nombre, mime[, md5])."""
    files = [
        {"id": i, "name": n, "mimeType": m, **({"md5Checksum": x[0]} if x else {})}
        for i, n, m, *x in items
    ]
    return httpx.Response(200, json={"files": files, "nextPageToken": siguiente})


@pytest.fixture
def cliente():
    with get_client(token_provider=lambda: "tok", backoff_base=0) as c:
        yield c


@respx.mock
def test_cliente_resuelve_la_ruta(cliente):
    respx.get(f"{API}/drives").mock(
        return_value=httpx.Response(200, json={"drives": [{"id": "D", "name": "Administración"}]})
    )
    hijos = respx.get(f"{API}/files").mock(
        side_effect=[
            ficheros(("A", "ANDROMEDA SOLUTIONS", CARPETA)),
            ficheros(("F", "Facturas recibidas AS", CARPETA)),
        ]
    )
    assert cliente.ruta("Administración", "ANDROMEDA SOLUTIONS/Facturas recibidas AS") == "F"
    peticion = hijos.calls[0].request
    assert peticion.url.params["supportsAllDrives"] == "true"
    assert peticion.url.params["q"].startswith("'D' in parents and trashed = false")
    assert peticion.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_cliente_avisa_si_falta_una_carpeta(cliente):
    respx.get(f"{API}/drives").mock(
        return_value=httpx.Response(200, json={"drives": [{"id": "D", "name": "Administración"}]})
    )
    respx.get(f"{API}/files").mock(return_value=httpx.Response(200, json={"files": []}))
    with pytest.raises(DriveNotFound, match="Administración > ANDROMEDA SOLUTIONS"):
        cliente.ruta("Administración", "ANDROMEDA SOLUTIONS/Facturas recibidas AS")


@respx.mock
def test_cliente_pagina_y_reintenta(cliente):
    ruta = respx.get(f"{API}/files").mock(
        side_effect=[
            httpx.Response(503),
            ficheros(("1", "a.pdf", "application/pdf", "x"), siguiente="p2"),
            ficheros(("2", "b.pdf", "application/pdf")),
        ]
    )
    assert [f.id for f in cliente.hijos("C")] == ["1", "2"]
    assert ruta.calls[2].request.url.params["pageToken"] == "p2"


@respx.mock
def test_cliente_sube_en_multipart_sin_reintentar(cliente):
    ruta = respx.post("https://www.googleapis.com/upload/drive/v3/files").mock(
        return_value=httpx.Response(
            200,
            json={"id": "N", "name": "f.pdf", "mimeType": "application/pdf", "md5Checksum": "m"},
        )
    )
    subida = cliente.subir("C", "f.pdf", b"%PDF-1.4")
    peticion = ruta.calls.last.request
    assert subida.id == "N"
    assert peticion.url.params["uploadType"] == "multipart"
    assert b'"parents": ["C"]' in peticion.content and b"%PDF-1.4" in peticion.content

    ruta.mock(return_value=httpx.Response(500))
    with pytest.raises(DriveError):
        cliente.subir("C", "f.pdf", b"%PDF-1.4")
    assert ruta.call_count == 2


@respx.mock
def test_cliente_errores_de_permisos(cliente):
    respx.get(f"{API}/drives").mock(return_value=httpx.Response(403, text="insufficient"))
    with pytest.raises(DriveAuthError):
        cliente.unidad_compartida("Administración")


# --- Botón "Subir a Drive" ------------------------------------------------------------------


@pytest.fixture
def cliente_admin(client, make_user):
    client.force_login(make_user(departments=["Administración"]))
    return client


def test_boton_muestra_las_pendientes_y_encola_la_tarea(cliente_admin, crear, monkeypatch):
    from django.urls import reverse

    crear()
    crear(b"%PDF-1.4 r", tipo="recibo", numero="R-1")  # no cuenta: no se sube
    monkeypatch.setattr("integrations.drive.is_configured", lambda: True)
    encoladas = []
    monkeypatch.setattr(
        "apps.administracion.views.async_task", lambda *a, **kw: encoladas.append((a, kw))
    )

    html = cliente_admin.get(reverse("administracion:facturas")).content.decode()
    assert "Subir a Drive (1 pendiente)" in html

    url = reverse("administracion:facturas_subir_drive")
    respuesta = cliente_admin.post(url, {"volver": "/administracion/facturas/?proveedor=1"})
    assert respuesta.url == "/administracion/facturas/?proveedor=1"
    assert encoladas[0][1]["forzar"] is True
    assert cliente_admin.post(url, {"volver": "https://malo.example/"}).url == reverse(
        "administracion:facturas"
    )


def test_la_tarea_forzada_funciona_aunque_este_desactivada(settings, crear, drive, monkeypatch):
    settings.DRIVE = {**settings.DRIVE, "ACTIVO": False}
    monkeypatch.setattr("integrations.drive.is_configured", lambda: True)
    monkeypatch.setattr("integrations.drive.get_client", lambda: drive)
    crear()
    assert sincronizar_facturas_drive(forzar=True).startswith("1 subidas")


def test_corrige_el_nombre_si_se_subio_antes_de_leer_la_fecha(drive, crear):
    factura = crear(fecha_factura=None, numero="")  # aún sin extraer: fecha del correo
    sincronizar_drive(client=drive)
    factura.refresh_from_db()
    assert factura.drive_nombre == "Acme 2026-04-02 Invoice.pdf"

    # Se extrae después: cambian la fecha y el nº
    FacturaRecibida.objects.filter(pk=factura.pk).update(
        fecha_factura=date(2026, 3, 31), numero_factura="F-1"
    )
    resumen = sincronizar_drive(client=drive)

    factura.refresh_from_db()
    assert resumen.renombradas == ["2026/Acme 2026-04-02 Invoice.pdf → Acme 2026-03-31 F-1.pdf"]
    assert drive.items[factura.drive_id]["name"] == "Acme 2026-03-31 F-1.pdf"
    assert factura.drive_nombre == "Acme 2026-03-31 F-1.pdf"
    assert len(drive.subidas) == 1


@pytest.mark.parametrize("caso", ["renombrada_por_contabilidad", "contabilizada", "probar"])
def test_no_renombra_lo_que_no_debe(drive, crear, caso):
    factura = crear(fecha_factura=None, numero="")
    sincronizar_drive(client=drive)
    factura.refresh_from_db()
    if caso == "renombrada_por_contabilidad":
        drive.items[factura.drive_id]["name"] = "acme marzo.pdf"
    elif caso == "contabilizada":
        anio = drive.buscar("2026", drive.facturas)
        drive.mover(factura.drive_id, drive.buscar("CONTABILIZADO", anio))
    FacturaRecibida.objects.filter(pk=factura.pk).update(
        fecha_factura=date(2026, 3, 31), numero_factura="F-1"
    )

    resumen = sincronizar_drive(client=drive, probar=caso == "probar")

    assert drive.renombradas == []
    assert bool(resumen.renombradas) == (caso == "probar")  # en prueba solo lo anuncia


def test_el_proveedor_siempre_delante(drive, crear):
    anio = drive.carpeta("2026", drive.facturas)
    contabilizado = drive.carpeta("CONTABILIZADO", anio)
    ajena = drive.fichero("EB1F4288.pdf", contabilizado, b"%PDF-1.4 a")
    antigua = drive.fichero("2026-03-31 Acme F-2.pdf", anio, b"%PDF-1.4 b")
    bien = drive.fichero("ACME marzo.pdf", anio, b"%PDF-1.4 c")
    facturas = [crear(b"%PDF-1.4 a"), crear(b"%PDF-1.4 b", numero="F-2"), crear(b"%PDF-1.4 c")]

    sincronizar_drive(client=drive)

    assert drive.items[ajena]["name"] == "Acme EB1F4288.pdf"
    assert drive.items[antigua]["name"] == "Acme 2026-03-31 F-2.pdf"
    assert drive.items[bien]["name"] == "ACME marzo.pdf"
    for f in facturas:
        f.refresh_from_db()
    # La ajena no pasa a ser "nuestra": no se le volverá a cambiar el nombre entero
    assert [f.drive_nombre for f in facturas] == ["", "Acme 2026-03-31 F-2.pdf", ""]

    drive.renombradas.clear()
    sincronizar_drive(client=drive)
    assert drive.renombradas == []
