import json
import logging
import re
from typing import Any

import anthropic

from config import settings
from models import ScrapedData, SiteAnalysis

logger = logging.getLogger(__name__)

_GEO_SCHEMA_SIGNALS = [
    "application/ld+json",
    "schema.org",
    "itemtype",
    "itemprop",
    '"@type"',
    "faqpage",
    "localbusiness",
    "product",
    "organization",
    "breadcrumb",
]

_GEO_FAQ_SIGNALS = [
    "faq", "foire aux questions",
    "questions fréquentes", "questions courantes",
    "comment ", "pourquoi ", "qu'est-ce que",
    "combien ", "quand ", "où trouver",
    "est-ce que", "puis-je",
]

_GEO_VILLE_MAROC = [
    "casablanca", "rabat", "marrakech", "fès",
    "tanger", "agadir", "meknès", "oujda",
    "maroc", "marocain", "marocaine",
]

_GEO_FACTUAL_SIGNALS = [
    "dhs", "mad", "€", "prix", "tarif", "coût",
    "%", "ans d'expérience", "clients", "véhicules",
    "annonces", "depuis ", "fondé", "créé en",
    "n°1", "premier", "leader", "certifié",
    "garantie", "km", "kilométrage",
]

_GEO_FRESHNESS_SIGNALS = [
    "blog", "actualités", "actualites", "news",
    "article", "publié", "mise à jour",
    "2024", "2025", "2026",
    "dernières", "nouveau", "nouveauté",
    "guide", "conseil", "comment choisir",
]

_GEO_MULTICHANNEL_SIGNALS = [
    "facebook.com", "instagram.com",
    "linkedin.com", "twitter.com", "tiktok.com",
    "google.com/maps", "maps.google",
    "tripadvisor", "trustpilot",
    "avis", "témoignage", "note sur",
    "youtube.com",
    "wa.me", "whatsapp",
]

_SYSTEM_PROMPT = (
    "Tu es un expert en stratégie IA pour les entreprises marocaines. "
    "Tu analyses l'état d'un site web et produis un diagnostic court, "
    "factuel et actionnable. "
    "Réponds UNIQUEMENT en JSON valide sans markdown."
)


def _compute_geo_score(scraped: ScrapedData) -> tuple[int, dict[str, int]]:
    """Return (score 0-100, breakdown) reflecting how likely a LLM is to cite the site."""
    breakdown: dict[str, int] = {}
    score = 0
    html_lower = scraped.visible_text.lower()

    schema_score = min(sum(1 for s in _GEO_SCHEMA_SIGNALS if s in html_lower) * 5, 20)
    breakdown["schema_org"] = schema_score
    score += schema_score

    faq_score = min(sum(1 for s in _GEO_FAQ_SIGNALS if s in html_lower) * 3, 20)
    breakdown["faq_content"] = faq_score
    score += faq_score

    entity_score = 0
    if any(v in html_lower for v in _GEO_VILLE_MAROC):
        entity_score += 8
    company_slug = scraped.company_name.lower() if scraped.company_name else ""
    if company_slug and html_lower.count(company_slug) > 2:
        entity_score += 7
    breakdown["named_entities"] = min(entity_score, 15)
    score += breakdown["named_entities"]

    factual_score = min(sum(1 for s in _GEO_FACTUAL_SIGNALS if s in html_lower) * 2, 15)
    breakdown["factual_content"] = factual_score
    score += factual_score

    freshness_score = min(sum(1 for s in _GEO_FRESHNESS_SIGNALS if s in html_lower) * 3, 15)
    breakdown["freshness"] = freshness_score
    score += freshness_score

    multichannel_score = min(sum(1 for s in _GEO_MULTICHANNEL_SIGNALS if s in html_lower) * 3, 15)
    breakdown["multichannel"] = multichannel_score
    score += multichannel_score

    return min(score, 100), breakdown


def _compute_ai_readiness(geo_score: int) -> str:
    """Map geo_score to a readiness tier."""
    if geo_score < 35:
        return "faible"
    if geo_score < 65:
        return "moyen"
    return "prêt"


