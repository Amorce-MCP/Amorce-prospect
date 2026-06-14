import json
import logging
import os
import re
from typing import Any

import anthropic

from config import settings
from models import EmailDraft, LinkedInDraft, Prospect, ScrapedData, SiteAnalysis

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

_SIGNATURE = "L'équipe Amorce — contact.amorce-mcp@protonmail.com"

FORBIDDEN_PHRASES = [
    "une question nous est venue",
    "nous avons pensé que",
    "nous nous sommes dit",
    "nous avons réalisé que",
    "cela nous a fait réfléchir",
    "nous nous sommes demandés",
    "ce qui nous a amenés à vous écrire",
    "c'est pourquoi nous vous contactons",
    "c'est précisément pour cela",
    "c'est exactement ce qu'on fait",
    "c'est là qu'on intervient",
    "bonne base",
    "ça prouve que vous avez compris",
    "là où beaucoup",
    "voici ce que nous proposons",
    "trois leviers",
    "boostez",
    "révolutionnez",
    "maximisez vos conversions",
    "ne ratez pas le train",
    "il répond avec des infos génériques",
    "il ne connaît pas votre stock",
    "il hallucine",
    "il invente des réponses",
]

_FALLBACK_DRAFT = EmailDraft(
    subject="Amorce — intégrer l'IA dans votre entreprise",
    body=(
        "Bonjour,\n\n"
        "Nous aidons les entreprises marocaines à intégrer l'intelligence artificielle "
        "dans leurs processus.\n\n"
        "30 minutes suffisent généralement pour identifier ce qui est le plus pertinent "
        "pour votre situation.\n\n"
        f"{_SIGNATURE}"
    ),
    mission_angle="Intégration IA générale",
)


def _load_prompt(filename: str) -> str:
    """Charge un fichier de prompt depuis le dossier prompts/."""
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _repair_literal_newlines(s: str) -> str:
    """Replace literal newlines inside JSON string values with \\n."""
    result: list[str] = []
    in_string = False
    escaped = False
    for char in s:
        if escaped:
            result.append(char)
            escaped = False
        elif char == "\\":
            result.append(char)
            escaped = True
        elif char == '"':
            in_string = not in_string
            result.append(char)
        elif in_string and char == "\n":
            result.append("\\n")
        elif in_string and char == "\r":
            pass
        else:
            result.append(char)
    return "".join(result)


def _parse_email_response(raw: str) -> dict[str, Any]:
    """Parse Claude's JSON response with two fallback strategies."""
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    repaired = _repair_literal_newlines(clean)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    subject_m = re.search(r'"subject"\s*:\s*"((?:[^"\\]|\\.)*)"', clean, re.S)
    body_m = re.search(r'"body"\s*:\s*"([\s\S]*?)"\s*(?:,\s*"mission_angle"|[}\s]*$)', clean)
    mission_m = re.search(r'"mission_angle"\s*:\s*"((?:[^"\\]|\\.)*)"', clean, re.S)

    if subject_m and body_m:
        logger.warning("JSON email malformé — extraction par regex utilisée.")
        return {
            "subject": subject_m.group(1),
            "body": body_m.group(1).replace("\\n", "\n"),
            "mission_angle": mission_m.group(1) if mission_m else "",
        }

    raise ValueError(f"Impossible de parser la réponse email : {clean[:300]}")


def _post_process(draft: EmailDraft, language: str = "fr") -> EmailDraft:
    """Enforce subject ≤ 65 chars and guarantee signature in body. Log quality issues."""
    subject = draft.subject[:62] + "..." if len(draft.subject) > 65 else draft.subject
    body = draft.body

    if _SIGNATURE not in body:
        body = body.rstrip() + f"\n\n{_SIGNATURE}"

    if body.count(_SIGNATURE) > 1:
        body = body.replace(_SIGNATURE, "").rstrip() + f"\n\n{_SIGNATURE}"

    word_count = len(body.split())
    if not (180 <= word_count <= 230):
        logger.warning("Email word count %d outside target range 180–230.", word_count)

    if language == "fr" and not body.strip().startswith("Bonjour"):
        logger.warning("Email body does not start with 'Bonjour,'.")
    elif language == "en" and not body.strip().lower().startswith(("hello", "dear", "hi")):
        logger.warning("Email body does not start with expected English greeting.")

    if "30 minutes" not in body and "30-minute" not in body:
        logger.warning("Email body missing CTA '30 minutes'.")

    body_lower = body.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in body_lower:
            logger.warning("Forbidden phrase in email: '%s'", phrase)

    bullets = sum(
        1 for line in body.splitlines()
        if line.strip().startswith(("—", "✦", "•", "-"))
    )
    if bullets > 3:
        logger.warning("Email has %d bullets, maximum is 3.", bullets)

    return draft.model_copy(update={"subject": subject, "body": body})


