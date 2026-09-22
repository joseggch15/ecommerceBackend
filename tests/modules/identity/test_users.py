"""Pruebas de integración del módulo de identidad (perfil y direcciones)."""

from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str = "buyer@example.com") -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": "Comprador"},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    return str(login.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_get_me_requires_auth(integration_client: AsyncClient) -> None:
    resp = await integration_client.get("/api/v1/users/me")
    assert resp.status_code == 401


async def test_get_me_returns_profile(integration_client: AsyncClient) -> None:
    token = await _register_and_login(integration_client)
    resp = await integration_client.get("/api/v1/users/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "buyer@example.com"
    assert resp.json()["profile"]["full_name"] == "Comprador"


async def test_update_profile(integration_client: AsyncClient) -> None:
    token = await _register_and_login(integration_client)
    resp = await integration_client.patch(
        "/api/v1/users/me",
        json={
            "full_name": "Nuevo Nombre",
            "preferred_currency": "usd",
            "timezone": "America/New_York",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"]["full_name"] == "Nuevo Nombre"
    assert body["profile"]["preferred_currency"] == "USD"
    assert body["profile"]["timezone"] == "America/New_York"


async def test_addresses_crud(integration_client: AsyncClient) -> None:
    token = await _register_and_login(integration_client)

    created = await integration_client.post(
        "/api/v1/users/me/addresses",
        json={
            "label": "Casa",
            "recipient_name": "Comprador",
            "line1": "Calle 1 # 2-3",
            "city": "Bogotá",
            "country": "co",
            "phone": "3001234567",
        },
        headers=_auth(token),
    )
    assert created.status_code == 201
    address = created.json()
    assert address["is_default"] is True
    assert address["country"] == "CO"

    listed = await integration_client.get("/api/v1/users/me/addresses", headers=_auth(token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = await integration_client.patch(
        f"/api/v1/users/me/addresses/{address['id']}",
        json={"label": "Oficina"},
        headers=_auth(token),
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Oficina"

    deleted = await integration_client.delete(
        f"/api/v1/users/me/addresses/{address['id']}", headers=_auth(token)
    )
    assert deleted.status_code == 204

    listed_after = await integration_client.get("/api/v1/users/me/addresses", headers=_auth(token))
    assert listed_after.json() == []
