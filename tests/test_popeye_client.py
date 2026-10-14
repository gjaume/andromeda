import httpx
import pytest
import respx

from core.models import PopeyeApiCall
from integrations.popeye import (
    PopeyeAuthError,
    PopeyeClientError,
    PopeyeNotFound,
    PopeyeUnavailable,
    get_client,
)

BASE = "https://popeye.test/ws"


@pytest.fixture
def client():
    with get_client(backoff_base=0) as c:
        yield c


@respx.mock
def test_get_sends_token_and_parses_json(client):
    route = respx.get(f"{BASE}/boats/7").mock(return_value=httpx.Response(200, json={"id": 7}))
    assert client.get("/boats/7") == {"id": 7}
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_get_retries_on_5xx_then_succeeds(client):
    route = respx.get(f"{BASE}/boats").mock(
        side_effect=[httpx.Response(502), httpx.Response(503), httpx.Response(200, json=[])]
    )
    assert client.get("boats") == []
    assert route.call_count == 3


@respx.mock
def test_get_gives_up_after_max_retries(client):
    respx.get(f"{BASE}/boats").mock(side_effect=httpx.ConnectTimeout("timeout"))
    with pytest.raises(PopeyeUnavailable):
        client.get("boats")


@respx.mock
@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, PopeyeAuthError),
        (403, PopeyeAuthError),
        (404, PopeyeNotFound),
        (422, PopeyeClientError),
    ],
)
def test_errors_are_typed(client, status, exc):
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(status, text="nope"))
    with pytest.raises(exc) as info:
        client.get("x")
    assert info.value.status_code == status


@respx.mock
def test_writes_are_not_retried_and_are_audited(client, make_user):
    user = make_user()
    route = respx.post(f"{BASE}/bookings/1/notes").mock(return_value=httpx.Response(500))
    with pytest.raises(PopeyeUnavailable):
        client.post("bookings/1/notes", json={"text": "hola"}, actor=user)

    assert route.call_count == 1
    call = PopeyeApiCall.objects.get()
    assert call.user == user
    assert call.method == "POST"
    assert call.status_code == 500
    assert call.request_body == {"text": "hola"}


@respx.mock
def test_successful_write_is_audited(client, make_user):
    user = make_user()
    respx.patch(f"{BASE}/bookings/1").mock(return_value=httpx.Response(200, json={"ok": True}))
    assert client.patch("bookings/1", json={"status": "confirmed"}, actor=user) == {"ok": True}
    assert PopeyeApiCall.objects.filter(user=user, status_code=200).exists()


@respx.mock
def test_reads_are_not_audited(client, db):
    respx.get(f"{BASE}/boats").mock(return_value=httpx.Response(200, json=[]))
    client.get("boats")
    assert not PopeyeApiCall.objects.exists()
