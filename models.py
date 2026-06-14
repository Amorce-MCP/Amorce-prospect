import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class ScrapedData(BaseModel):
    """Raw data extracted from a prospect's website."""

    url: str
    company_name: str
    title: str
    meta_description: str
    visible_text: str
    has_catalog: bool
    has_customer_service: bool
    has_contact_form: bool
    scrape_error: str | None = None

    @field_validator("visible_text")
    @classmethod
    def truncate_visible_text(cls, v: str) -> str:
        return v[:3000]


class QualificationResult(BaseModel):
    """LLM qualification output for a prospect."""

    score: int
    detected_need: str
    reasoning: str
    suggested_mission: str

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: int) -> int:
        if v not in (1, 2, 3):
            raise ValueError("score must be 1, 2, or 3")
        return v


class SiteAnalysis(BaseModel):
    """AI readiness analysis computed for a prospect's website."""

    has_catalog: bool
    has_customer_service: bool
    has_contact_form: bool
    geo_score: int
    ai_readiness: str         # "faible" | "moyen" | "prêt"
    geo_diagnosis: str
    main_gap: str
    quick_win: str
    recommendations: list[str]
    geo_breakdown: dict[str, int] | None = None


class EmailDraft(BaseModel):
    """Generated email for a prospect."""

    subject: str
    body: str
    mission_angle: str


class Prospect(BaseModel):
    """Full prospect record stored in the database."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    url: str
    company_name: str
    email: str | None = None
    score: int = 0
    detected_need: str = ""
    suggested_mission: str = ""
    has_chatbot: bool | None = None   # set manually by user
    email_subject: str | None = None
    email_body: str | None = None
    status: str = "pending"
    error_message: str | None = None
    analysis: SiteAnalysis | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class WorkflowEvent(BaseModel):
    """Real-time event emitted via WebSocket during prospect processing."""

    workflow_id: str
    url: str
    step: str
    message: str
    progress: int
    data: dict[str, Any] | None = None

    @field_validator("progress")
    @classmethod
    def validate_progress(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("progress must be between 0 and 100")
        return v


class EmailQuestionsResponse(BaseModel):
    """Questions generated for email personalization."""

    questions: list[str]


class EmailGenerateRequest(BaseModel):
    """Q&A pairs submitted to generate the email."""

    questions: list[str]
    answers: list[str]
    language: str = "fr"


class EmailPolishRequest(BaseModel):
    """Polish request — current draft plus optional user instruction."""

    subject: str
    body: str
    instruction: str = ""
    language: str = "fr"


class EmailSaveRequest(BaseModel):
    """Save manual edits to the email draft."""

    subject: str
    body: str


class LinkedInDraft(BaseModel):
    """Generated LinkedIn message for a prospect."""

    message: str


class LinkedInGenerateRequest(BaseModel):
    """Q&A pairs submitted to generate the LinkedIn message."""

    questions: list[str]
    answers: list[str]
    language: str = "fr"


class LinkedInPolishRequest(BaseModel):
    """Polish request for a LinkedIn message."""

    message: str
    instruction: str = ""
    language: str = "fr"
