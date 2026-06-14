import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

import analyzer
import database
import email_writer
import qualifier
import scraper
from config import settings
from models import (
    EmailGenerateRequest,
    EmailPolishRequest,
    EmailQuestionsResponse,
    EmailSaveRequest,
    LinkedInGenerateRequest,
    LinkedInPolishRequest,
    Prospect,
    WorkflowEvent,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
active_connections: dict[str, WebSocket] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    if settings.ANTHROPIC_API_KEY:
        logger.info("Anthropic API configured (%s...)", settings.ANTHROPIC_API_KEY[:15])
    else:
        logger.warning(
            "ANTHROPIC_API_KEY not set — qualification and emails will use fallback. "
            "Add your key to .env and restart."
        )
    yield


app = FastAPI(title="AMORCE Prospector", lifespan=lifespan)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class WorkflowStartRequest(BaseModel):
    urls: list[str]

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v: list[str]) -> list[str]:
        if len(v) > 50:
            raise ValueError("Maximum 50 URLs allowed")
        for url in v:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f"Invalid URL: {url!r}")
        return v


class ChatbotUpdateRequest(BaseModel):
    has_chatbot: bool | None


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------

async def _emit(
    workflow_id: str,
    url: str,
    step: str,
    message: str,
    progress: int,
    data: dict | None = None,
) -> None:
    event = WorkflowEvent(
        workflow_id=workflow_id,
        url=url,
        step=step,
        message=message,
        progress=progress,
        data=data,
    )
    ws = active_connections.get(workflow_id)
    if ws is not None:
        try:
            await ws.send_json(event.model_dump())
        except Exception as exc:
            logger.warning("WebSocket send failed for %s: %s", workflow_id, exc)


# ---------------------------------------------------------------------------
# Workflow engine — scrape + analyse + qualify only (no auto email)
# ---------------------------------------------------------------------------

async def _process_url(
    workflow_id: str, url: str, semaphore: asyncio.Semaphore
) -> None:
    try:
        async with semaphore:
            await _emit(workflow_id, url, "scraping", "Visite du site...", 10)
            scraped = await scraper.scrape_website(url)

            if scraped.scrape_error:
                await _emit(
                    workflow_id, url, "error",
                    f"Erreur scraping: {scraped.scrape_error}", 0,
                )
                return

            await _emit(workflow_id, url, "analyzing", "Analyse de l'état IA du site...", 40)
            site_analysis = await analyzer.analyze_site(scraped)

            await _emit(workflow_id, url, "qualifying", "Qualification du prospect...", 70)
            qualification = await qualifier.qualify_prospect(scraped, site_analysis)

            prospect = Prospect(
                url=url,
                company_name=scraped.company_name,
                score=qualification.score,
                detected_need=qualification.detected_need,
                suggested_mission=qualification.suggested_mission,
                status="qualified",
                analysis=site_analysis,
            )

            await database.insert_prospect(prospect)
            await _emit(
                workflow_id, url, "done", "Prospect enregistré", 100,
                data=prospect.model_dump(),
            )
    except Exception as exc:
        logger.error("Error processing %s: %s", url, exc)
        await _emit(workflow_id, url, "error", f"Erreur inattendue: {exc}", 0)


async def _run_workflow(workflow_id: str, urls: list[str]) -> None:
    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_SCRAPES)
    tasks = [_process_url(workflow_id, url, semaphore) for url in urls]
    await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# API — prospects
# ---------------------------------------------------------------------------

@app.post("/api/start-workflow")
async def start_workflow(request: WorkflowStartRequest) -> dict:
    workflow_id = str(uuid4())
    asyncio.create_task(_run_workflow(workflow_id, request.urls))
    return {"workflow_id": workflow_id, "url_count": len(request.urls)}


@app.get("/api/prospects")
async def get_prospects() -> list[Prospect]:
    return await database.get_all_prospects()


