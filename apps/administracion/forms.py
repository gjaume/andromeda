from django import forms
from django.conf import settings

from .models import Proveedor, opciones_extractores


class ProveedorForm(forms.ModelForm):
    extractores = forms.MultipleChoiceField(
        label="Formatos de factura",
        required=False,
        choices=opciones_extractores,
        widget=forms.CheckboxSelectMultiple,
        help_text="Los que leen sus PDF. Marca varios si el proveedor ha cambiado el diseño de "
        "sus facturas: se prueban todos y gana el que cuadra. Ninguno = no se extraen.",
    )

    class Meta:
        model = Proveedor
        fields = [
            "nombre",
            "cif",
            "email",
            "etiqueta_gmail",
            "extractores",
            "textos_pago",
            "activo",
            "notas",
        ]
        widgets = {
            "etiqueta_gmail": forms.TextInput(attrs={"list": "etiquetas-gmail"}),
            "textos_pago": forms.Textarea(attrs={"rows": 2}),
            "notas": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_etiqueta_gmail(self):
        # Se admite tanto "Iberdrola" como "Gastos/Iberdrola"
        etiqueta = self.cleaned_data["etiqueta_gmail"].strip().strip("/")
        padre = settings.GMAIL["INVOICES_LABEL"] + "/"
        if etiqueta.casefold().startswith(padre.casefold()):
            etiqueta = etiqueta[len(padre) :]
        return etiqueta


MAX_PDF_MB = 20


class VariosArchivosInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class VariosPdfField(forms.FileField):
    widget = VariosArchivosInput(attrs={"accept": "application/pdf,.pdf"})

    def clean(self, data, initial=None):
        archivos = data if isinstance(data, (list, tuple)) else [data]
        if not any(archivos):
            raise forms.ValidationError("Elige al menos un PDF.")
        validos = []
        for archivo in archivos:
            validos.append(self.validar_pdf(super().clean(archivo, initial)))
        return validos

    @staticmethod
    def validar_pdf(archivo):
        if not archivo.name.lower().endswith(".pdf"):
            raise forms.ValidationError(f"«{archivo.name}» no es un PDF.")
        if archivo.size > MAX_PDF_MB * 1024 * 1024:
            raise forms.ValidationError(f"«{archivo.name}» ocupa más de {MAX_PDF_MB} MB.")
        cabecera = archivo.read(5)
        archivo.seek(0)
        if cabecera != b"%PDF-":
            raise forms.ValidationError(f"«{archivo.name}» no parece un PDF válido.")
        return archivo


class SubirFacturasForm(forms.Form):
    archivos = VariosPdfField(label="Facturas en PDF")
