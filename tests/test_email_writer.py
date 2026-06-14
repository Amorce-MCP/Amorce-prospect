import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings
from email_writer import (
    FORBIDDEN_PHRASES,
    _load_prompt,
    _parse_email_response,
    _post_process,
    _repair_literal_newlines,
    write_prospecting_email,
)
from models import EmailDraft, Prospect, ScrapedData, SiteAnalysis

_SIGNATURE = "contact.amorce-mcp@protonmail.com"

# Reference body used in word-count and content tests (≈ 187 words).
_LONG_BODY = (
    "Bonjour,\n\n"
    "Nous nous permettons de vous contacter — nous sommes Amorce, une startup marocaine "
    "qui intègre l'intelligence artificielle dans les systèmes d'information des entreprises.\n\n"
    "Ce qui a retenu notre attention chez Example Maroc SARL, ce n'est pas votre plateforme "
    "aujourd'hui, mais la manière dont vos futurs clients risquent de vous découvrir demain.\n\n"
    "Une partie des recherches qui passaient hier par Google commence progressivement à passer "
    "par ChatGPT, Claude ou Gemini. Pour une entreprise spécialisée dans votre secteur, cela "
    "soulève une question simple : lorsqu'un prospect cherche vos services à Casablanca, est-ce "
    "que votre nom apparaît dans les réponses ?\n\n"
    "Selon le BCG, le Maroc est déjà le 2ème pays au monde en adoption de ChatGPT. "
    "Ce changement n'est pas dans cinq ans.\n\n"
    "Il existe aujourd'hui plusieurs façons d'y répondre :\n"
    "— améliorer votre visibilité dans les réponses générées ;\n"
    "— rendre votre catalogue accessible depuis les IA ;\n"
    "— intégrer un assistant capable d'agir sur vos services.\n\n"
    "Si le sujet vous semble pertinent, nous serions ravis d'en discuter avec vous.\n\n"
    "30 minutes suffisent généralement pour identifier ce qui est le plus pertinent "
    "pour votre situation.\n\n"
    "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_claude(mocker, json_str: str) -> AsyncMock:
    """Patch anthropic.AsyncAnthropic and settings.ANTHROPIC_API_KEY."""
    mocker.patch.object(settings, "ANTHROPIC_API_KEY", "test-key")
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json_str)]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    mocker.patch("email_writer.anthropic.AsyncAnthropic", return_value=mock_client)
    return mock_client


def _email_json(
    subject: str = "Votre catalogue est-il accessible depuis ChatGPT ?",
    body: str = "Corps de l'email de test.",
    mission_angle: str = "Intégration IA",
) -> str:
    return json.dumps({"subject": subject, "body": body, "mission_angle": mission_angle})


def _make_prospect(**kwargs) -> Prospect:
    defaults = dict(url="https://test.ma", company_name="Test Co")
    defaults.update(kwargs)
    return Prospect(**defaults)


def _make_scraped(**kwargs) -> ScrapedData:
    defaults = dict(
        url="https://test.ma",
        company_name="Test Co",
        title="Test",
        meta_description="",
        visible_text="",
        has_catalog=False,
        has_customer_service=False,
        has_contact_form=False,
    )
    defaults.update(kwargs)
    return ScrapedData(**defaults)


def _make_analysis(**kwargs) -> SiteAnalysis:
    defaults = dict(
        has_catalog=False,
        has_customer_service=False,
        has_contact_form=False,
        geo_score=50,
        ai_readiness="moyen",
        geo_diagnosis="",
        main_gap="",
        quick_win="",
        recommendations=[],
    )
    defaults.update(kwargs)
    return SiteAnalysis(**defaults)


# ---------------------------------------------------------------------------
# Core return type
# ---------------------------------------------------------------------------

async def test_write_email_returns_email_draft(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json())

    result, trace = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert isinstance(result, EmailDraft)
    assert result.subject
    assert result.body


async def test_write_email_returns_trace_dict(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json())

    _, trace = await write_prospecting_email(sample_prospect, sample_scraped_data)

    for key in ("system_prompt", "user_message", "raw_response", "model"):
        assert key in trace


async def test_invalid_llm_json_returns_fallback_email(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, "désolé je ne peux pas")

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert isinstance(result, EmailDraft)
    assert result.subject


async def test_email_personalized_with_company_name(mocker, sample_prospect, sample_scraped_data):
    body = f"Bonjour {sample_prospect.company_name}, nous avons une proposition."
    _setup_claude(mocker, _email_json(body=body))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert sample_prospect.company_name in result.body


