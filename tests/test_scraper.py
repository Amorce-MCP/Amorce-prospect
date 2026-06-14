import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from scraper import (
    _detect_chatbot,
    _detect_chatbot_vision,
    _scrape_with_playwright,
    scrape_website,
)
from config import settings

# ---------------------------------------------------------------------------
# Shared HTML fixtures
# ---------------------------------------------------------------------------

SIMPLE_HTML = """<html>
  <head>
    <title>Acme Corp - Accueil</title>
    <meta name="description" content="Bienvenue chez Acme.">
  </head>
  <body><p>Bonjour depuis Acme.</p></body>
</html>"""


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _setup_playwright(mocker, html: str = SIMPLE_HTML, goto_error: Exception | None = None):
    """Patch async_playwright; optionally make page.goto raise goto_error.

    Vision is disabled by default to keep these integration tests focused on
    scraping logic. Tests that specifically exercise vision set it up separately.
    """
    mock_page = AsyncMock()
    if goto_error:
        mock_page.goto = AsyncMock(side_effect=goto_error)
    else:
        mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value=html)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.query_selector = AsyncMock(return_value=None)   # no chatbot by default
    mock_page.evaluate = AsyncMock(return_value=False)        # no JS globals by default

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()

    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_pw
    mock_cm.__aexit__.return_value = False

    mocker.patch("scraper.async_playwright", return_value=mock_cm)
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", False)
    return mock_page


def _setup_httpx(mocker, html: str = SIMPLE_HTML, raise_error: Exception | None = None):
    """Patch httpx.AsyncClient; optionally make client.get raise raise_error."""
    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    if raise_error:
        mock_client.get = AsyncMock(side_effect=raise_error)
    else:
        mock_client.get = AsyncMock(return_value=mock_response)

    mocker.patch("scraper.httpx.AsyncClient", return_value=mock_client)
    return mock_client


def _make_page(query_selector_fn=None, evaluate_fn=None) -> AsyncMock:
    """Build a minimal mock Playwright page for _detect_chatbot tests."""
    mock_page = AsyncMock()
    mock_page.query_selector = AsyncMock(
        side_effect=query_selector_fn or (lambda _: None)
    )
    mock_page.evaluate = AsyncMock(
        side_effect=evaluate_fn or (lambda _: False)
    )
    return mock_page


# ---------------------------------------------------------------------------
# scrape_website — integration
# ---------------------------------------------------------------------------

async def test_scrape_valid_url_returns_scraped_data(mocker):
    _setup_playwright(mocker)
    _setup_httpx(mocker)

    result = await scrape_website("https://example.com")

    assert result.url == "https://example.com"
    assert result.scrape_error is None
    assert result.title == "Acme Corp - Accueil"


async def test_scrape_detects_chatbot_from_css_class(mocker):
    html = """<html><head>
    <script src="https://code.tidio.co/xxx.js"></script>
    <title>T</title></head>
    <body><p>Bonjour</p></body></html>"""
    _setup_playwright(mocker, html=html)
    _setup_httpx(mocker, html=html)

    result = await scrape_website("https://example.com")

    assert result.has_chatbot is True
    assert result.chatbot_confidence == "high"


async def test_scrape_detects_catalog_from_keywords(mocker):
    html = """<html><head><title>T</title></head>
    <body><p>Consultez notre catalogue en ligne.</p></body></html>"""
    _setup_playwright(mocker, html=html)
    _setup_httpx(mocker, html=html)

    result = await scrape_website("https://example.com")

    assert result.has_catalog is True


async def test_scrape_detects_contact_form(mocker):
    html = """<html><head><title>T</title></head>
    <body><form><input type="email" name="email"/><button>Envoyer</button></form></body></html>"""
    _setup_playwright(mocker, html=html)
    _setup_httpx(mocker, html=html)

    result = await scrape_website("https://example.com")

    assert result.has_contact_form is True


async def test_scrape_playwright_failure_falls_back_to_httpx(mocker):
    _setup_playwright(mocker, goto_error=Exception("navigation timeout"))
    httpx_mock = _setup_httpx(mocker)

    result = await scrape_website("https://example.com")

    httpx_mock.get.assert_called_once()
    assert result.scrape_error is None