def _fallback_diagnostics(
    scraped: ScrapedData,
    geo_score: int,
    quick_win: str,
) -> dict[str, Any]:
    """Build rule-based diagnostics when the LLM is unavailable."""
    if geo_score < 50:
        geo_diagnosis = f"Score GEO : {geo_score}/100 — site peu structuré pour les IA"
    else:
        geo_diagnosis = f"Score GEO : {geo_score}/100 — bonne base pour l'optimisation IA"

    main_gap = "Invisible depuis ChatGPT" if geo_score < 50 else "Contenu non structuré pour les IA"

    recs: list[str] = []
    if scraped.has_catalog:
        recs.append("Connecter le catalogue via un serveur MCP pour être visible dans ChatGPT.")
    if scraped.has_customer_service:
        recs.append("Déployer un chatbot RAG branché sur les vraies données.")
    if geo_score < 65:
        recs.append("Optimiser les méta-données du site pour les moteurs IA (GEO).")
    if not recs:
        recs.append("Mettre en place un serveur MCP pour connecter le site à ChatGPT.")

    return {
        "geo_diagnosis": geo_diagnosis,
        "main_gap": main_gap,
        "quick_win": quick_win,
        "recommendations": recs[:3],
    }


async def _call_claude_diagnostics(
    scraped: ScrapedData,
    geo_score: int,
    geo_breakdown: dict[str, int],
) -> dict[str, Any]:
    """Call Claude for textual diagnostics. Returns {} on any failure."""
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured — using fallback diagnostics for %s", scraped.url)
        return {}

    user_message = (
        f"Site : {scraped.url}\n"
        f"Titre : {scraped.title}\n"
        f"Description : {scraped.meta_description}\n"
        f"Contenu : {scraped.visible_text[:800]}\n"
        f"Signaux : catalogue={scraped.has_catalog}, "
        f"service_client={scraped.has_customer_service}\n"
        f"Score GEO : {geo_score}/100\n"
        f"Détail GEO :\n"
        f"  - Données structurées (schema.org) : {geo_breakdown.get('schema_org', 0)}/20\n"
        f"  - Contenu FAQ/Q&A : {geo_breakdown.get('faq_content', 0)}/20\n"
        f"  - Entités nommées claires : {geo_breakdown.get('named_entities', 0)}/15\n"
        f"  - Contenu factuel/chiffré : {geo_breakdown.get('factual_content', 0)}/15\n"
        f"  - Fraîcheur éditoriale : {geo_breakdown.get('freshness', 0)}/15\n"
        f"  - Présence multi-canaux : {geo_breakdown.get('multichannel', 0)}/15\n\n"
        'Retourne exactement ce JSON :\n'
        '{\n'
        '  "geo_diagnosis": "<1 phrase : état GEO du site>",\n'
        '  "main_gap": "<5 mots max : le manque principal>",\n'
        '  "quick_win": "<5 mots max : action rapide à valeur>",\n'
        '  "recommendations": [\n'
        '    "<recommandation 1 en 1 phrase>",\n'
        '    "<recommandation 2 en 1 phrase>",\n'
        '    "<recommandation 3 en 1 phrase>"\n'
        '  ]\n'
        '}'
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=settings.QUALIFICATION_MODEL,
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = message.content[0].text if message.content else ""
        if not raw or not raw.strip():
            logger.warning("Claude diagnostics returned empty response for %s", scraped.url)
            return {}
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        return json.loads(clean)
    except (anthropic.APIError, anthropic.APITimeoutError, anthropic.RateLimitError) as exc:
        logger.error("Claude diagnostics API error for %s: %s", scraped.url, exc)
        return {}
    except json.JSONDecodeError as exc:
        logger.error("Claude diagnostics response is not valid JSON for %s: %s", scraped.url, exc)
        return {}


async def analyze_site(scraped: ScrapedData) -> SiteAnalysis:
    """Compute a full AI-readiness analysis for a scraped website.

    Never raises — returns a fallback SiteAnalysis on any LLM failure.
    """
    geo_score, geo_breakdown = _compute_geo_score(scraped)
    ai_readiness = _compute_ai_readiness(geo_score)

    if scraped.has_catalog:
        quick_win = "Serveur MCP"
    elif scraped.has_customer_service:
        quick_win = "Chatbot RAG"
    else:
        quick_win = "GEO"

    llm = await _call_claude_diagnostics(scraped, geo_score, geo_breakdown)

    if not llm:
        llm = _fallback_diagnostics(scraped, geo_score, quick_win)

    return SiteAnalysis(
        has_catalog=scraped.has_catalog,
        has_customer_service=scraped.has_customer_service,
        has_contact_form=scraped.has_contact_form,
        geo_score=geo_score,
        geo_breakdown=geo_breakdown,
        ai_readiness=ai_readiness,
        geo_diagnosis=llm.get("geo_diagnosis", ""),
        main_gap=llm.get("main_gap", quick_win),
        quick_win=llm.get("quick_win", quick_win),
        recommendations=llm.get("recommendations", [])[:3],
    )
