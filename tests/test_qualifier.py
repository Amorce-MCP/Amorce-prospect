import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic

from config import settings
from models import ScrapedData
from qualifier import _call_claude, qualify_prospect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scraped(**kwargs) -> ScrapedData:
    """Create a minimal ScrapedData with all booleans False by default."""
    defaults = dict(
        url="https://example.ma",
        company_name="Test SARL",
        title="Test",
        meta_description="",
        visible_text="",
        has_chatbot=False,
        has_catalog=False,
        has_customer_service=False,
        has_contact_form=False,
    )
    return ScrapedData(**{**defaults, **kwargs})


def _llm_ok(score: int = 2, mission: str = "GEO") -> dict:
    return {
        "score": score,
        "detected_need": "Besoin d'automatisation IA",
        "reasoning": "Le site montre des signaux d'IA.",
        "suggested_mission": mission,
    }


def _mock_claude(mocker, return_value: dict) -> AsyncMock:
    """Patch _call_claude to return the given dict."""
    return mocker.patch("qualifier._call_claude", AsyncMock(return_value=return_value))


def _setup_anthropic_mock(mocker, json_payload: dict) -> AsyncMock:
    """Patch anthropic.AsyncAnthropic directly and return the mock client."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(json_payload))]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    mocker.patch("qualifier.anthropic.AsyncAnthropic", return_value=mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# Rule-based scoring
# ---------------------------------------------------------------------------

async def test_qualify_chatbot_and_catalog_gives_score_3(mocker):
    scraped = _scraped(has_chatbot=True, has_catalog=True)
    _mock_claude(mocker, _llm_ok(3, "MCP + Marketplace"))

    result = await qualify_prospect(scraped)

    assert result.score == 3
    assert result.suggested_mission == "MCP + Marketplace"


async def test_qualify_chatbot_only_suggests_rag(mocker):
    scraped = _scraped(has_chatbot=True, has_catalog=False)
    _mock_claude(mocker, {})

    result = await qualify_prospect(scraped)

    assert result.suggested_mission == "Chatbot RAG"


async def test_qualify_catalog_only_suggests_mcp(mocker):
    scraped = _scraped(has_catalog=True, has_chatbot=False)
    _mock_claude(mocker, {})

    result = await qualify_prospect(scraped)

    assert result.suggested_mission == "Serveur MCP"


async def test_qualify_empty_site_gives_score_1(mocker):
    scraped = _scraped()
    _mock_claude(mocker, {})

    result = await qualify_prospect(scraped)

    assert result.score == 1


# ---------------------------------------------------------------------------
# Claude API integration
# ---------------------------------------------------------------------------

async def test_qualify_calls_claude_api(mocker):
    scraped = _scraped()
    mock_client = _setup_anthropic_mock(mocker, _llm_ok(1, "GEO"))

    await qualify_prospect(scraped)

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == settings.QUALIFICATION_MODEL


async def test_qualify_claude_api_error_uses_rule_based_fallback(mocker):
    scraped = _scraped(has_customer_service=True, has_contact_form=True)
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.APIError(message="server error", request=MagicMock(), body=None)
    )
    mocker.patch("qualifier.anthropic.AsyncAnthropic", return_value=mock_client)

    result = await qualify_prospect(scraped)

    assert result.score == 2


async def test_qualify_claude_timeout_uses_rule_based_fallback(mocker):
    scraped = _scraped(has_chatbot=True)
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.APITimeoutError(request=MagicMock())
    )
    mocker.patch("qualifier.anthropic.AsyncAnthropic", return_value=mock_client)

    result = await qualify_prospect(scraped)

    assert result.score == 3
    assert result.suggested_mission == "Chatbot RAG"


async def test_qualify_claude_rate_limit_uses_rule_based_fallback(mocker):
    scraped = _scraped()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.RateLimitError(
            message="rate limited", response=MagicMock(), body=None
        )
    )
    mocker.patch("qualifier.anthropic.AsyncAnthropic", return_value=mock_client)

    result = await qualify_prospect(scraped)

    assert result.score == 1


# ---------------------------------------------------------------------------
# LLM result validation
# ---------------------------------------------------------------------------

async def test_qualify_invalid_llm_json_uses_rule_based_fallback(mocker):
    scraped = _scraped(has_customer_service=True, has_contact_form=True)
    _mock_claude(mocker, {})

    result = await qualify_prospect(scraped)

    assert result.score == 2


async def test_qualify_llm_can_upgrade_score(mocker):
    scraped = _scraped(has_customer_service=True, has_contact_form=True)
    _mock_claude(mocker, _llm_ok(3, "Chatbot RAG"))

    result = await qualify_prospect(scraped)

    assert result.score == 3


async def test_qualify_llm_score_out_of_range_is_ignored(mocker):
    scraped = _scraped(has_customer_service=True, has_contact_form=True)
    _mock_claude(mocker, {
        "score": 5,
        "detected_need": "test",
        "reasoning": "test",
        "suggested_mission": "GEO",
    })

    result = await qualify_prospect(scraped)

    assert result.score == 2


# ---------------------------------------------------------------------------
# _call_claude direct tests
# ---------------------------------------------------------------------------

async def test_call_claude_returns_parsed_json(mocker):
    payload = {"score": 3, "detected_need": "besoin", "reasoning": "ok", "suggested_mission": "Chatbot RAG"}
    _setup_anthropic_mock(mocker, payload)

    result = await _call_claude("test prompt")

    assert result["score"] == 3
    assert result["suggested_mission"] == "Chatbot RAG"


async def test_call_claude_api_error_returns_empty_dict(mocker):
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.APIError(message="error", request=MagicMock(), body=None)
    )
    mocker.patch("qualifier.anthropic.AsyncAnthropic", return_value=mock_client)

    result = await _call_claude("test prompt")

    assert result == {}
