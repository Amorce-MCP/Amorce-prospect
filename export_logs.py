"""Export email_logs to a readable Markdown file."""
import asyncio
import json
from datetime import datetime
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent / "amorce.db"
OUT_PATH = Path(__file__).parent / "llm_history.md"


def _fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return iso


async def main() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Prospect names
        cur = await db.execute("SELECT id, company_name, url FROM prospects")
        prospects = {row["id"]: dict(row) for row in await cur.fetchall()}

        # All logs in chronological order
        cur = await db.execute(
            "SELECT * FROM email_logs ORDER BY prospect_id, created_at ASC"
        )
        logs = [dict(row) for row in await cur.fetchall()]

    if not logs:
        print("Aucun log trouvé dans email_logs.")
        return

    # Group by prospect
    by_prospect: dict[str, list[dict]] = {}
    for log in logs:
        pid = log["prospect_id"]
        by_prospect.setdefault(pid, []).append(log)

    lines: list[str] = [
        "# Historique des échanges LLM — Amorce Prospector\n",
        f"_Exporté le {datetime.now().strftime('%d/%m/%Y %H:%M')}_\n",
        "---\n",
    ]

    for pid, entries in by_prospect.items():
        p = prospects.get(pid, {})
        company = p.get("company_name", pid)
        url = p.get("url", "")
        lines.append(f"\n## {company}")
        if url:
            lines.append(f"_{url}_\n")

        for i, log in enumerate(entries, 1):
            log_type = log["type"]
            date_str = _fmt_dt(log["created_at"])
            data = json.loads(log["data_json"]) if log["data_json"] else {}

            lines.append(f"\n### Tour {i} — `{log_type}` — {date_str}\n")

            # ── Business data ───────────────────────────────────────────────
            if log_type == "questions":
                qs = data.get("questions", [])
                if qs:
                    lines.append("**Questions générées :**\n")
                    for q in qs:
                        lines.append(f"- {q}")
                    lines.append("")

            elif log_type == "qa":
                qs = data.get("questions", [])
                ans = data.get("answers", [])
                if qs:
                    lines.append("**Q&A du commercial :**\n")
                    for q, a in zip(qs, ans):
                        lines.append(f"**Q :** {q}  ")
                        lines.append(f"**R :** {a or '_(vide)_'}  ")
                    lines.append("")

            elif log_type == "generate":
                if data.get("subject_out"):
                    lines.append("**Email généré :**\n")
                    lines.append(f"**Objet :** {data['subject_out']}  ")
                    body = (data.get("body_out") or "").replace("\n", "  \n")
                    lines.append(f"\n{body}\n")

            elif log_type == "polish":
                if data.get("instruction"):
                    lines.append(f"**Instruction :** {data['instruction']}\n")
                if data.get("subject_before"):
                    lines.append(f"**Avant — Objet :** {data['subject_before']}  ")
                    before = (data.get("body_before") or "").replace("\n", "  \n")
                    lines.append(f"\n{before}\n")
                if data.get("subject_after"):
                    lines.append(f"**Après — Objet :** {data['subject_after']}  ")
                    after = (data.get("body_after") or "").replace("\n", "  \n")
                    lines.append(f"\n{after}\n")

            # ── LLM trace ───────────────────────────────────────────────────
            if log.get("model"):
                tokens_in  = log.get("input_tokens")  or "—"
                tokens_out = log.get("output_tokens") or "—"
                lines.append(
                    f"_Modèle : `{log['model']}` · tokens in : {tokens_in} · out : {tokens_out}_\n"
                )

            if log.get("system_prompt"):
                lines.append("<details><summary>Prompt système</summary>\n")
                lines.append(f"\n```\n{log['system_prompt']}\n```\n")
                lines.append("</details>\n")

            if log.get("user_message"):
                lines.append("<details><summary>Message envoyé à Claude</summary>\n")
                lines.append(f"\n```\n{log['user_message']}\n```\n")
                lines.append("</details>\n")

            if log.get("raw_response"):
                lines.append("<details><summary>Réponse brute de Claude</summary>\n")
                lines.append(f"\n```json\n{log['raw_response']}\n```\n")
                lines.append("</details>\n")

            lines.append("---")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Exporté : {OUT_PATH}  ({len(logs)} entrées)")


asyncio.run(main())
