import re

import pytest
from pydantic import ValidationError

from models import Prospect, QualificationResult, ScrapedData, WorkflowEvent


def test_prospect_has_required_fields(sample_prospect):
    for field in (
        "id", "url", "company_name", "email", "score", "detected_need",
        "suggested_mission", "email_subject", "email_body", "status",
        "error_message", "created_at",
    ):
        assert hasattr(sample_prospect, field)


def test_prospect_default_status_is_pending():
    p = Prospect(url="https://example.com", company_name="Test Corp")
    assert p.status == "pending"


def test_prospect_id_is_uuid_format():
    p = Prospect(url="https://example.com", company_name="Test Corp")
    uuid_re = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    assert uuid_re.match(p.id)


def test_scraped_data_text_truncated_to_3000_chars():
    s = ScrapedData(
        url="https://example.com",
        company_name="Test",
        title="Test",
        meta_description="Test",
        visible_text="a" * 5000,
        has_chatbot=False,
        has_catalog=False,
        has_customer_service=False,
        has_contact_form=False,
    )
    assert len(s.visible_text) == 3000


def test_workflow_event_progress_between_0_and_100():
    with pytest.raises(ValidationError):
        WorkflowEvent(
            workflow_id="wf-1",
            url="https://example.com",
            step="scraping",
            message="Starting",
            progress=101,
        )


def test_qualification_score_must_be_1_2_or_3():
    with pytest.raises(ValidationError):
        QualificationResult(
            score=5,
            detected_need="test",
            reasoning="test",
            suggested_mission="test",
        )
