"""Integración de la extracción con la descarga, la subida manual y las pantallas."""

from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from apps.administracion.extraccion import DatosFactura, ExtraccionError, Extractor, Linea
from apps.administracion.extraccion import registro as registro_real
from apps.administracion.extraccion.servicio import extraer_datos
from apps.administracion.models import CorreoFactura, FacturaRecibida, Proveedor
from apps.administracion.templatetags.facturas import dinero


class ExtractorFalso(Extractor):
    clave = "falso"
    nombre = "Falso"
    datos: DatosFactura | Exception | None = None

    def extraer(self, doc):
        assert doc.nombre_archivo == "f.pdf"
        if isinstance(self.datos, Exception):
            raise self.datos
        return self.datos


@pytest.fixture
def extractor(monkeypatch):
    falso = ExtractorFalso()
    falso.datos = DatosFactura(
        numero="F-1",
        moneda="USD",
        base_imponible=Decimal("100.00"),
        impuestos=Decimal("21.00"),
        total=Decimal("121.00"),
        lineas=[
            Linea("Licencia", Decimal("80.00"), Decimal("2"), Decimal("40"), Decimal("21")),
            Linea("Soporte", Decimal("20.00")),
        ],
    )
    monkeypatch.setitem(registro_real, "falso", falso)
    return falso


@pytest.fixture
def factura(db):
    proveedor = Proveedor.objects.create(nombre="Acme", etiqueta_gmail="Acme", extractor="falso")
    ahora = timezone.now()
    correo = CorreoFactura.objects.create(proveedor=proveedor, gmail_id="m1", recibido_en=ahora)
    factura = FacturaRecibida(
        proveedor=proveedor,
        correo=correo,
        gmail_part_id="1",
        nombre_archivo="f.pdf",
        recibida_en=ahora,
    )
    factura.archivo.save("f.pdf", ContentFile(b"%PDF-1.4"), save=False)
    factura.save()
    return factura


def test_guarda_totales_y_lineas(extractor, factura):
    extraer_datos(factura)
    factura.refresh_from_db()

    assert factura.extraccion_estado == "ok"
    assert factura.numero_factura == "F-1"
    assert (factura.moneda, factura.total) == ("USD", Decimal("121.00"))
    assert factura.tipo == "factura"
    lineas = list(factura.lineas.all())
    assert [(linea.orden, linea.descripcion, linea.importe) for linea in lineas] == [
        (1, "Licencia", Decimal("80.00")),
        (2, "Soporte", Decimal("20.00")),
    ]
    assert lineas[0].cantidad == Decimal("2")


def test_volver_a_extraer_reemplaza_las_lineas(extractor, factura):
    extraer_datos(factura)
    extractor.datos.lineas = [Linea("Todo", Decimal("100.00"))]
    extraer_datos(factura)
    assert [linea.descripcion for linea in factura.lineas.all()] == ["Todo"]


def test_si_no_cuadra_queda_para_revisar(extractor, factura):
    extractor.datos.total = Decimal("150.00")
    extraer_datos(factura)
    assert factura.extraccion_estado == "revisar"
    assert "el total es 150.00" in factura.extraccion_detalle
    assert factura.total == Decimal("150.00")  # se guarda igualmente


@pytest.mark.parametrize(
    ("error", "detalle"),
    [
        (ExtraccionError("No encuentro el total"), "No encuentro el total"),
        (ValueError("raro"), "Error inesperado"),
    ],
)
def test_los_errores_quedan_registrados(extractor, factura, error, detalle):
    extraer_datos(factura)
    extractor.datos = error
    extraer_datos(factura)

    assert factura.extraccion_estado == "error"
    assert detalle in factura.extraccion_detalle
    assert factura.total is None
    assert not factura.lineas.exists()


def test_proveedor_sin_extractor(factura):
    Proveedor.objects.filter(pk=factura.proveedor_id).update(extractor="")
    factura.refresh_from_db()
    extraer_datos(factura)
    assert factura.extraccion_estado == "sin_extractor"


def test_se_extrae_al_subir_a_mano(extractor, factura, client, make_user):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(make_user(departments=["Administración"]))
    correo = CorreoFactura.objects.create(
        proveedor=factura.proveedor, gmail_id="m2", recibido_en=timezone.now()
    )
    pdf = SimpleUploadedFile("f.pdf", b"%PDF-1.4 x", content_type="application/pdf")
    client.post(reverse("administracion:subir_facturas", args=[correo.pk]), {"archivos": [pdf]})

    assert correo.facturas.get().extraccion_estado == "ok"


def test_ficha_de_factura_y_volver_a_leer(extractor, factura, client, make_user):
    client.force_login(make_user(departments=["Administración"]))
    extraer_datos(factura)

    html = client.get(reverse("administracion:factura_detalle", args=[factura.pk])).content.decode()
    assert "Licencia" in html
    assert "121,00 USD" in html
    listado = client.get(reverse("administracion:facturas")).content.decode()
    assert "121,00 USD" in listado

    extractor.datos.total = Decimal("999")
    response = client.post(reverse("administracion:factura_extraer", args=[factura.pk]))
    assert response.status_code == 302
    factura.refresh_from_db()
    assert factura.extraccion_estado == "revisar"


@pytest.mark.parametrize(
    ("valor", "moneda", "texto"),
    [
        (Decimal("1234.5"), "EUR", "1.234,50 €"),
        (Decimal("49"), "USD", "49,00 USD"),
        (Decimal("-12.3"), "EUR", "-12,30 €"),
        (None, "EUR", "—"),
    ],
)
def test_formato_de_importes(valor, moneda, texto):
    assert dinero(valor, moneda) == texto


@pytest.mark.parametrize(
    ("valor", "texto"),
    [
        (Decimal("35.6000"), "35,6"),
        (Decimal("2"), "2"),
        (Decimal("1234.5"), "1.234,5"),
        (Decimal("0.0000"), "0"),
        (None, ""),
    ],
)
def test_formato_de_cantidades(valor, texto):
    from apps.administracion.templatetags.facturas import numero

    assert numero(valor) == texto
