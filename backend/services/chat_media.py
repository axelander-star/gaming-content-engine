"""Chat attachments and spoken answers (Ausbau A4).

Attachments: images (PNG, JPEG) and PDFs up to ``MAX_DOCUMENT_BYTES``. PDFs are
read locally with pypdf (free); the AI only gets their text. Images go to Claude
as image blocks, downscaled first so one image costs at most about 1,600 tokens.
A scanned PDF without a text layer is not sent (it would be expensive); the
answer asks for the pages as pictures instead.

Spoken answers: the voice the operator chose for videos (Einstellungen → Betrieb,
``tts_provider``). With ``piper`` the server speaks locally and free; with the
silent ``mock`` voice the browser's own speech synthesis reads the answer.
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import Language
from models.access import User
from models.assistant import ChatAttachment, ChatMessage
from services import comments, media, storage, voice
from services.controls import get_operations

IMAGE_TYPES = {"image/png", "image/jpeg"}
PDF = "application/pdf"
#: Claude scales larger images down to this edge anyway; smaller means fewer tokens.
MAX_IMAGE_EDGE = 1568
MAX_PDF_PAGES = 60
MAX_PDF_CHARS = 40_000
#: PDF text sent with one message in total (the prompt limit is AI_MAX_INPUT_CHARS).
MAX_PROMPT_PDF_CHARS = 30_000
MAX_SPOKEN_CHARS = 1500


class ChatMediaError(ValueError):
    pass


def _image_size(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            return img.size
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ChatMediaError("Das Bild lässt sich nicht öffnen.") from exc


def pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ChatMediaError("Die PDF ist passwortgeschützt.")
        pages = len(reader.pages)
        parts: list[str] = []
        size = 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(text)
                size += len(text)
            if size >= MAX_PDF_CHARS:
                break
    except PdfReadError as exc:
        raise ChatMediaError("Die PDF lässt sich nicht lesen.") from exc
    text = re.sub(r"[ \t]+", " ", "\n\n".join(parts)).strip()
    return text[:MAX_PDF_CHARS], pages


def save(
    session: Session,
    settings: Settings,
    user: User,
    filename: str,
    content_type: str,
    data: bytes,
) -> ChatAttachment:
    content_type = content_type.split(";")[0].strip().lower()
    if content_type == "image/jpg":
        content_type = "image/jpeg"
    if content_type not in IMAGE_TYPES and content_type != PDF:
        raise ChatMediaError("Erlaubt sind Bilder (PNG, JPEG) und PDFs.")
    try:
        stored = storage.store_document(settings, data, content_type, "chat")
    except storage.StorageError as exc:
        raise ChatMediaError("Die Datei ist leer, zu groß oder passt nicht zu ihrem Typ.") from exc
    att = ChatAttachment(
        user_id=user.id,
        filename=(Path(filename).name or "datei")[:255],
        content_type=content_type,
        size_bytes=stored.size,
        uri=stored.uri,
    )
    if content_type == PDF:
        att.extracted_text, att.pages = pdf_text(data)
    else:
        att.width, att.height = _image_size(data)
    session.add(att)
    session.flush()
    return att


def claim(session: Session, settings: Settings, user: User, ids: list[int]) -> list[ChatAttachment]:
    """The user's own, not yet sent attachments with these ids (in the given order)."""
    if not ids:
        return []
    if len(ids) > settings.chat_max_attachments:
        raise ChatMediaError(f"Höchstens {settings.chat_max_attachments} Dateien je Nachricht.")
    rows = {
        a.id: a
        for a in session.scalars(
            select(ChatAttachment).where(
                ChatAttachment.id.in_(ids),
                ChatAttachment.user_id == user.id,
                ChatAttachment.message_id.is_(None),
            )
        )
    }
    missing = [i for i in ids if i not in rows]
    if missing:
        raise ChatMediaError("Eine Datei wurde nicht gefunden oder ist schon gesendet.")
    return [rows[i] for i in dict.fromkeys(ids)]


def for_messages(session: Session, message_ids: list[int]) -> dict[int, list[ChatAttachment]]:
    out: dict[int, list[ChatAttachment]] = {}
    if not message_ids:
        return out
    for a in session.scalars(
        select(ChatAttachment)
        .where(ChatAttachment.message_id.in_(message_ids))
        .order_by(ChatAttachment.id)
    ):
        assert a.message_id is not None
        out.setdefault(a.message_id, []).append(a)
    return out