async def write_prospecting_email(
    prospect: Prospect,
    scraped: ScrapedData,
    analysis: SiteAnalysis | None = None,
    questions: list[str] | None = None,
    answers: list[str] | None = None,
    language: str = "fr",
) -> tuple[EmailDraft, dict[str, Any]]:
    """Generate a prospecting email from prospect context.

    Never raises — returns fallback draft and empty trace on any error.
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured — using fallback email for %s", prospect.url)
        return _FALLBACK_DRAFT, {}

    chatbot_label = (
        "oui" if prospect.has_chatbot is True
        else "non" if prospect.has_chatbot is False
        else "inconnu"
    )
    geo_score = analysis.geo_score if analysis else "N/A"
    has_catalog = analysis.has_catalog if analysis else scraped.has_catalog
    has_cs = analysis.has_customer_service if analysis else scraped.has_customer_service

    qa_block = ""
    if questions and answers:
        qa_block = "\n".join(
            f"Q: {q}\nR: {a}" for q, a in zip(questions, answers) if a and a.strip()
        )

    user_message = (
        f"Entreprise : {prospect.company_name}\n"
        f"URL : {prospect.url}\n"
        f"Secteur / besoin détecté : {prospect.detected_need or scraped.visible_text[:200]}\n\n"
        "Signaux détectés :\n"
        f"- Chatbot embarqué : {chatbot_label}\n"
        f"- Catalogue produit : {'oui' if has_catalog else 'non'}\n"
        f"- Service client actif : {'oui' if has_cs else 'non'}\n"
        f"- Score GEO : {geo_score}/100\n\n"
        f"Extrait du site :\n{scraped.visible_text[:400]}\n"
    )

    if qa_block:
        user_message += f"\nInformations recueillies auprès du commercial :\n{qa_block}\n"

    lang_instruction = (
        "Write the email ENTIRELY in English (subject and body)."
        if language == "en"
        else "Rédige l'email ENTIÈREMENT en français (objet et corps)."
    )
    user_message += (
        f"\n{lang_instruction}\n"
        "\nRédige un email de prospection selon les instructions du prompt système.\n"
        "Ne suis pas un framework marketing.\n"
        "Raisonne depuis le business de cette entreprise spécifique.\n"
        "L'objectif est d'obtenir une visio de 30 minutes.\n\n"
        "Retourne uniquement ce JSON valide, sans markdown :\n"
        '{"subject": "...", "body": "...", "mission_angle": "..."}'
    )

    system_prompt = _load_prompt("email_system.txt")

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=settings.EMAIL_MODEL,
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = message.content[0].text if message.content else ""
        trace: dict[str, Any] = {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "raw_response": raw,
            "model": settings.EMAIL_MODEL,
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }
        if not raw or not raw.strip():
            logger.warning("Claude email returned empty response for %s", prospect.url)
            return _FALLBACK_DRAFT, trace
        parsed = _parse_email_response(raw)
        draft = EmailDraft(
            subject=parsed["subject"],
            body=parsed["body"],
            mission_angle=parsed.get("mission_angle", ""),
        )
        return _post_process(draft, language=language), trace
    except Exception as exc:
        logger.error("Email generation failed for %s: %s — using fallback", prospect.url, exc)
        return _FALLBACK_DRAFT, {}


async def generate_email_from_answers(
    prospect: Prospect,
    scraped: ScrapedData,
    analysis: SiteAnalysis,
    questions: list[str],
    answers: list[str],
    language: str = "fr",
) -> tuple[EmailDraft, dict[str, Any]]:
    """Generate email from Q&A answers. Delegates to write_prospecting_email."""
    return await write_prospecting_email(prospect, scraped, analysis, questions, answers, language=language)


async def generate_email_questions(
    prospect: Prospect,
    scraped: ScrapedData,
    analysis: SiteAnalysis,
) -> tuple[list[str], dict[str, Any]]:
    """Generate targeted questions to personalise the prospecting email.

    Never raises — returns fallback questions and an empty trace on any error.
    """
    fallback = [
        "Quel est l'angle principal à utiliser pour accrocher ce prospect ?",
        "Y a-t-il un contact ou une personne spécifique à qui adresser l'email ?",
        "Avez-vous déjà eu un échange avec cette entreprise auparavant ?",
        "Quel résultat concret voulez-vous mettre en avant dans cet email ?",
    ]

    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured — returning fallback questions")
        return fallback, {}

    chatbot_status = (
        "oui" if prospect.has_chatbot is True
        else "non" if prospect.has_chatbot is False
        else "inconnu"
    )

    user_message = (
        f"Entreprise : {prospect.company_name}\n"
        f"URL : {prospect.url}\n"
        f"Contenu du site : {scraped.visible_text[:600]}\n"
        f"Catalogue produit : {'oui' if scraped.has_catalog else 'non'}\n"
        f"Service client actif : {'oui' if scraped.has_customer_service else 'non'}\n"
        f"Chatbot existant : {chatbot_status}\n"
        f"Score GEO (visibilité IA) : {analysis.geo_score}/100\n"
        f"Besoin détecté : {prospect.detected_need}\n"
        f"Mission suggérée : {prospect.suggested_mission}\n\n"
        "Génère exactement 4 questions à poser au commercial Amorce "
        "pour personnaliser l'email de prospection vers cette entreprise.\n"
        "Les questions doivent aider à : identifier un angle d'accroche précis, "
        "comprendre le contexte spécifique, rendre l'email non générique.\n\n"
        'Retourne UNIQUEMENT ce JSON sans markdown :\n'
        '{"questions": ["Q1?", "Q2?", "Q3?", "Q4?"]}'
    )

    system = (
        "Tu es un expert en prospection B2B pour Amorce, une agence IA à Casablanca. "
        "Tu formules des questions courtes et précises pour personnaliser un email commercial. "
        "Réponds UNIQUEMENT en JSON valide sans markdown."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=settings.EMAIL_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = message.content[0].text if message.content else ""
        trace: dict[str, Any] = {
            "system_prompt": system,
            "user_message": user_message,
            "raw_response": raw,
            "model": settings.EMAIL_MODEL,
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }
        if not raw:
            return fallback, trace
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        data = json.loads(clean)
        questions_out = data.get("questions", [])
        return (questions_out if questions_out else fallback), trace
    except (anthropic.APIError, anthropic.APITimeoutError, anthropic.RateLimitError) as exc:
        logger.error("Question generation API error for %s: %s", prospect.url, exc)
        return fallback, {}
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Question generation parse error for %s: %s", prospect.url, exc)
        return fallback, {}


async def polish_email(
    subject: str,
    body: str,
    instruction: str,
    prospect: Prospect,
    history: list[dict[str, str]] | None = None,
    language: str = "fr",
) -> tuple[EmailDraft, dict[str, Any]]:
    """Polish an email draft based on a user instruction.

    history: previous turns as [{"user_message": ..., "raw_response": ...}, ...]
    in chronological order. Enables multi-turn context so Claude remembers prior edits.
    Never raises — returns the original draft and empty trace on any error.
    """
    original = EmailDraft(subject=subject, body=body, mission_angle="")

    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured — returning original email unchanged")
        return original, {}

    instr = instruction.strip() or "Améliore le style, la clarté et l'impact. Garde le même fond et la même structure."

    lang_instruction = (
        "Write the improved email ENTIRELY in English (subject and body)."
        if language == "en"
        else "Rédige l'email amélioré ENTIÈREMENT en français (objet et corps)."
    )
    user_message = (
        f"Voici l'email actuel à améliorer :\n\n"
        f"Objet : {subject}\n\n"
        f"Corps :\n{body}\n\n"
        f"Entreprise ciblée : {prospect.company_name}\n\n"
        f"Instruction d'amélioration : {instr}\n\n"
        f"{lang_instruction}\n\n"
        "Retourne UNIQUEMENT ce JSON sans markdown :\n"
        '{"subject": "...", "body": "...", "mission_angle": ""}'
    )

    system = (
        "Tu es un expert en rédaction d'emails de prospection B2B pour Amorce, "
        "une agence IA basée à Casablanca. "
        "Tu améliores des emails de prospection selon les instructions du commercial, "
        "en conservant le fond et en améliorant la forme. "
        "Réponds UNIQUEMENT en JSON valide sans markdown."
    )

    messages: list[dict[str, str]] = []
    for turn in (history or []):
        if turn.get("user_message") and turn.get("raw_response"):
            messages.append({"role": "user", "content": turn["user_message"]})
            messages.append({"role": "assistant", "content": turn["raw_response"]})
    messages.append({"role": "user", "content": user_message})

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=settings.EMAIL_MODEL,
            max_tokens=700,
            system=system,
            messages=messages,
        )
        raw = message.content[0].text if message.content else ""
        trace: dict[str, Any] = {
            "system_prompt": system,
            "user_message": user_message,
            "raw_response": raw,
            "model": settings.EMAIL_MODEL,
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }
        if not raw or not raw.strip():
            logger.warning("Polish returned empty response — returning original")
            return original, trace
        parsed = _parse_email_response(raw)
        draft = EmailDraft(
            subject=parsed["subject"],
            body=parsed["body"],
            mission_angle=parsed.get("mission_angle", ""),
        )
        return _post_process(draft, language=language), trace
    except Exception as exc:
        logger.error("Email polish failed for %s: %s — returning original", prospect.url, exc)
        return original, {}


# ---------------------------------------------------------------------------
# LinkedIn message generation
# ---------------------------------------------------------------------------

_FALLBACK_LINKEDIN = LinkedInDraft(
    message=(
        "J'ai parcouru votre site et j'ai vu que vous êtes actifs sur un marché "
        "où les comportements de recherche évoluent rapidement.\n\n"
        "Je travaille avec Amorce, une startup marocaine qui intègre l'IA dans les "
        "systèmes d'information. Si le sujet vous semble pertinent, je serais curieux "
        "d'en discuter — 20 minutes suffisent."
    )
)

_LINKEDIN_FORBIDDEN = [
    "je me permets",
    "je prends la liberté",
    "suite à la visite",
    "nous avons pensé que",
    "cela nous a fait réfléchir",
    "c'est là qu'on intervient",
    "voici ce que nous proposons",
    "boostez",
    "révolutionnez",
    "ne ratez pas le train",
    "il hallucine",
    "il invente des réponses",
]


def _post_process_linkedin(draft: LinkedInDraft) -> LinkedInDraft:
    """Log quality issues for LinkedIn messages."""
    message = draft.message
    word_count = len(message.split())
    if word_count > 180:
        logger.warning("LinkedIn message word count %d exceeds 180.", word_count)
    if word_count < 50:
        logger.warning("LinkedIn message word count %d is too short.", word_count)
    msg_lower = message.lower()
    for phrase in _LINKEDIN_FORBIDDEN:
        if phrase in msg_lower:
            logger.warning("Forbidden phrase in LinkedIn message: '%s'", phrase)
    return draft


async def generate_linkedin_message(
    prospect: Prospect,
    scraped: ScrapedData,
    analysis: SiteAnalysis,
    questions: list[str] | None = None,
    answers: list[str] | None = None,
    language: str = "fr",
) -> tuple[LinkedInDraft, dict[str, Any]]:
    """Generate a LinkedIn prospecting message from prospect context.

    Never raises — returns fallback message and empty trace on any error.
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured — using fallback LinkedIn message for %s", prospect.url)
        return _FALLBACK_LINKEDIN, {}

    chatbot_label = (
        "oui" if prospect.has_chatbot is True
        else "non" if prospect.has_chatbot is False
        else "inconnu"
    )
    geo_score = analysis.geo_score if analysis else "N/A"

    qa_block = ""
    if questions and answers:
        qa_block = "\n".join(
            f"Q: {q}\nR: {a}" for q, a in zip(questions, answers) if a and a.strip()
        )

    lang_instruction = (
        "Write the LinkedIn message ENTIRELY in English."
        if language == "en"
        else "Rédige le message LinkedIn ENTIÈREMENT en français."
    )

    user_message = (
        f"Entreprise : {prospect.company_name}\n"
        f"URL : {prospect.url}\n"
        f"Secteur / besoin détecté : {prospect.detected_need or scraped.visible_text[:200]}\n\n"
        "Signaux détectés :\n"
        f"- Chatbot embarqué : {chatbot_label}\n"
        f"- Catalogue produit : {'oui' if scraped.has_catalog else 'non'}\n"
        f"- Service client actif : {'oui' if scraped.has_customer_service else 'non'}\n"
        f"- Score GEO : {geo_score}/100\n\n"
        f"Extrait du site :\n{scraped.visible_text[:400]}\n"
    )

    if qa_block:
        user_message += f"\nInformations recueillies auprès du commercial :\n{qa_block}\n"

    user_message += (
        f"\n{lang_instruction}\n"
        "Rédige un message LinkedIn de prospection selon les instructions du prompt système.\n"
        "100 à 160 mots maximum. Zéro bullet point. Commence par une observation concrète.\n\n"
        "Retourne UNIQUEMENT ce JSON valide, sans markdown :\n"
        '{"message": "..."}'
    )

    system_prompt = _load_prompt("linkedin_system.txt")

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=settings.EMAIL_MODEL,
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = message.content[0].text if message.content else ""
        trace: dict[str, Any] = {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "raw_response": raw,
            "model": settings.EMAIL_MODEL,
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }
        if not raw or not raw.strip():
            logger.warning("Claude LinkedIn returned empty response for %s", prospect.url)
            return _FALLBACK_LINKEDIN, trace
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        parsed = json.loads(clean)
        draft = LinkedInDraft(message=parsed["message"])
        return _post_process_linkedin(draft), trace
    except Exception as exc:
        logger.error("LinkedIn generation failed for %s: %s — using fallback", prospect.url, exc)
        return _FALLBACK_LINKEDIN, {}


