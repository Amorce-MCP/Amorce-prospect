import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import aiosqlite

from config import settings
from models import Prospect, SiteAnalysis

logger = logging.getLogger(__name__)

_CREATE_LOGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS email_logs (
    id            TEXT PRIMARY KEY,
    prospect_id   TEXT NOT NULL,
    type          TEXT NOT NULL,
    data_json     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    system_prompt TEXT,
    user_message  TEXT,
    raw_response  TEXT,
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER
)
"""

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS prospects (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    email           TEXT,
    score           INTEGER DEFAULT 0,
    detected_need   TEXT DEFAULT '',
    suggested_mission TEXT DEFAULT '',
    has_chatbot     INTEGER,
    email_subject   TEXT,
    email_body      TEXT,
    linkedin_message TEXT,
    status          TEXT DEFAULT 'pending',
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    analysis_json   TEXT
)
"""


def _row_to_prospect(row: aiosqlite.Row) -> Prospect:
    analysis_raw = row["analysis_json"]
    analysis = SiteAnalysis.model_validate_json(analysis_raw) if analysis_raw else None
    raw_chatbot = row["has_chatbot"]
    has_chatbot: bool | None = None if raw_chatbot is None else bool(raw_chatbot)
    return Prospect(
        id=row["id"],
        url=row["url"],
        company_name=row["company_name"],
        email=row["email"],
        score=row["score"],
        detected_need=row["detected_need"] or "",
        suggested_mission=row["suggested_mission"] or "",
        has_chatbot=has_chatbot,
        email_subject=row["email_subject"],
        email_body=row["email_body"],
        linkedin_message=row["linkedin_message"] if "linkedin_message" in row.keys() else None,
        status=row["status"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        analysis=analysis,
    )


async def init_db(db_path: str | None = None) -> None:
    """Create all tables and run pending migrations."""
    path = db_path or settings.DB_PATH
    async with aiosqlite.connect(path) as db:
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(_CREATE_LOGS_TABLE_SQL)
        for column in ("analysis_json TEXT", "has_chatbot INTEGER", "linkedin_message TEXT"):
            try:
                await db.execute(f"ALTER TABLE prospects ADD COLUMN {column}")
            except Exception:
                pass  # column already exists
        for column in (
            "system_prompt TEXT",
            "user_message TEXT",
            "raw_response TEXT",
            "model TEXT",
            "input_tokens INTEGER",
            "output_tokens INTEGER",
        ):
            try:
                await db.execute(f"ALTER TABLE email_logs ADD COLUMN {column}")
            except Exception:
                pass  # column already exists
        await db.commit()


async def insert_prospect(prospect: Prospect, db_path: str | None = None) -> str:
    """Insert a prospect record and return its id."""
    path = db_path or settings.DB_PATH
    try:
        data = prospect.model_dump(exclude={"analysis"})
        data["analysis_json"] = (
            prospect.analysis.model_dump_json() if prospect.analysis else None
        )
        data["has_chatbot"] = (
            None if prospect.has_chatbot is None else int(prospect.has_chatbot)
        )
        async with aiosqlite.connect(path) as db:
            await db.execute(
                """INSERT INTO prospects (
                    id, url, company_name, email, score, detected_need,
                    suggested_mission, has_chatbot, email_subject, email_body,
                    linkedin_message, status, error_message, created_at, analysis_json
                ) VALUES (
                    :id, :url, :company_name, :email, :score, :detected_need,
                    :suggested_mission, :has_chatbot, :email_subject, :email_body,
                    :linkedin_message, :status, :error_message, :created_at, :analysis_json
                )""",
                data,
            )
            await db.commit()
        return prospect.id
    except Exception as e:
        logger.error("Failed to insert prospect %s: %s", prospect.id, e)
        raise


async def update_prospect(
    prospect_id: str, db_path: str | None = None, **kwargs: Any
) -> bool:
    """Update arbitrary fields on a prospect. Returns True if a row was updated."""
    if not kwargs:
        return False
    path = db_path or settings.DB_PATH
    set_clause = ", ".join(f"{k} = :{k}" for k in kwargs)
    params: dict[str, Any] = {**kwargs, "id": prospect_id}
    try:
        async with aiosqlite.connect(path) as db:
            cursor = await db.execute(
                f"UPDATE prospects SET {set_clause} WHERE id = :id", params
            )
            await db.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("Failed to update prospect %s: %s", prospect_id, e)
        return False


async def get_prospect(
    prospect_id: str, db_path: str | None = None
) -> Prospect | None:
    """Return a prospect by id, or None if not found."""
    path = db_path or settings.DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM prospects WHERE id = ?", (prospect_id,)
            )
            row = await cursor.fetchone()
            return _row_to_prospect(row) if row else None
    except Exception as e:
        logger.error("Failed to get prospect %s: %s", prospect_id, e)
        return None


