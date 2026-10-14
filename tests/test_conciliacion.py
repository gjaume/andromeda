"""Conciliación de facturas con los extractos del banco y de la tarjeta (datos inventados)."""

import io
from datetime import date, datetime
from decimal import Decimal

import httpx
import openpyxl
import pytest
import respx
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from apps.administracion.conciliacion.hojas import asignar_claves, leer_banco, leer_tarjeta
from apps.administracion.conciliacion.servicio import (
    conciliar,
    conciliar_pagos,
    guardar_movimientos,
)
from apps.administracion.models import (
    CorreoFactura,
    Empresa,
    FacturaRecibida,
    MovimientoPago,
    Proveedor,
)
from integrations.drive import DriveFile, get_client
from integrations.drive.client import HOJA_DE_CALCULO

D = Decimal

# --- Hojas de cálculo -----------------------------------------------------------------------


def libro(pestanas: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nombre, filas in pestanas.items():
        ws = wb.create_sheet(nombre)
        for fila in filas:
            ws.append(fila)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


CABECERA_BANCO = ["F. Operativa", "Concepto", "F. Valor", "Importe", "Saldo", "nota", "nota",
                  "Referencia 1", "Referencia 2"]  # fmt: skip

EXTRACTO = libro(
    {
        "BANCO": [
            CABECERA_BANCO,
            ["13/10/2026", "ADEUDO RECIBO ACME HOSTING SL", "13/10/2026", -121.0, 1000.0],
            # Excel convirtió "09/10/2026" en el 10 de septiembre
            [datetime(2026, 9, 10), "TRANSFERENCIA A Ana Alquileres", None, -400.0, 1121.0],
            [datetime(2026, 9, 10), "TARJETA CREDITO EMPRESA", None, -999.0, 1521.0],  # se ignora
            ["01/10/2026", "ABONO TRANSFERENCIA DE CLIENTE", "01/10/2026", 50.0, 2520.0],
        ],
        "OTRA": [["no se lee"]],
    }
)

TARJETA = libro(
    {
        "ENE": [
            ["Fecha", "Concepto", "Importe", None, None, None],
            ["31/01", "NUBE SAAS INC", "DUBLIN", None, "42,50", "EUR"],
            [None, "Importe original: 49,00 USD( cambio aplicado 1 EUR = 0,86 USD )", None],
            [datetime(2026, 12, 1), "CAFETERIA", "PALMA", None, "18,00", "EUR"],  # 12/01
            ["03/12", "CARGO DE DICIEMBRE", "PALMA", None, "5,00", "EUR"],  # del año anterior
            ["10/01", "RARO", "PALMA", None, "???", "EUR"],
        ],
        "FEB": [
            ["Fecha", "Concepto", "Importe"],
            ["02/02", "COLUMNAS DESPLAZADAS", "PALMA", "1.010,05", "EUR"],
            [3.0, "FECHA COMO NUMERO", "PALMA", None, "-7,00", "EUR"],
        ],
    }
)


def test_leer_banco():
    movimientos = leer_banco(EXTRACTO, "BANCO", "extracto.xlsx")
    assert [(m.fecha, m.concepto, m.importe, m.metodo) for m in movimientos] == [
        (date(2026, 10, 13), "ADEUDO RECIBO ACME HOSTING SL", D("121.00"), "domiciliacion"),
        (date(2026, 10, 9), "TRANSFERENCIA A Ana Alquileres", D("400.00"), "transferencia"),
        (date(2026, 10, 1), "ABONO TRANSFERENCIA DE CLIENTE", D("-50.00"), "domiciliacion"),
    ]
    assert movimientos[0].hoja == "extracto.xlsx › BANCO › fila 2"


def test_leer_tarjeta():
    avisos = []
    movimientos = leer_tarjeta(TARJETA, 2026, "tarjeta.xlsx", avisos)
    resumen = [(m.fecha, m.concepto, m.importe, m.importe_original, m.moneda_original)
               for m in movimientos]  # fmt: skip
    assert resumen == [
        (date(2026, 1, 31), "NUBE SAAS INC", D("42.50"), D("49.00"), "USD"),
        (date(2026, 1, 12), "CAFETERIA", D("18.00"), None, ""),
        (date(2025, 12, 3), "CARGO DE DICIEMBRE", D("5.00"), None, ""),
        (date(2026, 2, 2), "COLUMNAS DESPLAZADAS", D("1010.05"), None, ""),
        (date(2026, 2, 3), "FECHA COMO NUMERO", D("-7.00"), None, ""),
    ]
    assert all(m.metodo == "tarjeta" for m in movimientos)
    assert avisos == ["tarjeta.xlsx › ENE › fila 6: No es un importe: '???'"]


def test_claves_estables_y_distintas_para_filas_repetidas():
    def dos_veces():  # la misma fila repetida en la hoja
        return leer_banco(EXTRACTO, "BANCO", "x") + leer_banco(EXTRACTO, "BANCO", "x")

    a = asignar_claves(dos_veces())
    assert len({m.clave for m in a}) == len(a)
    b = asignar_claves(dos_veces())
    assert [m.clave for m in a] == [m.clave for m in b]


# --- Emparejamiento -------------------------------------------------------------------------


@pytest.fixture
def empresa(db):
    return Empresa.objects.create(
        nombre="EMPRESA PRUEBA",
        cif="B00000000",
        extracto_banco="Unidad/EMPRESA/extracto.xlsx",
        extracto_banco_pestana="BANCO",
        extracto_tarjeta="Unidad/EMPRESA/VISA/{anio}/tarjeta.xlsx",
    )


@pytest.fixture
def proveedor(db):
    def crear(nombre, textos=""):
        return Proveedor.objects.create(nombre=nombre, etiqueta_gmail=nombre, textos_pago=textos)

    return crear


@pytest.fixture
def factura(empresa):
    def crear(proveedor, fecha, total, moneda="EUR", **extra):
        cuando = timezone.make_aware(datetime.combine(fecha, datetime.min.time()))
        correo = CorreoFactura.objects.create(
            proveedor=proveedor, gmail_id=f"m{CorreoFactura.objects.count()}", recibido_en=cuando
        )
        f = FacturaRecibida(
            proveedor=proveedor, correo=correo, gmail_part_id="1", nombre_archivo="f.pdf",
            recibida_en=cuando, fecha_factura=fecha, total=D(total), moneda=moneda,
            empresa=empresa, **{"tipo": "factura", **extra},
        )  # fmt: skip
        f.archivo.save("f.pdf", ContentFile(b"%PDF"), save=False)
        f.save()
        return f

    return crear


@pytest.fixture
def movimiento(empresa):
    def crear(fecha, concepto, importe, metodo="domiciliacion", **extra):
        return MovimientoPago.objects.create(
            empresa=empresa, origen="tarjeta" if metodo == "tarjeta" else "banco",
            clave=f"k{MovimientoPago.objects.count()}", fecha=fecha, concepto=concepto,
            importe=D(importe), metodo=metodo, hoja="h", **extra,
        )  # fmt: skip

    return crear


def estado(f):
    f.refresh_from_db()
    return (f.metodo_pago, f.pagada_el, f.pago_id)


def test_casa_importe_textos_y_fecha(empresa, proveedor, factura, movimiento):
    acme = proveedor("Acme", "ACME HOSTING")
    f = factura(acme, date(2026, 10, 1), "121.00")
    movimiento(date(2026, 10, 2), "CAFETERIA", "121.00", "tarjeta")  # importe igual, otro texto
    buena = movimiento(date(2026, 10, 13), "ADEUDO RECIBO Acme Hosting SL", "121.00")

    resumen = conciliar(empresa)

    assert estado(f) == ("domiciliacion", date(2026, 10, 13), buena.pk)
    assert (resumen.pagadas, resumen.pendientes) == (1, 0)


def test_dolares_por_el_importe_original(empresa, proveedor, factura, movimiento):
    nube = proveedor("Nube", "NUBE SAAS")
    f = factura(nube, date(2026, 1, 31), "49.00", "USD")
    m = movimiento(date(2026, 1, 31), "NUBE SAAS INC", "42.50", "tarjeta",
                   importe_original=D("49.00"), moneda_original="USD")  # fmt: skip
    conciliar(empresa)
    assert estado(f) == ("tarjeta", date(2026, 1, 31), m.pk)


def test_recurrentes_cada_una_con_su_pago(empresa, proveedor, factura, movimiento):
    luz = proveedor("Luz", "ELECTRICA")
    facturas = [factura(luz, date(2026, mes, 1), "50.00") for mes in (1, 2, 3)]
    pagos = [movimiento(date(2026, mes, 8), "ELECTRICA SA", "50.00") for mes in (3, 1, 2)]
    conciliar(empresa)
    assert [estado(f)[1] for f in facturas] == [date(2026, m, 8) for m in (1, 2, 3)]
    assert len({estado(f)[2] for f in facturas}) == 3
    assert {p.pk for p in pagos} == {estado(f)[2] for f in facturas}


def test_pago_por_adelantado_y_fuera_de_plazo(empresa, proveedor, factura, movimiento):
    p = proveedor("Firma", "FIRMADIGITAL")
    adelantada = factura(p, date(2026, 3, 1), "100.00")
    tardia = factura(p, date(2026, 1, 1), "200.00")
    movimiento(date(2026, 1, 20), "TRANSFERENCIA A FirmaDigital", "100.00", "transferencia")
    movimiento(date(2026, 6, 1), "TRANSFERENCIA A FirmaDigital", "200.00", "transferencia")
    conciliar(empresa)
    assert estado(adelantada)[0] == "transferencia"
    assert estado(tardia)[0] == ""  # 151 días después: demasiado tarde para ser ese pago


def test_un_pago_para_varias_facturas(empresa, proveedor, factura, movimiento):
    alquiler = proveedor("Alquiler", "ANA ALQUILERES")
    meses = [factura(alquiler, date(2026, mes, 1), "387.60") for mes in range(1, 6)]
    movimiento(date(2026, 1, 3), "TRANSFERENCIA A Ana Alquileres", "387.60", "transferencia")
    junto = movimiento(date(2026, 5, 20), "TRANSFERENCIA A Ana Alquileres", "1550.40",
                       "transferencia")  # fmt: skip
    conciliar(empresa)
    assert [estado(f)[2] == junto.pk for f in meses] == [False, True, True, True, True]


def test_sin_textos_solo_si_es_inequivoco(empresa, proveedor, factura, movimiento):
    p = proveedor("Sin textos")
    f = factura(p, date(2026, 5, 1), "33.33")
    movimiento(date(2026, 5, 3), "LO QUE SEA", "33.33")
    conciliar(empresa)
    assert estado(f)[0] == "domiciliacion"

    movimiento(date(2026, 5, 4), "OTRO", "33.33")
    conciliar(empresa)
    assert estado(f)[0] == ""  # dos candidatos: no se adivina


def test_abonos_con_devoluciones(empresa, proveedor, factura, movimiento):
    p = proveedor("Acme", "ACME")
    abono = factura(p, date(2026, 4, 1), "-20.00", tipo="abono")
    movimiento(date(2026, 4, 5), "ACME DEVOLUCION", "-20.00", "tarjeta")
    conciliar(empresa)
    assert estado(abono)[0] == "tarjeta"


def test_no_concilia_recibos_duplicadas_ni_manuales(empresa, proveedor, factura, movimiento):
    p = proveedor("Acme", "ACME")
    original = factura(p, date(2026, 4, 1), "10.00")
    copia = factura(p, date(2026, 4, 1), "10.00", duplicada_de=original)
    recibo = factura(p, date(2026, 4, 1), "10.00", tipo="recibo")
    manual = factura(p, date(2026, 4, 2), "10.00", pago_manual=True, metodo_pago="transferencia",
                     pagada_el=date(2026, 4, 2))  # fmt: skip
    movimiento(date(2026, 4, 3), "ACME", "10.00", "tarjeta")
    movimiento(date(2026, 4, 3), "ACME", "10.00", "tarjeta")
    conciliar(empresa)
    assert estado(original)[0] == "tarjeta"
    assert estado(copia)[0] == estado(recibo)[0] == ""
    assert estado(manual) == ("transferencia", date(2026, 4, 2), None)


def test_si_desaparece_el_movimiento_deja_de_estar_pagada(empresa, proveedor, factura):
    p = proveedor("Acme", "ACME HOSTING")
    f = factura(p, date(2026, 10, 1), "121.00")
    movimientos = asignar_claves(leer_banco(EXTRACTO, "BANCO", "Unidad/EMPRESA/extracto.xlsx"))
    guardar_movimientos(empresa, movimientos, ["Unidad/EMPRESA/extracto.xlsx"])
    guardar_movimientos(empresa, movimientos, ["Unidad/EMPRESA/extracto.xlsx"])  # idempotente
    assert empresa.movimientos.count() == 3
    conciliar(empresa)
    assert estado(f)[0] == "domiciliacion"

    guardar_movimientos(empresa, movimientos[1:], ["Unidad/EMPRESA/extracto.xlsx"])
    conciliar(empresa)
    assert estado(f)[0] == ""


# --- De punta a punta, con un Drive falso ---------------------------------------------------


class DriveExtractos:
    def __init__(self, ficheros: dict[str, bytes]):
        self.ficheros = ficheros  # "Unidad/carpeta/fichero" → contenido

    def ruta(self, unidad, ruta):
        return f"{unidad}/{ruta}"

    def fichero(self, carpeta, nombre):
        ruta = f"{carpeta}/{nombre}"
        return DriveFile(ruta, nombre, "x") if ruta in self.ficheros else None

    def descargar(self, fichero):
        return self.ficheros[fichero.id]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def test_conciliar_pagos_lee_drive(empresa, proveedor, factura):
    acme = proveedor("Acme", "ACME HOSTING")
    nube = proveedor("Nube", "NUBE SAAS")
    a = factura(acme, date(2026, 10, 1), "121.00")
    n = factura(nube, date(2026, 1, 31), "49.00", "USD")
    drive = DriveExtractos(
        {
            "Unidad/EMPRESA/extracto.xlsx": EXTRACTO,
            "Unidad/EMPRESA/VISA/2026/tarjeta.xlsx": TARJETA,
        }
    )
    resumen = conciliar_pagos(client=drive)
    # Las empresas reales (las crean las migraciones) no están en este Drive: solo un aviso
    assert any("No encuentro" in aviso for aviso in resumen.avisos)
    assert estado(a)[0] == "domiciliacion"
    assert estado(n)[0] == "tarjeta"
    assert resumen.pagadas == 2
    assert "Unidad/EMPRESA/VISA/2026/tarjeta.xlsx" in resumen.ficheros


def test_listado_y_ficha(empresa, proveedor, factura, movimiento, client, make_user):
    client.force_login(make_user(departments=["Administración"]))
    p = proveedor("Acme", "ACME")
    pagada = factura(p, date(2026, 4, 1), "10.00", numero_factura="F-PAGADA")
    factura(p, date(2026, 4, 2), "99.00", numero_factura="F-PENDIENTE")
    movimiento(date(2026, 4, 3), "ACME", "10.00", "tarjeta")
    conciliar(empresa)

    url = reverse("administracion:facturas")
    html = client.get(url).content.decode()
    assert "✓ Tarjeta" in html and "Sin pagar" in html
    pendientes = client.get(url, {"pago": "pendiente"}).content.decode()
    assert "F-PENDIENTE" in pendientes and "F-PAGADA" not in pendientes
    tarjeta = client.get(url, {"pago": "tarjeta"}).content.decode()
    assert "F-PAGADA" in tarjeta and "F-PENDIENTE" not in tarjeta
    ficha = client.get(reverse("administracion:factura_detalle", args=[pagada.pk]))
    assert "Tarjeta: ACME" in ficha.content.decode()


# --- Cliente de Drive: descargas ------------------------------------------------------------


@respx.mock
def test_descargar_fichero_y_exportar_hoja_de_google():
    api = "https://www.googleapis.com/drive/v3/files"
    respx.get(f"{api}/X").mock(return_value=httpx.Response(200, content=b"xlsx"))
    exportar = respx.get(f"{api}/G/export").mock(return_value=httpx.Response(200, content=b"g"))
    with get_client(token_provider=lambda: "t", backoff_base=0) as c:
        assert c.descargar(DriveFile("X", "a.xlsx", "application/vnd.ms-excel")) == b"xlsx"
        assert c.descargar(DriveFile("G", "Hoja", HOJA_DE_CALCULO)) == b"g"
    assert "spreadsheetml" in exportar.calls.last.request.url.params["mimeType"]