async def test_claude_called_with_correct_model(mocker, sample_prospect, sample_scraped_data):
    mock_client = _setup_claude(mocker, _email_json())

    await write_prospecting_email(sample_prospect, sample_scraped_data)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == settings.EMAIL_MODEL


# ---------------------------------------------------------------------------
# Prompt and user message
# ---------------------------------------------------------------------------

def test_load_prompt_reads_file_correctly():
    content = _load_prompt("email_system.txt")

    assert isinstance(content, str)
    assert len(content) > 0
    assert "Amorce" in content
    assert "startup" in content


async def test_write_email_passes_company_name_in_user_message(mocker, sample_prospect, sample_scraped_data):
    mock_client = _setup_claude(mocker, _email_json())

    await write_prospecting_email(sample_prospect, sample_scraped_data)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    user_content = call_kwargs["messages"][0]["content"]
    assert sample_prospect.company_name in user_content
    assert "Catalogue produit" in user_content


async def test_email_no_chatbot_status_reflected_in_user_content(mocker):
    mock_client = _setup_claude(mocker, _email_json())
    prospect = _make_prospect(has_chatbot=False)
    scraped = _make_scraped()

    await write_prospecting_email(prospect, scraped)

    user_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Chatbot embarqué : non" in user_content


async def test_email_chatbot_status_reflected_in_user_content(mocker):
    mock_client = _setup_claude(mocker, _email_json())
    prospect = _make_prospect(has_chatbot=True)
    scraped = _make_scraped()

    await write_prospecting_email(prospect, scraped)

    user_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Chatbot embarqué : oui" in user_content


# ---------------------------------------------------------------------------
# Subject rules
# ---------------------------------------------------------------------------

async def test_email_subject_max_65_chars(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json(subject="A" * 80))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert len(result.subject) <= 65


async def test_email_subject_starts_with_question_or_fact(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json(subject="Votre catalogue est-il sur ChatGPT ?"))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert result.subject.endswith("?") or (
        result.subject[0].isupper()
        and not result.subject.startswith("Bonjour")
        and not result.subject.startswith("Nous")
    )


# ---------------------------------------------------------------------------
# Body invariants
# ---------------------------------------------------------------------------

async def test_email_body_contains_signature(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json(body="Bonjour, voici notre proposition."))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert _SIGNATURE in result.body


async def test_email_has_correct_cta(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json(body=_LONG_BODY))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert "30 minutes" in result.body


async def test_email_starts_with_bonjour(mocker, sample_prospect, sample_scraped_data):
    body = (
        "Bonjour,\n\n"
        "Mubawab centralise des milliers d'annonces immobilières au Maroc.\n\n"
        "30 minutes suffisent généralement pour identifier ce qui est le plus pertinent "
        "pour votre situation.\n\n"
        "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
    )
    _setup_claude(mocker, _email_json(body=body))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert result.body.strip().startswith("Bonjour")


async def test_email_no_jai_vu_opening(mocker, sample_prospect, sample_scraped_data):
    body = (
        "Bonjour,\n\n"
        "Votre catalogue de produits est en ligne — ChatGPT ne le voit pas encore.\n\n"
        "30 minutes suffisent pour votre situation.\n\n"
        "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
    )
    _setup_claude(mocker, _email_json(body=body))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    first_words = " ".join(result.body.split()[:6]).lower()
    assert "j'ai vu" not in first_words


async def test_email_presents_amorce_as_startup_not_agency(mocker, sample_prospect, sample_scraped_data):
    body = (
        "Bonjour,\n\n"
        "Nous nous permettons de vous contacter — nous sommes Amorce, "
        "une startup marocaine qui intègre l'intelligence artificielle "
        "dans les systèmes d'information des entreprises.\n\n"
        "30 minutes suffisent pour identifier ce qui est pertinent pour vous.\n\n"
        "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
    )
    _setup_claude(mocker, _email_json(body=body))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert "nous sommes une agence" not in result.body.lower()
    assert "agence spécialisée" not in result.body.lower()


async def test_email_has_amorce_presentation_early(mocker, sample_prospect, sample_scraped_data):
    """Amorce doit apparaître dans les 50 premiers mots du body."""
    body = (
        "Bonjour,\n\n"
        "Nous nous permettons de vous contacter — nous sommes Amorce, "
        "une startup marocaine qui intègre l'intelligence artificielle "
        "dans les systèmes d'information des entreprises.\n\n"
        "Votre catalogue est en ligne — ChatGPT ne le voit pas encore.\n\n"
        "30 minutes suffisent pour votre situation.\n\n"
        "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
    )
    _setup_claude(mocker, _email_json(body=body))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    first_50_words = " ".join(result.body.split()[:50])
    assert "Amorce" in first_50_words


