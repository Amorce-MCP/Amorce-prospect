"""Integration test: full scrape → qualify → email pipeline via the HTTP API."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import database
from config import settings
from main import app
from models import EmailDraft, QualificationResult, ScrapedData, SiteAnalysis


@pytest.fixture
async def client(tmp_db, mocker):
    mocker.patch.object(settings, "DB_PATH", tmp_db)
    await database.init_db(tmp_db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def test_full_workflow_pipeline(client, sample_analysis):
    """Scrape → analyze → qualify → email → persisted prospect, all mocked."""
    scraped = ScrapedData(
        url="https://testcorp.ma",
        company_name="TestCorp",
        title="TestCorp – solutions e-commerce",
        meta_description="Boutique en ligne TestCorp",
        visible_text="Bienvenue chez TestCorp",
        has_chatbot=True,
        has_catalog=True,
        has_customer_service=False,
        has_contact_form=False,
    )
    qualification = QualificationResult(
        score=3,
        detected_need="Chatbot e-commerce + catalogue produits",
        suggested_mission="MCP + Marketplace",
        reasoning="Site e-commerce avec chatbot intégré.",
    )
    email_draft = EmailDraft(
        subject="Objet test",
        body=(
            "Corps test.\n\n"
            "30 minutes. Votre situation. Notre diagnostic.\n\n"
            "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
        ),
        mission_angle="MCP + Marketplace",
    )

    with (
        patch("scraper.scrape_website", AsyncMock(return_value=scraped)),
        patch("analyzer.analyze_site", AsyncMock(return_value=sample_analysis)),
        patch("qualifier.qualify_prospect", AsyncMock(return_value=qualification)),
        patch("email_writer.write_prospecting_email", AsyncMock(return_value=email_draft)),
    ):
        resp = await client.post(
            "/api/start-workflow",
            json={"urls": ["https://testcorp.ma"]},
        )
        assert resp.status_code == 200

        await asyncio.sleep(0.5)

    prospects = await client.get("/api/prospects")
    assert prospects.status_code == 200

    data = prospects.json()
    assert len(data) == 1

    p = data[0]
    assert p["score"] == 3
    assert p["status"] == "email_written"
    assert p["email_subject"] == "Objet test"
    assert p["company_name"] == "TestCorp"
    assert p["suggested_mission"] == "MCP + Marketplace"