def describe(att: ChatAttachment) -> str:
    if att.content_type == PDF:
        pages = att.pages or 0
        return f"PDF „{att.filename}“ ({pages} {'Seite' if pages == 1 else 'Seiten'})"
    return f"Bild „{att.filename}“ ({att.width} × {att.height})"


def _image_block(settings: Settings, att: ChatAttachment) -> dict[str, Any]:
    path = storage.resolve(settings, att.uri)
    with Image.open(path) as src:
        img = src.convert("RGB")
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(buf.getvalue()).decode(),
        },
    }


def content_blocks(
    settings: Settings, text: str, attachments: list[ChatAttachment]
) -> str | list[dict[str, Any]]:
    """The user turn for Claude: images first, then the PDFs' text, then the message."""
    if not attachments:
        return text
    blocks: list[dict[str, Any]] = []
    notes: list[str] = []
    pdfs = sum(1 for a in attachments if a.content_type == PDF and a.extracted_text)
    per_pdf = MAX_PROMPT_PDF_CHARS // max(1, pdfs)
    for att in attachments:
        if att.content_type in IMAGE_TYPES:
            blocks.append(_image_block(settings, att))
            notes.append(f"Angehängt: {describe(att)}.")
        elif att.extracted_text:
            body = att.extracted_text[:per_pdf]
            cut = " (gekürzt)" if len(att.extracted_text) > per_pdf else ""
            notes.append(f"Inhalt der {describe(att)}{cut}:\n<<<\n{body}\n>>>")
        else:
            notes.append(
                f"Angehängt: {describe(att)}, aber ohne lesbaren Text (vermutlich ein Scan). "
                "Bitte den Nutzer, die wichtigen Seiten als Bild zu schicken."
            )
    message = text or "Was siehst du in der Datei? Fass es kurz zusammen."
    blocks.append({"type": "text", "text": "\n\n".join([*notes, message])})
    return blocks


def mock_summary(attachments: list[ChatAttachment]) -> str:
    lines = []
    for att in attachments:
        if att.content_type == PDF:
            text = (att.extracted_text or "").strip()
            if text:
                start = " ".join(text.split())[:160]
                lines.append(
                    f"{describe(att)} gelesen, {len(text)} Zeichen Text. Anfang: „{start} …“"
                )
            else:
                lines.append(
                    f"{describe(att)} hat keinen lesbaren Text (Scan?). "
                    "Schick mir die Seiten am besten als Bild."
                )
        else:
            lines.append(
                f"{describe(att)} erhalten. Bilder kann ich mir ansehen, wenn Claude als "
                "KI eingestellt ist."
            )
    return "\n".join(lines)


# --- spoken answers -------------------------------------------------------------------


@dataclass(frozen=True)
class Speech:
    path: Path | None
    provider: str


def spoken_text(text: str) -> str:
    """Markdown and links out, so the voice reads like a person would."""
    t = re.sub(r"https?://\S+", "Link", text)
    t = re.sub(r"[*_`#>|]+", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\.\s*\.", ".", t)
    t = " ".join(t.split())
    if len(t) > MAX_SPOKEN_CHARS:
        cut = t[:MAX_SPOKEN_CHARS]
        t = cut[: cut.rfind(". ") + 1] if ". " in cut else cut
    return t


def speak(session: Session, settings: Settings, message: ChatMessage) -> Speech:
    """Audio (AAC in .m4a) of an assistant answer, cached; ``path`` None = browser speaks."""
    name = get_operations(session).tts_provider
    provider = voice.get_provider(name, settings)
    if provider is None or provider.name == voice.MOCK:
        return Speech(None, voice.MOCK)
    if not provider.commercial_use_cleared:
        return Speech(None, voice.MOCK)
    text = spoken_text(message.text)
    if not text:
        raise ChatMediaError("Nichts zum Vorlesen.")
    folder = Path(settings.media_root) / "chat-speech"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{message.id}-{provider.name}.m4a"
    if out.is_file():
        return Speech(out, provider.name)
    language = comments.language_of(text, Language.DE)
    wav = folder / f"{message.id}-{provider.name}.wav"
    try:
        provider.synthesize(text, language, provider.voices[language], wav)
        media.run(
            [settings.ffmpeg_bin, "-v", "error", "-y", "-i", str(wav),
             "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)],
            timeout=120,
        )  # fmt: skip
    except (voice.VoiceError, media.MediaError) as exc:
        out.unlink(missing_ok=True)
        raise ChatMediaError(f"Vorlesen ging nicht: {exc}") from exc
    finally:
        wav.unlink(missing_ok=True)
    return Speech(out, provider.name)
