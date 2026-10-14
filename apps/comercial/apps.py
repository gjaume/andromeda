from django.apps import AppConfig


class ComercialConfig(AppConfig):
    name = "apps.comercial"
    label = "comercial"
    verbose_name = "Comercial"

    def ready(self) -> None:
        from core.navigation import Tool, register_tool

        register_tool(
            "comercial",
            Tool(
                label="Inicio de Comercial",
                url_name="comercial:index",
                description="Punto de partida para las herramientas de Comercial.",
            ),
        )
