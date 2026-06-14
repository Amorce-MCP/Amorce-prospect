import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import database
from config import settings
from main import app
from models import Prospect


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(tmp_db, mocker):
    """AsyncClient wired to the FastAPI app with an isolated tmp DB."""
    mocker.patch.object(settings, "DB_PATH", tmp_db)
    await database.init_db(tmp_db)          # defensive: ensure table exists
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

async def test_health_endpoint_returns_200(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["db"] is True


# ---------------------------------------------------------------------------
# Workflow start
# ---------------------------------------------------------------------------

async def test_start_workflow_returns_workflow_id(client, mocker):
    mocker.patch("main._run_workflow", AsyncMock())

    response = await client.post(
        "/api/start-workflow", json={"urls": ["https://example.com"]}
    )
    await asyncio.sleep(0)  # let the background task run to completion

    assert response.status_code == 200
    data = response.json()
    assert "workflow_id" in data
    assert data["url_count"] == 1


async def test_start_workflow_rejects_invalid_urls(client):
    response = await client.post(
        "/api/start-workflow",
        json={"urls": ["pas-une-url", "ftp://invalide"]},
    )

    assert response.status_code == 422


async def test_start_workflow_rejects_more_than_50_urls(client):
    response = await client.post(
        "/api/start-workflow",
        json={"urls": ["https://example.com"] * 51},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Prospect CRUD
# ---------------------------------------------------------------------------

async def test_get_prospects_returns_list(client, sample_prospect):
    p2 = sample_prospect.model_copy(
        update={"id": str(uuid4()), "url": "https://other.ma"}
    )
    await database.insert_prospect(sample_prospect)
    await database.insert_prospect(p2)

    response = await client.get("/api/prospects")

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_prospect_by_id(client, sample_prospect):
    await database.insert_prospect(sample_prospect)

    response = await client.get(f"/api/prospects/{sample_prospect.id}")

    assert response.status_code == 200
    assert response.json()["id"] == sample_prospect.id


async def test_get_nonexistent_prospect_returns_404(client):
    response = await client.get("/api/prospects/nonexistent-id")

    assert response.status_code == 404


async def test_delete_prospect(client, sample_prospect):
    await database.insert_prospect(sample_prospect)

    delete_resp = await client.delete(f"/api/prospects/{sample_prospect.id}")
    assert delete_resp.status_code == 200

    get_resp = await client.get(f"/api/prospects/{sample_prospect.id}")
    assert get_resp.status_code == 404


async def test_delete_all_prospects(client, sample_prospect):
    p2 = sample_prospect.model_copy(
        update={"id": str(uuid4()), "url": "https://other2.ma"}
    )
    p3 = sample_prospect.model_copy(
        update={"id": str(uuid4()), "url": "https://other3.ma"}
    )
    await database.insert_prospect(sample_prospect)
    await database.insert_prospect(p2)
    await database.insert_prospect(p3)

    response = await client.delete("/api/prospects")

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 3
