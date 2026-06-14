import pytest

from models import Prospect, QualificationResult, ScrapedData, SiteAnalysis


@pytest.fixture
def tmp_db(tmp_path) -> str:
    """Path to a fresh temporary SQLite database."""
    return str(tmp_path / "test_amorce.db")


@pytest.fixture
def sample_prospect() -> Prospect:
    """A valid Prospect instance for use in tests."""
    return Prospect(
        url="https://example.ma",
        company_name="Example Maroc SARL",
        email="contact@example.ma",
        score=2,
        detected_need="automatisation service client",
        suggested_mission="Chatbot Service Client",
        status="qualified",
    )


@pytest.fixture
def sample_scraped_data() -> ScrapedData:
    """A valid ScrapedData instance for use in tests."""
    return ScrapedData(
        url="https://example.ma",
        company_name="Example Maroc SARL",
        title="Example Maroc - Accueil",
        meta_description="Nous sommes une entreprise marocaine.",
        visible_text="Bienvenue chez Example Maroc. Nous vendons des produits.",
        has_chatbot=False,
        has_catalog=True,
        has_customer_service=False,
        has_contact_form=True,
    )


@pytest.fixture
def sample_analysis() -> SiteAnalysis:
    """A valid SiteAnalysis instance for use in tests."""
    return SiteAnalysis(
        has_chatbot=True,
        has_catalog=True,
        has_customer_service=False,
        has_contact_form=False,
        geo_score=62,
        chatbot_quality="avancé",
        ai_readiness="moyen",
        geo_diagnosis="Site modérément optimisé pour les IA",
        chatbot_diagnosis="Chatbot présent — peut être connecté aux données",
        main_gap="Invisible depuis ChatGPT",
        quick_win="Serveur MCP",
        recommendations=[
            "Brancher le catalogue via MCP",
            "Optimiser les méta pour les IA (GEO)",
            "Upgrader le chatbot avec accès données",
        ],
    )


@pytest.fixture
def sample_qualification() -> QualificationResult:
    """A valid QualificationResult instance for use in tests."""
    return QualificationResult(
        score=2,
        detected_need="automatisation service client",
        reasoning="L'entreprise a un formulaire de contact mais pas de chatbot.",
        suggested_mission="Chatbot Service Client",
    )