async def test_scrape_both_fail_returns_error_not_exception(mocker):
    _setup_playwright(mocker, goto_error=Exception("Playwright down"))
    _setup_httpx(mocker, raise_error=Exception("httpx down"))

    result = await scrape_website("https://example.com")

    assert isinstance(result.scrape_error, str)
    assert len(result.scrape_error) > 0


async def test_scrape_text_truncated_to_3000_chars(mocker):
    long_html = (
        "<html><head><title>T</title></head>"
        f"<body><p>{'x' * 10_000}</p></body></html>"
    )
    _setup_playwright(mocker, html=long_html)
    _setup_httpx(mocker, html=long_html)

    result = await scrape_website("https://example.com")

    assert len(result.visible_text) <= 3000


async def test_scrape_invalid_url_raises_value_error():
    with pytest.raises(ValueError):
        await scrape_website("pas-une-url")


# ---------------------------------------------------------------------------
# _detect_chatbot — exclusions : liens externes ≠ chatbot
# ---------------------------------------------------------------------------

async def test_whatsapp_link_not_detected_as_chatbot():
    html = '<a href="https://wa.me/212600000000">WhatsApp</a>'
    has_chatbot, confidence = await _detect_chatbot(None, html)
    assert has_chatbot is False
    assert confidence == "none"


async def test_facebook_link_not_detected_as_chatbot():
    html = '<a href="https://facebook.com/page">Facebook</a>'
    has_chatbot, _ = await _detect_chatbot(None, html)
    assert has_chatbot is False


async def test_contact_form_not_detected_as_chatbot():
    html = '<form><input type="email"/><button>Envoyer</button></form>'
    has_chatbot, _ = await _detect_chatbot(None, html)
    assert has_chatbot is False


async def test_tawadoo_pattern_not_chatbot(mocker):
    """Footer avec wa.me + facebook + instagram = moyens de contact, pas chatbot."""
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", False)
    html = (
        '<footer>'
        '<a href="https://wa.me/1234">WhatsApp</a>'
        '<a href="https://facebook.com/tawadoo">Facebook</a>'
        '<a href="https://instagram.com/tawadoo">Instagram</a>'
        '</footer>'
    )
    page = _make_page()
    has_chatbot, confidence = await _detect_chatbot(page, html)
    assert has_chatbot is False
    assert confidence == "none"


# ---------------------------------------------------------------------------
# _detect_chatbot — couche 1 : scripts embarqués connus (confidence=high)
# ---------------------------------------------------------------------------

async def test_tidio_script_detected():
    html = '<script src="//code.tidio.co/abcdef.js"></script>'
    has_chatbot, confidence = await _detect_chatbot(None, html)
    assert has_chatbot is True
    assert confidence == "high"


async def test_crisp_script_detected():
    html = '<script src="https://client.crisp.chat/l.js"></script>'
    has_chatbot, confidence = await _detect_chatbot(None, html)
    assert has_chatbot is True
    assert confidence == "high"


async def test_confidence_high_for_known_script():
    html = '<script src="https://client.crisp.chat/l.js"></script>'
    _, confidence = await _detect_chatbot(None, html)
    assert confidence == "high"


# ---------------------------------------------------------------------------
# _detect_chatbot — couche 3 : éléments DOM (confidence=high)
# ---------------------------------------------------------------------------

async def test_tawk_iframe_detected():
    """iframe tawk.to dans le DOM → détecté avec confidence=high."""
    page = _make_page(
        query_selector_fn=lambda sel: MagicMock() if "tawk.to" in sel else None
    )
    has_chatbot, confidence = await _detect_chatbot(page, "<html></html>")
    assert has_chatbot is True
    assert confidence == "high"


# ---------------------------------------------------------------------------
# _detect_chatbot — couche 2 : variables JS globales (confidence=high)
# ---------------------------------------------------------------------------

async def test_tawk_global_var_detected():
    """window.Tawk_API présent → détecté avec confidence=high."""
    page = _make_page(
        evaluate_fn=lambda expr: "Tawk_API" in expr
    )
    has_chatbot, confidence = await _detect_chatbot(page, "<html></html>")
    assert has_chatbot is True
    assert confidence == "high"


