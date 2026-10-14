"""Facturas duplicadas: el mismo nº del mismo proveedor recibido en varios correos."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from apps.administracion.extraccion import DatosFactura, Extractor, Linea
from apps.administracion.extraccion import registro as registro_real
from apps.administracion.extraccion.servicio import extraer_datos, marcar_todos_los_duplicados
from apps.administracion.models import CorreoFactura, FacturaRecibida, Proveedor


class ExtractorPorNombre(Extractor):
    """Devuelve el nº de factura y el tipo que indique `datos[nombre_archivo]`."""

    clave = "por_nombre"
    nombre = "Por nombre"
    datos: dict[str, tuple[str, str]] = {}

    def extraer(self, doc):
        numero, tipo = self.datos[doc.nombre_archivo]
        return DatosFactura(
            numero=numero,
            tipo=tipo,
            moneda="EUR",
            base_imponible=Decimal("10"),
            impuestos=Decimal("0"),
            total=Decimal("10"),
            lineas=[Linea("Servicio", Decimal("10"))],
        )


@pytest.fixture
def extractor(monkeypatch):
    falso = ExtractorPorNombre()
    falso.datos = {}
    monkeypatch.setitem(registro_real, "por_nombre", falso)
    return falso


@pytest.fixture
def proveedor(db):
    return Proveedor.objects.create(nombre="Acme", etiqueta_gmail="Acme", extractor="por_nombre")


@pytest.fixture
def nueva(extractor, proveedor):
    """Crea y extrae una factura recibida `dias` después de la primera."""
    inicio = timezone.now() - timedelta(days=30)

    def crear(nombre, numero, *, tipo="factura", dias=0, prov=None):
        prov = prov or proveedor
        extractor.datos[nombre] = (numero, tipo)
        cuando = inicio + timedelta(days=dias)
        correo = CorreoFactura.objects.create(
            proveedor=prov, gmail_id=f"m-{nombre}", recibido_en=cuando
        )
        factura = FacturaRecibida(
            proveedor=prov, correo=correo, gmail_part_id="1", nombre_archivo=nombre,
            recibida_en=cuando,
        )  # fmt: skip
        factura.archivo.save(nombre, ContentFile(b"%PDF-1.4"), save=False)
        factura.save()
        return extraer_datos(factura)

    return crear


def test_la_primera_es_la_original_y_las_demas_duplicadas(nueva):
    original = nueva("a.pdf", "F-1")
    copia = nueva("b.pdf", "F-1", dias=3)
    otra = nueva("c.pdf", "F-2", dias=5)

    assert original.duplicada_de is None
    assert copia.duplicada_de == original
    assert otra.duplicada_de is None
    assert list(FacturaRecibida.objects.sin_duplicados()) == [otra, original]


def test_una_copia_recibida_antes_pasa_a_ser_la_original(nueva):
    tardia = nueva("a.pdf", "F-1", dias=10)
    temprana = nueva("b.pdf", "F-1", dias=1)  # p. ej. subida a mano de un correo antiguo

    tardia.refresh_from_db()
    assert temprana.duplicada_de is None
    assert tardia.duplicada_de == temprana


@pytest.mark.parametrize(
    "distinta",
    [
        {"tipo": "recibo"},  # factura y recibo de pago pueden compartir nº
        {"prov": "otro"},  # mismo nº en otro proveedor
    ],
)
def test_no_son_duplicadas_si_cambia_tipo_o_proveedor(nueva, distinta):
    if distinta.get("prov"):
        distinta["prov"] = Proveedor.objects.create(
            nombre="Otro", etiqueta_gmail="Otro", extractor="por_nombre"
        )
    nueva("a.pdf", "F-1")
    assert nueva("b.pdf", "F-1", dias=1, **distinta).duplicada_de is None


def test_sin_numero_no_se_marca(nueva):
    nueva("a.pdf", "")
    assert nueva("b.pdf", "", dias=1).duplicada_de is None


def test_si_al_volver_a_leer_cambia_el_numero_se_recalcula(nueva, extractor):
    original = nueva("a.pdf", "F-1")
    copia = nueva("b.pdf", "F-1", dias=1)
    tercera = nueva("c.pdf", "F-1", dias=2)

    extractor.datos["a.pdf"] = ("F-9", "factura")
    extraer_datos(original)

    copia.refresh_from_db()
    tercera.refresh_from_db()
    assert original.duplicada_de is None
    assert copia.duplicada_de is None
    assert tercera.duplicada_de == copia


def test_al_borrar_la_original_la_siguiente_ocupa_su_lugar(nueva):
    original = nueva("a.pdf", "F-1")
    copia = nueva("b.pdf", "F-1", dias=1)
    tercera = nueva("c.pdf", "F-1", dias=2)

    original.delete()

    copia.refresh_from_db()
    tercera.refresh_from_db()
    assert copia.duplicada_de is None
    assert tercera.duplicada_de == copia


def test_recalcular_todos(nueva):
    original = nueva("a.pdf", "F-1")
    copia = nueva("b.pdf", "F-1", dias=1)
    FacturaRecibida.objects.update(duplicada_de=None)

    assert marcar_todos_los_duplicados() == 1
    copia.refresh_from_db()
    assert copia.duplicada_de == original


def test_pantallas(nueva, client, make_user):
    client.force_login(make_user(departments=["Administración"]))
    original = nueva("a.pdf", "F-1")
    copia = nueva("b.pdf", "F-1", dias=1)

    listado = client.get(reverse("administracion:facturas")).content.decode()
    assert listado.count(">duplicada</a>") == 1
    ficha = client.get(reverse("administracion:factura_detalle", args=[copia.pk])).content.decode()
    assert "es un <strong>duplicado</strong>" in ficha
    ficha = client.get(reverse("administracion:factura_detalle", args=[original.pk]))
    assert "volvió a llegar en 1 correo más" in ficha.content.decode()

    por_mes = client.get(
        reverse("administracion:facturas_por_mes"), {"anio": original.recibida_en.year}
    )
    filas = por_mes.context["filas"]
    contadas = sum(c["facturas"] for fila in filas for c in fila["meses"])
    assert contadas == 1
