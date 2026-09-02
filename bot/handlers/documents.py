"""Phase 4 — document-driven learning.

Upload a German engineering PDF -> extract text (pypdf) -> Gemini pulls key
terminology + a summary -> stored as VocabItem(source=document) + Document row.
Those terms flow into /practice automatically.

Commands:
  (send a PDF)  -> analyse and store terminology
  /docs         -> list uploaded documents
  /learn [id]   -> generate a lesson from a document (most recent if no id)
  /docfocus on|off -> bias conversation toward the latest document's topic
"""
from __future__ import annotations

import io
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth
from db.models import VocabSource
from db.repo import (
    add_vocab_items,
    create_document,
    get_document,
    get_user_by_telegram_id,
    list_documents,
    recent_document,
    set_document_term_count,
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route
from llm.structured import generate_json

logger = logging.getLogger(__name__)

MAX_FILE_MB = 20
CHUNK_CHARS = 12000
MAX_CHUNKS = 6  # cap LLM calls to respect the free tier
SUMMARY_CHARS = 8000

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (Gemini quota reached.)"
_IMPORTANCE = {"high": 0, "medium": 1, "low": 2}


def _extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:  # a broken page shouldn't kill the whole doc
            logger.warning("Page extract failed: %s", exc)
    return "\n".join(parts).strip()


def _chunks(text: str, size: int, max_chunks: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)][:max_chunks]


@require_auth
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    doc = message.document
    if doc is None:
        return

    filename = doc.file_name or "document.pdf"
    is_pdf = (doc.mime_type == "application/pdf") or filename.lower().endswith(".pdf")
    if not is_pdf:
        await message.reply_text(
            "Ich kann momentan nur PDFs analysieren. (Only PDF files for now.)"
        )
        return
    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        await message.reply_text(
            f"Die Datei ist zu groß (max {MAX_FILE_MB} MB)."
        )
        return

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return

    await message.reply_text(f"📄 Analysiere *{filename}*… einen Moment.")
    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        text = _extract_pdf_text(data)
    except Exception as exc:
        logger.exception("PDF download/extract failed")
        await message.reply_text(
            "Konnte die PDF nicht lesen. Ist sie beschädigt? (Couldn't read the PDF.)"
        )
        return

    if len(text) < 40:
        await message.reply_text(
            "Diese PDF enthält keinen extrahierbaren Text — wahrscheinlich ein "
            "Scan. OCR kann ich (noch) nicht. Schick mir eine Text-PDF. 🙏\n"
            "(No extractable text — looks scanned; OCR is out of scope.)"
        )
        return

    # --- extract terms chunk by chunk ---
    collected: dict[str, dict] = {}
    try:
        for chunk in _chunks(text, CHUNK_CHARS, MAX_CHUNKS):
            result, _ = await generate_json(
                Task.analyze, chunk, system=prompts.DOC_EXTRACT_TERMS
            )
            terms = (result or {}).get("terms", []) if isinstance(result, dict) else []
            for t in terms:
                term = (t.get("term") or "").strip()
                if term and term not in collected:
                    collected[term] = t

        summary = await route(
            Task.analyze, text[:SUMMARY_CHARS], system=prompts.DOC_SUMMARY
        )
    except QuotaExceeded:
        await message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await message.reply_text(
            "Die Analyse hat nicht geklappt. Versuch es später nochmal."
        )
        return

    if not collected:
        await message.reply_text(
            "Ich habe keine nützlichen Fachbegriffe gefunden. 🤔"
        )
        return

    ordered = sorted(
        collected.values(),
        key=lambda t: _IMPORTANCE.get((t.get("importance") or "low").lower(), 2),
    )

    document_id = create_document(user.id, filename, summary.strip())
    inserted = add_vocab_items(
        user.id,
        [
            {
                "term": t["term"],
                "translation": t.get("translation"),
                "context_sentence": t.get("context_sentence"),
            }
            for t in ordered
        ],
        source=VocabSource.document,
        document_id=document_id,
    )
    set_document_term_count(document_id, inserted)

    top = ordered[:10]
    lines = [f"✅ *{filename}* analysiert!", "", summary.strip(), "", "🔑 Top-Begriffe:"]
    for t in top:
        tr = f" — {t['translation']}" if t.get("translation") else ""
        lines.append(f"  • {t['term']}{tr}")
    lines.append(
        f"\n{inserted} neue Vokabeln gespeichert (Doc #{document_id}). "
        f"Nutze /learn {document_id} für eine Lektion, oder /practice zum Üben."
    )
    await message.reply_text("\n".join(lines))


@require_auth
async def docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    documents = list_documents(user.id)
    if not documents:
        await update.effective_message.reply_text(
            "Noch keine Dokumente. Schick mir eine deutsche Technik-PDF! 📄"
        )
        return
    lines = ["📚 *Deine Dokumente:*"]
    for d in documents:
        lines.append(f"  • #{d['id']} — {d['filename']} ({d['terms']} Begriffe)")
    lines.append("\n/learn <id> für eine Lektion.")
    await update.effective_message.reply_text("\n".join(lines))


@require_auth
async def learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return

    document = None
    if context.args:
        try:
            document = get_document(user.id, int(context.args[0]))
        except ValueError:
            document = None
        if document is None:
            await update.effective_message.reply_text(
                "Kein Dokument mit dieser ID. /docs zeigt deine Dokumente."
            )
            return
    else:
        recent = recent_document(user.id)
        if recent is None:
            await update.effective_message.reply_text(
                "Noch keine Dokumente. Schick mir zuerst eine PDF. 📄"
            )
            return
        document = get_document(user.id, recent["id"])

    from bot.handlers.conversation import _user_level

    level = _user_level(user.cefr_estimate)
    terms = ", ".join(t["term"] for t in document["terms"][:25]) or "(keine)"

    await update.effective_message.reply_text(
        f"🎓 Ich baue eine Lektion aus *{document['filename']}*… einen Moment."
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, action="typing"
    )
    prompt = "Generate the lesson now."
    system = prompts.LEARN_LESSON.format(
        level=level, summary=document.get("summary") or "(no summary)", terms=terms
    )
    try:
        lesson = await route(Task.generate, prompt, system=system)
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await update.effective_message.reply_text(
            "Die Lektion hat nicht geklappt. Versuch es später."
        )
        return

    # Telegram messages cap at 4096 chars; split if needed.
    for i in range(0, len(lesson), 4000):
        await update.effective_message.reply_text(lesson[i : i + 4000])


@require_auth
async def docfocus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔀 option: bias conversation toward the latest document's topic."""
    arg = (context.args[0].lower() if context.args else "").strip()
    if arg in ("on", "an", "ein"):
        context.user_data["docfocus"] = True
        await update.effective_message.reply_text(
            "Dokument-Fokus AN — ich lenke Gespräche zum neuesten Dokument. "
            "(/docfocus off zum Ausschalten.)"
        )
    elif arg in ("off", "aus"):
        context.user_data["docfocus"] = False
        await update.effective_message.reply_text(
            "Dokument-Fokus AUS. (Off.)"
        )
    else:
        state = "AN" if context.user_data.get("docfocus") else "AUS"
        await update.effective_message.reply_text(
            f"Dokument-Fokus ist {state}. Nutze /docfocus on oder /docfocus off."
        )
