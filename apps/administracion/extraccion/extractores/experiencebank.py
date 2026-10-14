"""ExperienceBank: dos emisores distintos llegan con este proveedor, ambos en inglés.

1. TrekkSoft AG / Experience Bank ("Invoice_INV6283_….pdf"): comisión mensual sobre las ventas.
   "Invoice number: Date of issue:" y debajo "INV6283 31/01/2026". Tabla "PAYMENT DESCRIPTION
   QUANTITY COMMISSION % FEES" con filas como

       Commission March 7,634.80 2.00% EUR 152.70
       descripción     ventas    %     comisión

   y al pie "Subtotal EUR …", "Tax Total EUR …" e "Invoiced amount incl. VAT EUR …". Cada fila
   se guarda con cantidad = importe de ventas y precio unitario = % de comisión / 100.

2. Validated ID, S.L.U. (VIDSigner, "Invoice_INV-VID-000000160.pdf" y "Credit Memo_CN-VID-86.pdf"):
   "Date 31/01/2026", "Invoice # INV-VID-…" o "Credit # CN-VID-…", importes con "€" delante
   ("€396.00"). Tabla "Item Description Quantity Rate Amount": la fila con importes empieza por el
   código del producto y la descripción sigue en las líneas de debajo, que se añaden a la fila.
   Al pie "Subtotal", "Tax Total (%)", "Total" y el cuadro "Tax Rate Subtotal Tax Amount".
   Los "CREDIT MEMO" son rectificativas (tipo "abono"): el PDF muestra los importes en positivo y
   aquí se guardan en negativo (líneas, base, impuestos y total).
"""

import re
from decimal import Decimal

from ..base import (
    IMPORTE,
    DatosFactura,
    Documento,
    ExtraccionError,
    Extractor,
    Linea,
    buscar,
    buscar_grupos,
    fecha,
    importe,
    moneda,
    registrar,
)

# --- TrekkSoft ---
CABECERA_TREKKSOFT = re.compile(r"^PAYMENT DESCRIPTION\s+QUANTITY\s+COMMISSION %\s+FEES$", re.M)
FILA_TREKKSOFT = re.compile(
    rf"^(?P<descripcion>.+?)\s+(?P<ventas>{IMPORTE})\s+(?P<pct>[\d.]+)%\s+[A-Z]{{3}}\s+"
    rf"(?P<comision>{IMPORTE})$"
)

# --- Validated ID ---
CABECERA_VID = re.compile(r"^Item\s+Description\s+Quantity\s+Rate\s+Amount$", re.M)
FILA_VID = re.compile(
    rf"^(?P<descripcion>.+?)\s+(?P<cantidad>[\d.,]+)\s+(?P<precio>-?€\s*{IMPORTE})\s+"
    rf"(?P<importe>-?€\s*{IMPORTE})$"
)
TIPO_IVA_VID = re.compile(rf"^([\d.]+)%\s+{IMPORTE}\s+{IMPORTE}$", re.M)

CENTIMOS = Decimal("0.01")


def _ingles(texto: str) -> Decimal:
    """Importes en formato inglés ("1,768.45", "€0.38")."""
    return importe(texto, decimal=".")


@registrar
class ExperienceBank(Extractor):
    clave = "experiencebank"
    nombre = "ExperienceBank / Validated ID"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        if CABECERA_TREKKSOFT.search(texto):
            return self._trekksoft(texto)
        if CABECERA_VID.search(texto):
            return self._validated_id(texto)
        raise ExtraccionError(
            "Formato desconocido: no es una factura de TrekkSoft ni de Validated ID"
        )

    def _trekksoft(self, texto: str) -> DatosFactura:
        inicio = CABECERA_TREKKSOFT.search(texto)
        fin = re.search(r"^Subtotal\b", texto[inicio.end() :], re.M)
        tabla = texto[inicio.end() : inicio.end() + fin.start()] if fin else ""

        divisa, base = buscar_grupos(
            rf"^Subtotal\s+([A-Z]{{3}})\s+({IMPORTE})$", texto, "el subtotal", flags=re.M
        )
        base = _ingles(base)
        impuestos = _ingles(
            buscar(rf"^Tax Total\s+[A-Z]{{3}}\s+({IMPORTE})$", texto, "el IVA", flags=re.M)
        )
        total = _ingles(
            buscar(
                rf"^Invoiced amount incl\. VAT\s+[A-Z]{{3}}\s+({IMPORTE})$",
                texto,
                "el total",
                flags=re.M,
            )
        )
        pct_iva = (impuestos / base * 100).quantize(CENTIMOS) if base else None

        lineas = []
        for fila in tabla.splitlines():
            if m := FILA_TREKKSOFT.match(fila.strip()):
                lineas.append(
                    Linea(
                        descripcion=m["descripcion"],
                        cantidad=_ingles(m["ventas"]),
                        precio_unitario=_ingles(m["pct"]) / 100,
                        importe=_ingles(m["comision"]).quantize(CENTIMOS),
                        impuesto_pct=pct_iva,
                    )
                )
        if not lineas:
            raise ExtraccionError("No encuentro las líneas de comisión")

        numero, emision = buscar_grupos(
            r"Invoice number:\s*Date of issue:\s*\n\s*(\S+)\s+(\d{1,2}/\d{1,2}/\d{4})",
            texto,
            "el nº de factura y la fecha",
        )
        return DatosFactura(
            numero=numero,
            fecha=fecha(emision),
            moneda=divisa,
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            lineas=lineas,
        )

    def _validated_id(self, texto: str) -> DatosFactura:
        abono = bool(re.search(r"\bCREDIT MEMO\b", texto))
        signo = -1 if abono else 1

        inicio = CABECERA_VID.search(texto)
        fin = re.search(r"^Subtotal\b", texto[inicio.end() :], re.M)
        tabla = texto[inicio.end() : inicio.end() + fin.start()] if fin else ""

        tipos = TIPO_IVA_VID.findall(texto)
        pct_iva = _ingles(tipos[0]) if len(set(tipos)) == 1 else None

        lineas: list[Linea] = []
        for fila in tabla.splitlines():
            fila = fila.strip()
            if m := FILA_VID.match(fila):
                lineas.append(
                    Linea(
                        descripcion=m["descripcion"],
                        cantidad=_ingles(m["cantidad"]),
                        precio_unitario=signo * _ingles(m["precio"]),
                        importe=(signo * _ingles(m["importe"])).quantize(CENTIMOS),
                        impuesto_pct=pct_iva,
                    )
                )
            elif fila and lineas:
                lineas[-1].descripcion += f" {fila}"
        if not lineas:
            raise ExtraccionError("No encuentro las líneas de producto")

        base = _ingles(buscar(rf"^Subtotal\s+(-?€\s*{IMPORTE})$", texto, "el subtotal", flags=re.M))
        impuestos = _ingles(
            buscar(rf"^Tax Total \(%\)\s+(-?€\s*{IMPORTE})$", texto, "el IVA", flags=re.M)
        )
        total = _ingles(buscar(rf"^Total\s+(-?€\s*{IMPORTE})$", texto, "el total", flags=re.M))

        return DatosFactura(
            numero=buscar(r"(?:Invoice|Credit) #\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"(?<!Due )\bDate\s+(\d{1,2}/\d{1,2}/\d{4})", texto, "la fecha")),
            moneda=moneda(texto),
            tipo="abono" if abono else "factura",
            base_imponible=signo * base,
            impuestos=signo * impuestos,
            total=signo * total,
            lineas=lineas,
        )