@app.get("/api/prospects/{prospect_id}")
async def get_prospect(prospect_id: str) -> Prospect:
    prospect = await database.get_prospect(prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


@app.delete("/api/prospects")
async def delete_all_prospects_endpoint() -> dict:
    count = await database.clear_all_prospects()
    return {"deleted_count": count}


@app.delete("/api/prospects/{prospect_id}")
async def delete_prospect_endpoint(prospect_id: str) -> dict:
    deleted = await database.delete_prospect(prospect_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return {"deleted": True}


@app.patch("/api/prospects/{prospect_id}/chatbot")
async def update_chatbot(prospect_id: str, body: ChatbotUpdateRequest) -> dict:
    """Set the manual has_chatbot flag on a prospect."""
    value = None if body.has_chatbot is None else int(body.has_chatbot)
    updated = await database.update_prospect(prospect_id, has_chatbot=value)
    if not updated:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return {"has_chatbot": body.has_chatbot}


# ---------------------------------------------------------------------------
# API — email workflow
# ---------------------------------------------------------------------------

@app.post("/api/prospects/{prospect_id}/email/questions")
async def email_questions(prospect_id: str) -> EmailQuestionsResponse:
    """Generate personalisation questions for the email workflow."""
    prospect = await database.get_prospect(prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if prospect.analysis is None:
        raise HTTPException(status_code=422, detail="Prospect not yet analysed")

    scraped_stub = _prospect_to_scraped_stub(prospect)
    questions, trace = await email_writer.generate_email_questions(
        prospect, scraped_stub, prospect.analysis
    )
    await database.log_email_interaction(
        prospect_id, "questions",
        {"company": prospect.company_name, "questions": questions},
        llm_trace=trace,
    )
    return EmailQuestionsResponse(questions=questions)


@app.post("/api/prospects/{prospect_id}/email/generate")
async def email_generate(prospect_id: str, body: EmailGenerateRequest) -> dict:
    """Generate an email draft from Q&A answers."""
    prospect = await database.get_prospect(prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if prospect.analysis is None:
        raise HTTPException(status_code=422, detail="Prospect not yet analysed")

    scraped_stub = _prospect_to_scraped_stub(prospect)

    await database.log_email_interaction(
        prospect_id, "qa",
        {
            "company": prospect.company_name,
            "questions": body.questions,
            "answers": body.answers,
        },
    )

    draft, trace = await email_writer.generate_email_from_answers(
        prospect, scraped_stub, prospect.analysis,
        body.questions, body.answers,
        language=body.language,
    )
    await database.update_prospect(
        prospect_id,
        email_subject=draft.subject,
        email_body=draft.body,
        status="email_written",
    )
    await database.log_email_interaction(
        prospect_id, "generate",
        {
            "company": prospect.company_name,
            "subject_out": draft.subject,
            "body_out": draft.body,
            "mission": prospect.suggested_mission,
        },
        llm_trace=trace,
    )
    return {"subject": draft.subject, "body": draft.body}


@app.post("/api/prospects/{prospect_id}/email/polish")
async def email_polish(prospect_id: str, body: EmailPolishRequest) -> dict:
    """Polish the current email draft with an optional user instruction."""
    prospect = await database.get_prospect(prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")

    logs = await database.get_email_logs(prospect_id)
    history = [
        {"user_message": log["user_message"], "raw_response": log["raw_response"]}
        for log in reversed(logs)
        if log["type"] in ("generate", "polish")
        and log.get("user_message")
        and log.get("raw_response")
    ]

    draft, trace = await email_writer.polish_email(
        body.subject, body.body, body.instruction, prospect, history=history, language=body.language
    )
    await database.update_prospect(
        prospect_id,
        email_subject=draft.subject,
        email_body=draft.body,
    )
    await database.log_email_interaction(
        prospect_id, "polish",
        {
            "company": prospect.company_name,
            "instruction": body.instruction,
            "subject_before": body.subject,
            "body_before": body.body,
            "subject_after": draft.subject,
            "body_after": draft.body,
        },
        llm_trace=trace,
    )
    return {"subject": draft.subject, "body": draft.body}


@app.post("/api/prospects/{prospect_id}/linkedin/generate")
async def linkedin_generate(prospect_id: str, body: LinkedInGenerateRequest) -> dict:
    """Generate a LinkedIn message draft from Q&A answers."""
    prospect = await database.get_prospect(prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if prospect.analysis is None:
        raise HTTPException(status_code=422, detail="Prospect not yet analysed")

    scraped_stub = _prospect_to_scraped_stub(prospect)

    draft, trace = await email_writer.generate_linkedin_message(
        prospect, scraped_stub, prospect.analysis,
        body.questions, body.answers,
        language=body.language,
    )
    await database.log_email_interaction(
        prospect_id, "linkedin_generate",
        {
            "company": prospect.company_name,
            "questions": body.questions,
            "answers": body.answers,
            "message_out": draft.message,
        },
        llm_trace=trace,
    )
    return {"message": draft.message}


@app.post("/api/prospects/{prospect_id}/linkedin/polish")
async def linkedin_polish(prospect_id: str, body: LinkedInPolishRequest) -> dict:
    """Polish a LinkedIn message draft with an optional user instruction."""
    prospect = await database.get_prospect(prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")

    draft, trace = await email_writer.polish_linkedin_message(
        body.message, body.instruction, prospect, language=body.language
    )
    await database.log_email_interaction(
        prospect_id, "linkedin_polish",
        {
            "company": prospect.company_name,
            "instruction": body.instruction,
            "message_before": body.message,
            "message_after": draft.message,
        },
        llm_trace=trace,
    )
    return {"message": draft.message}


@app.patch("/api/prospects/{prospect_id}/email")
async def email_save(prospect_id: str, body: EmailSaveRequest) -> dict:
    """Save manual edits to the email draft."""
    updated = await database.update_prospect(
        prospect_id,
        email_subject=body.subject,
        email_body=body.body,
        status="email_written",
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return {"saved": True}


# ---------------------------------------------------------------------------
# API — health
# ---------------------------------------------------------------------------

@app.get("/api/email-logs")
async def get_email_logs(prospect_id: str | None = None) -> list:
    """Return all stored email AI interactions, newest first."""
    return await database.get_email_logs(prospect_id=prospect_id)


@app.get("/api/health")
async def health() -> dict:
    anthropic_ok = bool(settings.ANTHROPIC_API_KEY)
    db_ok = False
    try:
        await database.get_all_prospects()
        db_ok = True
    except Exception:
        pass
    all_ok = anthropic_ok and db_ok
    return {
        "anthropic": anthropic_ok,
        "db": db_ok,
        "status": "ok" if all_ok else "degraded",
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/{workflow_id}")
async def websocket_endpoint(websocket: WebSocket, workflow_id: str) -> None:
    await websocket.accept()
    active_connections[workflow_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.pop(workflow_id, None)


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.get("/")
async def root() -> FileResponse:
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prospect_to_scraped_stub(prospect: Prospect):
    """Build a minimal ScrapedData from a stored Prospect (no re-scrape needed)."""
    from models import ScrapedData
    analysis = prospect.analysis
    return ScrapedData(
        url=prospect.url,
        company_name=prospect.company_name,
        title=prospect.company_name,
        meta_description=prospect.detected_need,
        visible_text=prospect.detected_need,
        has_catalog=analysis.has_catalog if analysis else False,
        has_customer_service=analysis.has_customer_service if analysis else False,
        has_contact_form=analysis.has_contact_form if analysis else False,
    )
