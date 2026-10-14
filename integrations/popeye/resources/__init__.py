"""Funciones tipadas por recurso de popeye (reservas, barcos, agentes…).

Patrón recomendado, un módulo por recurso:

    # integrations/popeye/resources/bookings.py
    from dataclasses import dataclass
    from integrations.popeye import get_client

    @dataclass(frozen=True)
    class Booking:
        id: int
        status: str

    def get_booking(booking_id: int) -> Booking:
        with get_client() as client:
            data = client.get(f"<ruta-real-del-endpoint>/{booking_id}")
        return Booking(id=data["id"], status=data["status"])

Las rutas y campos se añaden aquí cuando se integre cada endpoint real del API WS.
"""
