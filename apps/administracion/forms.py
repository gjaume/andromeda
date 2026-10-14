from django import forms
from django.conf import settings

from .models import Proveedor


class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = ["nombre", "cif", "email", "etiqueta_gmail", "activo", "notas"]
        widgets = {
            "etiqueta_gmail": forms.TextInput(attrs={"list": "etiquetas-gmail"}),
            "notas": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_etiqueta_gmail(self):
        # Se admite tanto "Iberdrola" como "Gastos/Iberdrola"
        etiqueta = self.cleaned_data["etiqueta_gmail"].strip().strip("/")
        padre = settings.GMAIL["INVOICES_LABEL"] + "/"
        if etiqueta.casefold().startswith(padre.casefold()):
            etiqueta = etiqueta[len(padre) :]
        return etiqueta
