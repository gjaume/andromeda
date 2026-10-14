from django.apps import AppConfig


class AdministracionConfig(AppConfig):
    name = "apps.administracion"
    label = "administracion"
    verbose_name = "Administración"

    def ready(self) -> None:
        from core.navigation import Tool, register_tool

        from . import signals  # noqa: F401

        register_tool(
            "administracion",
            Tool(
                label="Inicio de Administración",
                url_name="administracion:index",
                description="Punto de partida para las herramientas de Administración.",
            ),
        )
        register_tool(
            "administracion",
            Tool(
                label="Facturas recibidas",
                url_name="administracion:facturas",
                description="Facturas de proveedores descargadas automáticamente desde Gmail.",
            ),
        )
        register_tool(
            "administracion",
            Tool(
                label="Proveedores",
                url_name="administracion:proveedores",
                description="Proveedores y la etiqueta de Gmail donde llegan sus facturas.",
            ),
        )
