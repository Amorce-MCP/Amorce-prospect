"""Tests for analyzer.py — deterministic GEO scoring + LLM diagnostics."""
import json
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from analyzer import _compute_geo_score, analyze_site
from config import settings
from models import ScrapedData, SiteAnalysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scraped(**kwargs) -> ScrapedData:
    defaults = dict(
        url="https://test.ma",
        company_name="Test Co",
        title="",
        meta_description="",
        visible_text="",
        has_chatbot=False,
        has_catalog=False,
        has_customer_service=False,
        has_contact_form=False,
    )
    defaults.update(kwargs)
    return ScrapedData(**defaults)


_VALID_LLM = {
    "geo_diagnosis": "Site peu optimisé pour les IA",
    "chatbot_diagnosis": "Chatbot absent — opportunité",
    "main_gap": "Invisible depuis ChatGPT",
    "quick_win": "Serveur MCP",
    "recommendations": ["Brancher le catalogue MCP", "Optimiser le GEO", "Ajouter un chatbot"],
}

# visible_text rich enough to reach > 60 with the new GEO signals
_RICH_TEXT = (
    "application/ld+json schema.org faqpage localbusiness "
    "faq foire aux questions comment faire pourquoi pas combien coûte "
    "casablanca maroc test co test co test co "
    "prix dhs % garantie km "
    "blog actualités 2025 guide "
    "facebook.com instagram.com avis "
) + "x" * 100


