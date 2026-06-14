import asyncio
import logging
import re
import sys
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from config import settings
from models import ScrapedData

logger = logging.getLogger(__name__)

# SelectorEventLoop (used by uvicorn on Windows) does not support subprocess creation.
# Playwright requires subprocess to launch the browser, so it fails with NotImplementedError
# on Windows + Python >= 3.14. Fall back to httpx-only mode in that case.
_USE_PLAYWRIGHT = not (sys.platform == "win32" and sys.version_info >= (3, 14))

_CATALOG_KEYWORDS = frozenset({
    "produit", "catalogue", "boutique", "shop", "article", "annonce", "listing",
})
_SERVICE_KEYWORDS = frozenset({
    "faq", "support", "aide", "assistance", "service client", "contactez", "formulaire",
})


# ── URL validation ───────────────────────────────────────────────────────────

def _validate_url(url: str) -> None:
    """Raise ValueError if url is not a valid http/https URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url!r}")


# ── HTML parsing ─────────────────────────────────────────────────────────────

def _detect_contact_form(soup: BeautifulSoup) -> bool:
    """Return True if the page contains a form with an email input."""
    for form in soup.find_all("form"):
        if form.find("input", attrs={"type": re.compile(r"^email$", re.I)}):
            return True
    return False


def _extract_metadata(url: str, soup: BeautifulSoup) -> dict[str, Any]:
    """Extract all ScrapedData fields from a parsed page."""
    title = soup.title.get_text(strip=True) if soup.title else ""

    meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_description = meta_tag.get("content", "") if meta_tag else ""

    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    company_name = og_site.get("content", "") if og_site else ""
    if not company_name:
        company_name = re.sub(r"\s*[-|–]\s*.*$", "", title).strip()

    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()

    visible_text = " ".join(soup.stripped_strings)[:3000]
    text_lower = visible_text.lower()

    return {
        "company_name": company_name,
        "title": title,
        "meta_description": meta_description,
        "visible_text": visible_text,
        "has_catalog": any(kw in text_lower for kw in _CATALOG_KEYWORDS),
        "has_customer_service": any(kw in text_lower for kw in _SERVICE_KEYWORDS),
        "has_contact_form": _detect_contact_form(soup),
    }


# ── Scrapers ─────────────────────────────────────────────────────────────────

async def _scrape_with_playwright(url: str) -> ScrapedData:
    """Scrape using a headless browser with networkidle wait."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, timeout=settings.SCRAPE_TIMEOUT * 1000)
            await page.wait_for_load_state("networkidle", timeout=10000)
            await asyncio.sleep(1.5)
            html = await page.content()
            meta = _extract_metadata(url, BeautifulSoup(html, "lxml"))
            return ScrapedData(url=url, **meta)
        finally:
            await browser.close()


async def _scrape_with_httpx(url: str) -> ScrapedData:
    """Scrape with httpx + BeautifulSoup (no JS rendering)."""
    async with httpx.AsyncClient(
        timeout=settings.SCRAPE_TIMEOUT, follow_redirects=True
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text
        meta = _extract_metadata(url, BeautifulSoup(html, "lxml"))
        return ScrapedData(url=url, **meta)


# ── Public entry point ───────────────────────────────────────────────────────

async def scrape_website(url: str) -> ScrapedData:
    """Scrape a website and return structured data.

    Raises ValueError for malformed URLs. Never raises for network/parse
    errors — returns ScrapedData with scrape_error set instead.
    """
    _validate_url(url)

    if _USE_PLAYWRIGHT:
        try:
            return await _scrape_with_playwright(url)
        except Exception as exc:
            logger.warning("Playwright failed for %s: %s — trying httpx fallback", url, exc)

    try:
        return await _scrape_with_httpx(url)
    except Exception as exc:
        logger.error("Both scrapers failed for %s: %s", url, exc)
        return ScrapedData(
            url=url,
            company_name="",
            title="",
            meta_description="",
            visible_text="",
            has_catalog=False,
            has_customer_service=False,
            has_contact_form=False,
            scrape_error=str(exc),
        )
