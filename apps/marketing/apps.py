from django.apps import AppConfig


class MarketingConfig(AppConfig):
    name = "apps.marketing"
    label = "marketing"
    verbose_name = "Marketing"

    def ready(self) -> None:
        from core.navigation import Tool, register_tool

        register_tool(
            "marketing",
            Tool(
                label="Inicio de Marketing",
                url_name="marketing:index",
                description="Punto de partida para las herramientas de Marketing.",
            ),
        )