def _setup_claude(mocker, payload: dict) -> AsyncMock:
    """Patch analyzer.anthropic.AsyncAnthropic to return payload as JSON."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(payload))]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    mocker.patch("analyzer.anthropic.AsyncAnthropic", return_value=mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# New GEO scoring — unit tests on _compute_geo_score directly
# ---------------------------------------------------------------------------

def test_geo_score_returns_breakdown_dict():
    score, breakdown = _compute_geo_score(_make_scraped())
    assert isinstance(score, int)
    assert isinstance(breakdown, dict)
    assert set(breakdown.keys()) == {
        "schema_org", "faq_content", "named_entities",
        "factual_content", "freshness", "multichannel",
    }


def test_geo_schema_org_detected():
    scraped = _make_scraped(visible_text="application/ld+json schema.org")
    _, breakdown = _compute_geo_score(scraped)
    assert breakdown["schema_org"] > 0


def test_geo_faq_content_detected():
    scraped = _make_scraped(
        visible_text="faq foire aux questions comment faire pourquoi pas combien coûte"
    )
    _, breakdown = _compute_geo_score(scraped)
    assert breakdown["faq_content"] >= 15


def test_geo_factual_content_detected():
    scraped = _make_scraped(visible_text="prix dhs % garantie km")
    _, breakdown = _compute_geo_score(scraped)
    assert breakdown["factual_content"] >= 8


def test_geo_freshness_detected():
    scraped = _make_scraped(visible_text="blog actualités 2025 guide")
    _, breakdown = _compute_geo_score(scraped)
    assert breakdown["freshness"] >= 9


def test_geo_multichannel_detected():
    scraped = _make_scraped(visible_text="facebook.com instagram.com avis")
    _, breakdown = _compute_geo_score(scraped)
    assert breakdown["multichannel"] >= 6


def test_geo_max_score_is_100():
    scraped = _make_scraped(visible_text=_RICH_TEXT)
    score, _ = _compute_geo_score(scraped)
    assert score <= 100


def test_geo_empty_site_low_score():
    score, _ = _compute_geo_score(_make_scraped())
    assert score < 15


# ---------------------------------------------------------------------------
# Deterministic scoring (through analyze_site)
# ---------------------------------------------------------------------------

async def test_geo_score_empty_site_is_low(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, _VALID_LLM)

    analysis = await analyze_site(_make_scraped())

    assert analysis.geo_score < 35


async def test_geo_score_rich_site_is_high(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, _VALID_LLM)
    scraped = _make_scraped(visible_text=_RICH_TEXT)

    analysis = await analyze_site(scraped)

    assert analysis.geo_score >= 60


async def test_chatbot_quality_absent(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, _VALID_LLM)

    analysis = await analyze_site(_make_scraped(has_chatbot=False))

    assert analysis.chatbot_quality == "absent"


async def test_chatbot_quality_basique(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, _VALID_LLM)

    analysis = await analyze_site(_make_scraped(has_chatbot=True, has_catalog=False))

    assert analysis.chatbot_quality == "basique"


async def test_chatbot_quality_avance(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, _VALID_LLM)

    analysis = await analyze_site(_make_scraped(has_chatbot=True, chatbot_confidence="high"))

    assert analysis.chatbot_quality == "avancé"


async def test_ai_readiness_levels(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, _VALID_LLM)

    # faible: empty site → score 0
    a_low = await analyze_site(_make_scraped())
    assert a_low.ai_readiness == "faible"

    # moyen: schema + faq + ville + factual + freshness → score ~39
    a_mid = await analyze_site(_make_scraped(
        visible_text=(
            "application/ld+json schema.org itemtype "
            "faq comment casablanca prix dhs blog 2025"
        )
    ))
    assert a_mid.ai_readiness == "moyen"

    # prêt: full signals → score ~76
    a_high = await analyze_site(_make_scraped(
        visible_text=(
            "application/ld+json schema.org faqpage localbusiness itemtype "
            "faq comment faire pourquoi pas combien coûte "
            "casablanca maroc test co test co test co "
            "prix dhs % garantie "
            "blog actualités 2025 guide "
            "facebook.com instagram.com avis"
        )
    ))
    assert a_high.ai_readiness == "prêt"


# ---------------------------------------------------------------------------
# GEO breakdown stored on SiteAnalysis
# ---------------------------------------------------------------------------

async def test_geo_breakdown_stored_in_analysis(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, _VALID_LLM)

    analysis = await analyze_site(_make_scraped())

    assert analysis.geo_breakdown is not None
    assert set(analysis.geo_breakdown.keys()) == {
        "schema_org", "faq_content", "named_entities",
        "factual_content", "freshness", "multichannel",
    }


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def test_analyze_calls_claude_api(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    mock_client = _setup_claude(mocker, _VALID_LLM)
    scraped = _make_scraped(url="https://mysite.ma")

    await analyze_site(scraped)

    assert mock_client.messages.create.called
    content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "mysite.ma" in content


async def test_analyze_calls_claude_with_breakdown(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    mock_client = _setup_claude(mocker, _VALID_LLM)
    scraped = _make_scraped(url="https://mysite.ma")

    await analyze_site(scraped)

    content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Détail GEO" in content
    assert "schema.org" in content


async def test_analyze_claude_failure_returns_fallback(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.APIError(message="down", request=MagicMock(), body=None)
    )
    mocker.patch("analyzer.anthropic.AsyncAnthropic", return_value=mock_client)

    analysis = await analyze_site(_make_scraped())

    assert isinstance(analysis, SiteAnalysis)
    assert analysis.geo_diagnosis != ""


# ---------------------------------------------------------------------------
# Structural constraints
# ---------------------------------------------------------------------------

async def test_analyze_recommendations_max_3(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, {**_VALID_LLM, "recommendations": ["R1", "R2", "R3", "R4", "R5"]})

    analysis = await analyze_site(_make_scraped())

    assert len(analysis.recommendations) <= 3


async def test_full_analysis_global_occaz(mocker):
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    _setup_claude(mocker, {
        "geo_diagnosis": "Site avec contenu riche et signaux positifs",
        "chatbot_diagnosis": "Chatbot présent avec catalogue — potentiel avancé",
        "main_gap": "Invisible depuis ChatGPT",
        "quick_win": "Serveur MCP",
        "recommendations": [
            "Brancher le catalogue via MCP pour ChatGPT",
            "Upgrader le chatbot avec accès aux données réelles",
            "Optimiser les méta pour les IA (GEO)",
        ],
    })
    scraped = _make_scraped(
        url="https://globaloccaz.com",
        title="Voiture occasion Maroc | Global Occaz",
        visible_text=(
            "application/ld+json schema.org Casablanca occasion catalogue "
            "voitures Maroc faq comment acheter prix dhs blog 2025 "
        ) + "x" * 100,
        has_chatbot=True,
        has_catalog=True,
    )

    analysis = await analyze_site(scraped)

    assert analysis.chatbot_quality in ("basique", "avancé")
    assert analysis.geo_score > 30
    assert analysis.quick_win != ""
    assert len(analysis.recommendations) == 3
    assert analysis.geo_breakdown is not None
