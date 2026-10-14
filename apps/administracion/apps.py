from django.apps import AppConfig


class AdministracionConfig(AppConfig):
    name = "apps.administracion"
    label = "administracion"
    verbose_name = "Administración"

    def ready(self) -> None:
        from core.navigation import Tool, register_tool

        register_tool(
            "administracion",
            Tool(
                label="Inicio de Administración",
                url_name="administracion:index",
                description="Punto de partida para las herramientas de Administración.",
            ),
        )