async def get_all_prospects(db_path: str | None = None) -> list[Prospect]:
    """Return all prospects ordered by creation date descending."""
    path = db_path or settings.DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM prospects ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            return [_row_to_prospect(row) for row in rows]
    except Exception as e:
        logger.error("Failed to get all prospects: %s", e)
        return []


async def delete_prospect(
    prospect_id: str, db_path: str | None = None
) -> bool:
    """Delete a prospect. Returns True if a row was deleted."""
    path = db_path or settings.DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cursor = await db.execute(
                "DELETE FROM prospects WHERE id = ?", (prospect_id,)
            )
            await db.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("Failed to delete prospect %s: %s", prospect_id, e)
        return False


async def clear_all_prospects(db_path: str | None = None) -> int:
    """Delete all prospects and return the count deleted."""
    path = db_path or settings.DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cursor = await db.execute("DELETE FROM prospects")
            await db.commit()
            return cursor.rowcount
    except Exception as e:
        logger.error("Failed to clear all prospects: %s", e)
        return 0


async def log_email_interaction(
    prospect_id: str,
    log_type: str,
    data: dict[str, Any],
    db_path: str | None = None,
    llm_trace: dict[str, Any] | None = None,
) -> None:
    """Store a complete email AI interaction for future prompt analysis and improvement.

    log_type: 'questions' | 'generate' | 'polish'
    data keys for 'questions': questions
    data keys for 'generate':  questions, answers, subject_out, body_out, mission
    data keys for 'polish':    subject_before, body_before, instruction, subject_after, body_after
    llm_trace keys: system_prompt, user_message, raw_response, model, input_tokens, output_tokens
    Never raises.
    """
    path = db_path or settings.DB_PATH
    entry_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    trace = llm_trace or {}
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "INSERT INTO email_logs "
                "(id, prospect_id, type, data_json, created_at, "
                "system_prompt, user_message, raw_response, model, input_tokens, output_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    prospect_id,
                    log_type,
                    json.dumps(data, ensure_ascii=False),
                    created_at,
                    trace.get("system_prompt"),
                    trace.get("user_message"),
                    trace.get("raw_response"),
                    trace.get("model"),
                    trace.get("input_tokens"),
                    trace.get("output_tokens"),
                ),
            )
            await db.commit()
    except Exception as e:
        logger.error("Failed to log email interaction for %s: %s", prospect_id, e)


async def get_email_logs(
    prospect_id: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return email interaction logs, optionally filtered by prospect.

    Results ordered newest first. Never raises.
    """
    path = db_path or settings.DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            if prospect_id:
                cursor = await db.execute(
                    "SELECT * FROM email_logs WHERE prospect_id = ? ORDER BY created_at DESC",
                    (prospect_id,),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM email_logs ORDER BY created_at DESC"
                )
            rows = await cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "prospect_id": row["prospect_id"],
                    "type": row["type"],
                    "data": json.loads(row["data_json"]),
                    "created_at": row["created_at"],
                    "system_prompt": row["system_prompt"],
                    "user_message": row["user_message"],
                    "raw_response": row["raw_response"],
                    "model": row["model"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                }
                for row in rows
            ]
    except Exception as e:
        logger.error("Failed to get email logs: %s", e)
        return []
