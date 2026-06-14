import json
import logging
import os
import re
from typing import Any

import anthropic

from config import settings
from models import QualificationResult, ScrapedData, SiteAnalysis

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

VALID_MISSIONS = frozenset({
    "Serveur MCP", "Chatbot RAG", "MCP + Marketplace", "Workflows n8n", "GEO"
})


def _load_prompt(filename: str) -> str:
    """Charge un fichier de prompt depuis le dossier prompts/."""
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _rule_based_score(scraped: ScrapedData) -> tuple[int, str]:
    """Return (score, candidate_mission) using detected signal heuristics."""
    if scraped.has_catalog and scraped.has_customer_service:
        return 3, "Serveur MCP"
    if scraped.has_catalog:
        return 3, "Serveur MCP"
    if scraped.has_customer_service and scraped.has_contact_form:
        return 2, "Chatbot RAG"
    return 1, "GEO"


def _build_user_message(
    scraped: ScrapedData, initial_score: int, candidate_mission: str
) -> str:
    template = _load_prompt("qualification_user.txt")
    return template.format(
        title=scraped.title,
        meta_description=scraped.meta_description,
        visible_text=scraped.visible_text[:1500],
        has_catalog=scraped.has_catalog,
        has_customer_service=scraped.has_customer_service,
        has_contact_form=scraped.has_contact_form,
        initial_score=initial_score,
        candidate_mission=candidate_mission,
    )


async def _call_claude(prompt: str) -> dict[str, Any]:
    """Call Claude API and return parsed JSON, or {} on any error."""
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured — skipping LLM qualification")
        return {}
    system_prompt = _load_prompt("qualification_system.txt")
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=settings.QUALIFICATION_MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text if message.content else ""
        if not raw or not raw.strip():
            logger.warning("Claude qualification returned empty response")
            return {}
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        return json.loads(clean)
    except (anthropic.APIError, anthropic.APITimeoutError, anthropic.RateLimitError) as exc:
        logger.error("Claude qualification API error: %s", exc)
        return {}
    except json.JSONDecodeError as exc:
        logger.error("Claude qualification response is not valid JSON: %s", exc)
        return {}


def _validate_llm_result(result: dict[str, Any]) -> bool:
    """Return True only if the LLM result has a valid score, mission, and detected_need."""
    return (
        result.get("score") in (1, 2, 3)
        and result.get("suggested_mission", "") in VALID_MISSIONS
        and bool(result.get("detected_need", ""))
    )


async def qualify_prospect(
    scraped: ScrapedData, analysis: SiteAnalysis | None = None
) -> QualificationResult:
    """Qualify a scraped prospect using rules then Claude enrichment.

    Never raises — returns rule-based result on any LLM failure.
    """
    initial_score, candidate_mission = _rule_based_score(scraped)
    user_message = _build_user_message(scraped, initial_score, candidate_mission)

    llm_result = await _call_claude(user_message)

    if not llm_result or not _validate_llm_result(llm_result):
        if llm_result:
            logger.warning("Invalid LLM response: %s — using rule-based result", llm_result)
        return QualificationResult(
            score=initial_score,
            detected_need=f"Besoin identifié : {candidate_mission}",
            reasoning="Qualification basée sur les signaux techniques du site.",
            suggested_mission=candidate_mission,
        )

    return QualificationResult(
        score=llm_result["score"],
        detected_need=llm_result["detected_need"],
        reasoning=llm_result.get("reasoning", ""),
        suggested_mission=llm_result["suggested_mission"],
    )