async def polish_linkedin_message(
    message_text: str,
    instruction: str,
    prospect: Prospect,
    language: str = "fr",
) -> tuple[LinkedInDraft, dict[str, Any]]:
    """Polish a LinkedIn message draft based on a user instruction.

    Never raises — returns the original message and empty trace on any error.
    """
    original = LinkedInDraft(message=message_text)

    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured — returning original LinkedIn message")
        return original, {}

    instr = instruction.strip() or "Améliore le style et l'impact. Garde la même longueur et le même fond."
    lang_instruction = (
        "Write the improved message ENTIRELY in English."
        if language == "en"
        else "Rédige le message amélioré ENTIÈREMENT en français."
    )

    user_message = (
        f"Voici le message LinkedIn actuel à améliorer :\n\n{message_text}\n\n"
        f"Entreprise ciblée : {prospect.company_name}\n\n"
        f"Instruction : {instr}\n\n"
        f"{lang_instruction}\n\n"
        "100 à 160 mots maximum. Zéro bullet point.\n\n"
        "Retourne UNIQUEMENT ce JSON sans markdown :\n"
        '{"message": "..."}'
    )

    system = (
        "Tu es un expert en messages LinkedIn de prospection B2B pour Amorce, "
        "une startup marocaine qui intègre l'IA dans les systèmes d'information. "
        "Tu améliores des messages LinkedIn courts et directs selon les instructions, "
        "en conservant le fond et en améliorant la forme. "
        "Réponds UNIQUEMENT en JSON valide sans markdown."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = await client.messages.create(
            model=settings.EMAIL_MODEL,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = msg.content[0].text if msg.content else ""
        trace: dict[str, Any] = {
            "system_prompt": system,
            "user_message": user_message,
            "raw_response": raw,
            "model": settings.EMAIL_MODEL,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }
        if not raw or not raw.strip():
            return original, trace
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        parsed = json.loads(clean)
        draft = LinkedInDraft(message=parsed["message"])
        return _post_process_linkedin(draft), trace
    except Exception as exc:
        logger.error("LinkedIn polish failed for %s: %s — returning original", prospect.url, exc)
        return original, {}