async def test_email_body_word_count_in_range(mocker, sample_prospect, sample_scraped_data):
    """Corps email : 180 à 230 mots."""
    _setup_claude(mocker, _email_json(body=_LONG_BODY))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    word_count = len(result.body.split())
    assert 180 <= word_count <= 230


async def test_email_body_has_required_elements(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json(body=_LONG_BODY))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    for element in ("Bonjour", "ChatGPT", "Amorce", "30 minutes"):
        assert element in result.body


async def test_email_no_forbidden_phrases(mocker, sample_prospect, sample_scraped_data):
    _setup_claude(mocker, _email_json(body=_LONG_BODY))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    body_lower = result.body.lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase.lower() not in body_lower, f"Forbidden phrase found: {phrase!r}"


async def test_email_contains_no_generic_phrases(mocker, sample_prospect, sample_scraped_data):
    body = (
        "Bonjour,\n\n"
        "Votre catalogue produit n'est pas encore accessible depuis ChatGPT.\n\n"
        "Il existe plusieurs façons d'y répondre.\n\n"
        "30 minutes suffisent pour votre situation.\n\n"
        "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
    )
    _setup_claude(mocker, _email_json(body=body))

    result, _ = await write_prospecting_email(sample_prospect, sample_scraped_data)

    assert "j'espère que ce mail vous trouve bien" not in result.body.lower()
    assert "nous sommes une agence" not in result.body.lower()
    assert "spécialisée en ia" not in result.body.lower()


async def test_chatbot_profile_does_not_attack_existing_chatbot(mocker):
    """When prospect has a chatbot, the body must not use attack phrases."""
    body = (
        "Bonjour,\n\n"
        "Vous avez déjà mis en place un chatbot pour accompagner vos visiteurs. "
        "Le sujet, aujourd'hui, n'est pas seulement de répondre à leurs questions, "
        "mais de savoir jusqu'où cet assistant peut aller dans leur parcours.\n\n"
        "Pour un acheteur, la recherche ne se limite pas à obtenir une information. "
        "Il veut comparer, filtrer, réserver une visite, déclencher une prise de contact.\n\n"
        "Il existe plusieurs façons d'y répondre :\n"
        "— donner à votre chatbot la capacité d'agir ;\n"
        "— rendre votre catalogue accessible depuis les IA.\n\n"
        "30 minutes suffisent généralement pour identifier ce qui est le plus pertinent "
        "pour votre situation.\n\n"
        "L'équipe Amorce — contact.amorce-mcp@protonmail.com"
    )
    _setup_claude(mocker, _email_json(body=body))
    prospect = _make_prospect(has_chatbot=True)
    scraped = _make_scraped()

    result, _ = await write_prospecting_email(prospect, scraped)

    assert "il répond avec des infos génériques" not in result.body.lower()
    assert "il ne connaît pas votre stock" not in result.body.lower()
    assert "il hallucine" not in result.body.lower()
    assert "bonne base" not in result.body.lower()


# ---------------------------------------------------------------------------
# Post-processing unit tests
# ---------------------------------------------------------------------------

def test_post_processing_adds_signature_if_missing():
    draft = EmailDraft(
        subject="Objet test",
        body="Corps de l'email sans signature.",
        mission_angle="GEO",
    )

    result = _post_process(draft)

    assert _SIGNATURE in result.body


def test_post_processing_truncates_long_subject():
    draft = EmailDraft(
        subject="A" * 80,
        body="Corps.",
        mission_angle="GEO",
    )

    result = _post_process(draft)

    assert len(result.subject) == 65
    assert result.subject.endswith("...")


def test_post_processing_keeps_short_subject_unchanged():
    draft = EmailDraft(
        subject="Objet court",
        body="Corps.",
        mission_angle="GEO",
    )

    result = _post_process(draft)

    assert result.subject == "Objet court"


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------

def test_repair_literal_newlines_fixes_multiline_body():
    raw = '{"subject": "Objet", "body": "Bonjour,\n\nCorps ici.", "mission_angle": "GEO"}'
    repaired = _repair_literal_newlines(raw)
    parsed = json.loads(repaired)
    assert parsed["body"] == "Bonjour,\n\nCorps ici."


def test_parse_email_response_standard_json():
    raw = json.dumps({"subject": "Objet", "body": "Corps.", "mission_angle": "GEO"})
    result = _parse_email_response(raw)
    assert result["subject"] == "Objet"


def test_parse_email_response_repairs_literal_newlines():
    raw = '{"subject": "Objet", "body": "Bonjour,\n\nCorps.", "mission_angle": "MCP"}'
    result = _parse_email_response(raw)
    assert result["subject"] == "Objet"
    assert "Bonjour" in result["body"]
