"""HTTP-level tests against a real database: auth, isolation between users,
and the shared listings queue."""

from __future__ import annotations

import httpx
import pytest
from src.main import app

pytestmark = pytest.mark.asyncio


async def _add_listing(db, company="Acme", role="Engineer", url=None):
    return await db.fetchval(
        "INSERT INTO listings (company, role, url) VALUES ($1, $2, $3) RETURNING id",
        company,
        role,
        url or f"https://jobs.example.com/{company}/{role}",
    )


async def test_requires_sign_in(api):
    await api()  # installs the database override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as anonymous:
        assert (await anonymous.get("/api/applications/")).status_code == 401
        assert (await anonymous.get("/api/listings/")).status_code == 401
        assert (await anonymous.get("/api/auth/me")).status_code == 401


async def test_state_changes_require_the_same_origin_header(api):
    alice = await api()
    response = await alice.client.post(
        "/api/applications/",
        json={"company": "Acme", "role": "Engineer"},
        headers={"X-Requested-With": ""},
    )
    assert response.status_code == 403


async def test_users_cannot_see_or_touch_each_others_applications(api):
    alice = await api("alice@example.com")
    bob = await api("bob@example.com")

    created = await alice.client.post(
        "/api/applications/", json={"company": "Acme", "role": "Engineer"}
    )
    assert created.status_code == 201
    app_id = created.json()["id"]

    listed = await bob.client.get("/api/applications/")
    assert listed.json() == []
    assert listed.headers["x-total-count"] == "0"
    assert (await bob.client.get(f"/api/applications/{app_id}")).status_code == 404
    patch = await bob.client.patch(f"/api/applications/{app_id}", json={"notes": "mine now"})
    assert patch.status_code == 404
    assert (await bob.client.delete(f"/api/applications/{app_id}")).status_code == 404

    stats = (await bob.client.get("/api/applications/stats/summary")).json()
    assert stats["total"] == 0
    assert (await alice.client.get(f"/api/applications/{app_id}")).json()["notes"] is None


async def test_null_status_in_patch_is_ignored_not_a_500(api):
    alice = await api()
    app_id = (
        await alice.client.post("/api/applications/", json={"company": "A", "role": "B"})
    ).json()["id"]
    response = await alice.client.patch(
        f"/api/applications/{app_id}", json={"status": None, "notes": "hi"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPLIED"


async def test_queue_is_per_user_and_apply_links_the_listing(api, db):
    alice = await api("alice@example.com")
    bob = await api("bob@example.com")
    first = await _add_listing(db, "Acme", "Engineer")
    await _add_listing(db, "Globex", "Analyst")

    applied = await alice.client.post(f"/api/listings/{first}/apply")
    assert applied.status_code == 201
    assert applied.json()["listing_id"] == str(first)
    assert applied.json()["status"] == "APPLIED"

    alice_queue = await alice.client.get("/api/listings/")
    assert [row["company"] for row in alice_queue.json()] == ["Globex"]
    assert alice_queue.headers["x-total-count"] == "1"
    assert (await bob.client.get("/api/listings/")).headers["x-total-count"] == "2"

    again = await alice.client.post(f"/api/listings/{first}/apply")
    assert again.status_code == 409


async def test_deleting_an_application_returns_its_listing_to_the_queue(api, db):
    alice = await api()
    listing = await _add_listing(db)
    app_id = (await alice.client.post(f"/api/listings/{listing}/apply")).json()["id"]
    assert (await alice.client.delete(f"/api/applications/{app_id}")).status_code == 204
    assert (await alice.client.get("/api/listings/")).headers["x-total-count"] == "1"
    assert (await alice.client.post(f"/api/listings/{listing}/apply")).status_code == 201


async def test_scraper_trigger_is_admin_only(api):
    alice = await api()
    assert (await alice.client.post("/api/scraper/run")).status_code == 403
    assert (await alice.client.get("/api/scraper/status")).json() == {"status": "idle"}


async def test_removing_someone_from_the_allowlist_ends_their_session(api, monkeypatch):
    alice = await api()
    assert (await alice.client.get("/api/auth/me")).status_code == 200
    monkeypatch.setenv("ALLOWED_EMAILS", "someone-else@example.com")
    from src.core.config import get_settings

    get_settings.cache_clear()
    assert (await alice.client.get("/api/auth/me")).status_code == 403


async def test_me_and_logout(api, db):
    alice = await api()
    me = (await alice.client.get("/api/auth/me")).json()
    assert me["email"] == "alice@example.com"
    assert me["gmail"] is None
    assert me["is_admin"] is False

    assert (await alice.client.post("/api/auth/logout")).status_code == 204
    assert await db.fetchval("SELECT COUNT(*) FROM sessions") == 0


async def test_dev_login_is_unavailable_unless_enabled(api):
    alice = await api()
    response = await alice.client.post("/api/auth/dev-login", json={"email": "x@example.com"})
    assert response.status_code == 404