# ---------------------------------------------------------------------------
# _detect_chatbot — couche 4 : détection générique (confidence=medium)
# ---------------------------------------------------------------------------

async def test_confidence_none_when_nothing_found(mocker):
    """Aucun signal Phase 1 et vision désactivée → has_chatbot=False, confidence=none."""
    page = _make_page()
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", False)
    has_chatbot, confidence = await _detect_chatbot(page, "<html><body><p>Bonjour.</p></body></html>")
    assert has_chatbot is False
    assert confidence == "none"


# ---------------------------------------------------------------------------
# _detect_chatbot_vision — tests Phase 2 (screenshot + Claude)
# ---------------------------------------------------------------------------

def _setup_vision_claude(mocker, payload: dict) -> AsyncMock:
    """Patch scraper.anthropic.AsyncAnthropic to return payload as JSON."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(payload))]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    mocker.patch("scraper.anthropic.AsyncAnthropic", return_value=mock_client)
    return mock_client


async def test_vision_detection_calls_claude_with_screenshot(mocker):
    """Phase 2 : screenshot pris et Claude appelé → chatbot détecté."""
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff")
    mock_page.evaluate = AsyncMock(return_value=False)
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", True)
    _setup_vision_claude(mocker, {"has_chatbot": True, "reason": "bulle visible"})

    has_chatbot, confidence = await _detect_chatbot_vision(mock_page)

    mock_page.screenshot.assert_called_once()
    assert has_chatbot is True
    assert confidence == "medium"


async def test_vision_detection_no_chatbot(mocker):
    """Phase 2 : Claude répond false → has_chatbot=False, confidence=none."""
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff")
    mock_page.evaluate = AsyncMock(return_value=False)
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", True)
    _setup_vision_claude(mocker, {"has_chatbot": False, "reason": "aucun widget"})

    has_chatbot, confidence = await _detect_chatbot_vision(mock_page)

    assert has_chatbot is False
    assert confidence == "none"


async def test_vision_skipped_if_known_script_found():
    """Phase 1 court-circuite Phase 2 : screenshot jamais appelé."""
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff")
    mock_page.evaluate = AsyncMock(return_value=False)
    mock_page.query_selector = AsyncMock(return_value=None)

    html = '<script src="//code.tidio.co/abc.js"></script>'
    has_chatbot, confidence = await _detect_chatbot(mock_page, html)

    mock_page.screenshot.assert_not_called()
    assert has_chatbot is True
    assert confidence == "high"


async def test_vision_failure_returns_false_not_exception(mocker):
    """Erreur screenshot → (False, none), jamais d'exception levée."""
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(side_effect=Exception("screenshot failed"))
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", True)

    has_chatbot, confidence = await _detect_chatbot_vision(mock_page)

    assert has_chatbot is False
    assert confidence == "none"


async def test_vision_invalid_json_returns_false(mocker):
    """Réponse non-JSON de Claude → (False, none), jamais d'exception levée."""
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff")
    mock_page.evaluate = AsyncMock(return_value=False)
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", True)
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="je ne sais pas")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    mocker.patch("scraper.anthropic.AsyncAnthropic", return_value=mock_client)

    has_chatbot, _ = await _detect_chatbot_vision(mock_page)

    assert has_chatbot is False


async def test_vision_disabled_by_config(mocker):
    """CHATBOT_VISION_ENABLED=False → screenshot jamais appelé, has_chatbot=False."""
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff")
    mocker.patch.object(settings, "CHATBOT_VISION_ENABLED", False)

    has_chatbot, _ = await _detect_chatbot_vision(mock_page)

    mock_page.screenshot.assert_not_called()
    assert has_chatbot is False


# ---------------------------------------------------------------------------
# _scrape_with_playwright — contraintes techniques
# ---------------------------------------------------------------------------

async def test_scrape_uses_networkidle(mocker):
    """_scrape_with_playwright doit appeler wait_for_load_state('networkidle')."""
    mock_page = _setup_playwright(mocker)
    mocker.patch("asyncio.sleep")

    await _scrape_with_playwright("https://example.com")

    mock_page.wait_for_load_state.assert_called_with("networkidle", timeout=10000)
