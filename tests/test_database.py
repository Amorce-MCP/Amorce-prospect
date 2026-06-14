from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from database import (
    clear_all_prospects,
    delete_prospect,
    get_all_prospects,
    get_prospect,
    init_db,
    insert_prospect,
    update_prospect,
)


async def test_init_db_creates_table(tmp_db):
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prospects'"
        )
        row = await cursor.fetchone()
    assert row is not None


async def test_insert_and_get_prospect(tmp_db, sample_prospect):
    await init_db(tmp_db)
    await insert_prospect(sample_prospect, tmp_db)
    result = await get_prospect(sample_prospect.id, tmp_db)
    assert result is not None
    assert result.id == sample_prospect.id
    assert result.company_name == sample_prospect.company_name


async def test_update_prospect_status(tmp_db, sample_prospect):
    await init_db(tmp_db)
    await insert_prospect(sample_prospect, tmp_db)
    updated = await update_prospect(sample_prospect.id, tmp_db, status="scraped")
    assert updated is True
    result = await get_prospect(sample_prospect.id, tmp_db)
    assert result.status == "scraped"


async def test_delete_prospect(tmp_db, sample_prospect):
    await init_db(tmp_db)
    await insert_prospect(sample_prospect, tmp_db)
    deleted = await delete_prospect(sample_prospect.id, tmp_db)
    assert deleted is True
    result = await get_prospect(sample_prospect.id, tmp_db)
    assert result is None


async def test_get_all_prospects_returns_list(tmp_db, sample_prospect):
    await init_db(tmp_db)
    await insert_prospect(sample_prospect, tmp_db)
    prospects = await get_all_prospects(tmp_db)
    assert isinstance(prospects, list)
    assert len(prospects) == 1


async def test_get_nonexistent_prospect_returns_none(tmp_db):
    await init_db(tmp_db)
    result = await get_prospect("does-not-exist", tmp_db)
    assert result is None


async def test_clear_all_prospects(tmp_db, sample_prospect):
    await init_db(tmp_db)
    await insert_prospect(sample_prospect, tmp_db)
    count = await clear_all_prospects(tmp_db)
    assert count == 1
    remaining = await get_all_prospects(tmp_db)
    assert remaining == []


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

async def test_update_prospect_no_kwargs_returns_false(tmp_db, sample_prospect):
    await init_db(tmp_db)
    await insert_prospect(sample_prospect, tmp_db)
    result = await update_prospect(sample_prospect.id, tmp_db)
    assert result is False


async def test_insert_prospect_duplicate_id_raises(tmp_db, sample_prospect):
    await init_db(tmp_db)
    await insert_prospect(sample_prospect, tmp_db)
    with pytest.raises(Exception):
        await insert_prospect(sample_prospect, tmp_db)


async def test_update_prospect_db_error_returns_false(sample_prospect):
    with patch("database.aiosqlite.connect", side_effect=Exception("db error")):
        result = await update_prospect(sample_prospect.id, status="error")
    assert result is False


async def test_get_prospect_db_error_returns_none(sample_prospect):
    with patch("database.aiosqlite.connect", side_effect=Exception("db error")):
        result = await get_prospect(sample_prospect.id)
    assert result is None


async def test_get_all_prospects_db_error_returns_empty_list():
    with patch("database.aiosqlite.connect", side_effect=Exception("db error")):
        result = await get_all_prospects()
    assert result == []


async def test_delete_prospect_db_error_returns_false(sample_prospect):
    with patch("database.aiosqlite.connect", side_effect=Exception("db error")):
        result = await delete_prospect(sample_prospect.id)
    assert result is False


async def test_clear_all_prospects_db_error_returns_zero():
    with patch("database.aiosqlite.connect", side_effect=Exception("db error")):
        result = await clear_all_prospects()
    assert result == 0
