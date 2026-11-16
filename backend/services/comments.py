"""Viewer comments: fetch, sort, draft natural replies, send (A3).

Flow per channel (agent ``community``):

1. **fetch** new comments of recent posts through the official APIs
   (YouTube ``commentThreads.list``, Instagram ``/{media}/comments``). TikTok has
   no comment API for normal apps: the operator pastes comments by hand and gets
   a draft to copy.
2. **classify** each comment with fixed rules (spam, sensitive, criticism,
   question, praise). Rules, not the AI, decide what may be answered automatically.
3. **draft** a reply with the AI (Claude Haiku; mock in test mode). The style
   guide asks for short, specific, casual answers in the viewer's language,
   without stock phrases; a filter drops replies that still sound like a bot.
4. **policy**: spam is ignored; criticism, sensitive topics and TikTok go to the
   operator ("review"); everything else is "ready" and sent automatically when
   ``COMMENT_AUTO_REPLY`` is on.
5. **send** via ``comments.insert`` (YouTube, needs ``youtube.force-ssl``) or
   ``/{comment}/replies`` (Instagram). Without every publishing switch on
   (``PUBLISHING_MODE=live`` and ``AUTO_PUBLISH_ENABLED``) a send is only
   simulated and marked as test.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    ChannelAuthStatus,
    CommentKind,
    CommentStatus,
    Language,
    PlatformCode,
)
from models.channels import Channel, ChannelCredential
from models.comments import Comment
from models.production import Variant
from models.publishing import Post
from services import ai, audit, instagram, meta, platform, youtube

log = logging.getLogger(__name__)

YT_COMMENT_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
IG_LOGIN_COMMENT_SCOPE = "instagram_business_manage_comments"
IG_FB_COMMENT_SCOPE = "instagram_manage_comments"
MAX_REPLY_CHARS = 300


class CommentError(ValueError):
    """An action that is not allowed (German message)."""


# --- classification --------------------------------------------------------------------


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return text.replace("ß", "ss")


_URL = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|de|net|io|me|ly)\b)")
_SPAM = (
    "sub4sub", "sub 4 sub", "check my channel", "check out my channel", "schau auf meinem kanal",
    "abonniere mich", "folgt mir", "follow me", "follow back", "dm me", "schreib mir privat",
    "telegram", "whatsapp", "crypto", "bitcoin", "forex", "onlyfans", "giveaway winner",
    "promote", "promo code",
)  # fmt: skip
_SENSITIVE = (
    # insults and threats
    "idiot", "hurensohn", "wichser", "fotze", "bitch", "fuck you", "kys", "kill yourself",
    "umbringen", "spast", "behindert", "retard",
    # legal and rights
    "copyright", "urheberrecht", "anwalt", "abmahnung", "klage", "lawyer", "sue", "gestohlen",
    "stolen", "reupload", "dmca",
    # health, money, politics
    "medikament", "diagnose", "krebs", "schwanger", "depression", "suizid", "selbstmord",
    "medication", "cancer", "pregnant", "suicide", "politik", "politics", "wahl", "election",
    "afd", "trump", "scam", "betrug", "abzocke", "fraud",
)  # fmt: skip
_NEGATIVE = (
    "schlecht", "langweilig", "falsch", "stimmt nicht", "clickbait", "unsinn", "quatsch",
    "nervig", "müll", "muell", "schwach", "enttäuscht", "enttaeuscht", "boring", "wrong",
    "worst", "hate", "trash", "cringe", "fake", "misleading", "nonsense", "terrible", "bad video",
)  # fmt: skip
_PRAISE = (
    "geil", "super", "stark", "danke", "nice", "love", "great", "awesome", "top", "cool",
    "krass", "mega", "genial", "hilfreich", "helpful", "amazing", "perfect", "perfekt", "best",
    "🔥", "❤", "😍", "👍", "👏", "💯",
)  # fmt: skip
_QUESTION_START = (
    "wie ", "was ", "warum ", "wieso ", "weshalb ", "wo ", "wann ", "welche", "kann ", "gibt es",
    "hast du", "habt ihr", "how ", "what ", "why ", "where ", "when ", "which ", "can ", "is ",
    "are ", "do you", "does ",
)  # fmt: skip


def _has(text: str, words: tuple[str, ...]) -> str | None:
    for w in words:
        pattern = (
            rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])" if w.isascii() and w.isalnum() else None
        )
        if (pattern and re.search(pattern, text)) or (not pattern and w in text):
            return w
    return None


def classify(text: str) -> tuple[CommentKind, str | None]:
    """Kind of a comment and, for review cases, the reason (German)."""
    t = fold(text)
    if _URL.search(t) or _has(t, _SPAM):
        return CommentKind.SPAM, "Enthält Werbung oder Links."
    hit = _has(t, _SENSITIVE)
    if hit:
        return CommentKind.SENSITIVE, f"Heikles Thema („{hit}“), bitte selbst entscheiden."
    if len(text) > 600:
        return CommentKind.SENSITIVE, "Sehr langer Kommentar, bitte selbst lesen."
    if _has(t, _NEGATIVE):
        return CommentKind.CRITICISM, "Kritik: Antwort bitte kurz prüfen."
    if "?" in t or t.startswith(_QUESTION_START):
        return CommentKind.QUESTION, None
    if _has(t, _PRAISE) or not re.search(r"[a-z0-9äöü]", t):
        return CommentKind.PRAISE, None
    return CommentKind.OTHER, None


_DE_WORDS = {"der", "die", "das", "und", "ist", "nicht", "ich", "du", "wie", "was", "mit", "auch",
             "ein", "eine", "danke", "geil", "warum", "bitte", "kann", "hab", "mal"}  # fmt: skip
_EN_WORDS = {"the", "and", "is", "not", "you", "what", "how", "with", "this", "that", "thanks",
             "love", "why", "please", "can", "great", "i", "it", "my"}  # fmt: skip


def language_of(text: str, fallback: Language) -> Language:
    words = re.findall(r"[a-zäöüß]+", fold(text))
    de = sum(w in _DE_WORDS for w in words) + sum(c in text for c in "äöüß")
    en = sum(w in _EN_WORDS for w in words)
    if de > en:
        return Language.DE
    if en > de:
        return Language.EN
    return fallback


# --- drafting --------------------------------------------------------------------------

STYLE = (
    "You reply to comments under short videos on behalf of the channel. Write like the real "
    "person behind a small channel: casual, warm, specific. Rules:\n"
    "- Answer in the commenter's language. One or two short sentences, max 200 characters.\n"
    "- Refer to what they actually wrote. Answer questions concretely; if you do not know, "
    "say so honestly instead of guessing.\n"
    "- No stock phrases: never 'Great question', 'Thanks for your comment', 'Tolle Frage', "
    "'Danke für deinen Kommentar', 'Absolutely', 'I hope this helps'.\n"
    "- At most one emoji, often none. No hashtags, no links, no self-promotion.\n"
    "- Never mention AI, bots or automation. Do not make promises about future videos or "
    "dates unless the comment asks and you hedge it ('vielleicht', 'maybe').\n"
    "- Vary the wording; do not start like the recent replies listed.\n"
    "Return only the reply text."
)

_BOT_PHRASES = (
    "great question", "thanks for your comment", "thank you for your comment", "tolle frage",
    "gute frage", "danke für deinen kommentar", "danke fuer deinen kommentar", "as an ai",
    "als ki", "language model", "sprachmodell", "i hope this helps", "ich hoffe, das hilft",
    "feel free to", "don't hesitate",
)  # fmt: skip

_MOCK = {
    (Language.DE, CommentKind.QUESTION): (
        "Kommt drauf an, aber meistens reicht die einfache Variante völlig.",
        "Hab ich selbst getestet: klappt, wenn man es nicht übertreibt.",
    ),
    (Language.DE, CommentKind.PRAISE): (
        "Freut mich richtig, danke dir!",
        "Oh nice, das freut mich 🙌",
    ),
    (Language.DE, CommentKind.CRITICISM): ("Fair, nehm ich mit. Was hättest du anders gemacht?",),
    (Language.EN, CommentKind.QUESTION): (
        "Depends a bit, but the simple version works fine most of the time.",
        "Tried it myself: works as long as you don't overdo it.",
    ),
    (Language.EN, CommentKind.PRAISE): ("Really glad you liked it!", "Appreciate it 🙌"),
    (Language.EN, CommentKind.CRITICISM): (
        "Fair point, noted. What would you have done differently?",
    ),
}


def mock_reply(comment_text: str, kind: CommentKind, lang: Language) -> str:
    options = _MOCK.get((lang, kind)) or _MOCK[(lang, CommentKind.PRAISE)]
    idx = int(hashlib.sha256(comment_text.encode()).hexdigest()[:4], 16) % len(options)
    return options[idx]


def clean_reply(text: str) -> str | None:
    """Trim the model's answer; ``None`` if it still sounds like a bot or is empty."""
    t = " ".join(text.strip().strip('"„“”').split())
    t = re.sub(r"#\w+", "", t).strip()
    if not t or _URL.search(fold(t)):
        return None
    if any(p in fold(t) for p in _BOT_PHRASES):
        return None
    if len(t) > MAX_REPLY_CHARS:
        cut = t[:MAX_REPLY_CHARS]
        t = cut[: cut.rfind(" ")] if " " in cut else cut
    return t


def _context(session: Session, comment: Comment) -> tuple[str, str]:
    title = ""
    if comment.post_id is not None:
        post = session.get(Post, comment.post_id)
        if post is not None:
            v = session.get(Variant, post.variant_id)
            title = (v.title or "") if v else ""
    recent = session.scalars(
        select(Comment.reply_text)
        .where(Comment.channel_id == comment.channel_id, Comment.reply_text.is_not(None))
        .order_by(Comment.id.desc())
        .limit(5)
    ).all()
    return title, "\n".join(f"- {r}" for r in recent if r)


def draft(session: Session, settings: Settings, comment: Comment, channel: Channel) -> str | None:
    """Write a reply draft; ``None`` if the AI is blocked or only produced bot phrases."""
    lang = language_of(comment.text, channel.language)
    title, recent = _context(session, comment)
    lang_name = "German" if lang == Language.DE else "English"
    prompt = (
        f"Channel: {channel.name} (topic: {channel.content_project.name})\n"
        f"Video title: {title or '-'}\n"
        f"Comment by {comment.author or 'viewer'}: {comment.text}\n"
        f"Kind: {comment.kind.value}. Reply language: {lang_name}.\n"
        f"Recent replies of the channel (do not repeat their wording):\n{recent or '-'}"
    )
    text, kind = comment.text, comment.kind
    for attempt in range(2):
        try:
            result = ai.generate(
                session,
                settings,
                ai.AIRequest(
                    purpose="comment_reply",
                    tier="text",
                    messages=[ai.AIMessage("user", prompt)],
                    system=STYLE,
                    max_tokens=200,
                    mock=lambda _req: mock_reply(text, kind, lang),
                    content_project_id=channel.content_project_id,
                    meta={"comment_id": comment.id, "attempt": attempt},
                ),
            )
        except ai.AIError as exc:
            log.info("comment %s: no draft (%s)", comment.id, exc.code)
            return None
        reply = clean_reply(result.text)
        if reply:
            comment.reply_source = "mock" if result.provider == ai.MOCK else result.provider
            return reply
        prompt += "\nYour last answer sounded like a bot. Write it again, plainer and shorter."
    return None


# --- policy ----------------------------------------------------------------------------


def decide(settings: Settings, comment: Comment) -> None:
    """Status after classification and draft."""
    if comment.kind == CommentKind.SPAM:
        comment.status, comment.reply_text = CommentStatus.IGNORED, None
        return
    if comment.reply_text is None:
        comment.status = CommentStatus.NEW
        comment.review_reason = "Noch kein Entwurf (KI gerade nicht verfügbar)."
        return
    if comment.kind in (CommentKind.SENSITIVE, CommentKind.CRITICISM):
        comment.status = CommentStatus.REVIEW
    elif comment.platform == PlatformCode.TIKTOK:
        comment.status = CommentStatus.REVIEW
        comment.review_reason = (
            "TikTok hat keine Schnittstelle für Antworten: Text kopieren und in der App antworten."
        )
    elif not settings.comment_auto_reply:
        comment.status = CommentStatus.REVIEW
        comment.review_reason = "Automatische Antworten sind ausgeschaltet."
    else:
        comment.status = CommentStatus.READY
        comment.review_reason = None


def process(session: Session, settings: Settings, comment: Comment, channel: Channel) -> Comment:
    comment.kind, comment.review_reason = classify(comment.text)
    if comment.kind != CommentKind.SPAM:
        comment.reply_text = draft(session, settings, comment, channel)
    decide(settings, comment)
    return comment


# --- fetching --------------------------------------------------------------------------


@dataclass
class Fetched:
    external_id: str
    text: str
    author: str | None
    written_at: datetime | None
    like_count: int | None
    post_id: int | None


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None


_MOCK_COMMENTS = {
    Language.DE: (
        ("Lena", "Wie lange hält sich das eigentlich?"),
        ("Tom", "Richtig gut erklärt, danke!"),
        ("Kai", "Check my channel for more www.spam.example"),
        ("Mia", "Das stimmt so nicht, ist doch Clickbait"),
    ),
    Language.EN: (
        ("Sam", "How long does this actually last?"),
        ("Alex", "Really well explained, thanks!"),
        ("Bot", "sub4sub anyone?"),
        ("Jo", "This is wrong and kind of clickbait"),
    ),
}


def _mock_fetch(session: Session, channel: Channel, posts: list[Post]) -> list[Fetched]:
    out: list[Fetched] = []
    samples = _MOCK_COMMENTS[channel.language]
    for post in posts:
        for n, (author, text) in enumerate(samples):
            out.append(
                Fetched(
                    f"mock-{post.id}-{n}", text, f"{author} (Test)", post.published_at, 0, post.id
                )
            )
    return out


def _youtube_fetch(
    session: Session, settings: Settings, cred: ChannelCredential, posts: list[Post]
) -> list[Fetched]:
    token = youtube.access_token(session, settings, cred)
    own = cred.external_account_id
    out: list[Fetched] = []
    with youtube.http_client(30) as client:
        for post in posts:
            res = client.get(
                f"{youtube.API}/commentThreads",
                params={
                    "part": "snippet",
                    "videoId": post.external_post_id,
                    "maxResults": 50,
                    "order": "time",
                    "textFormat": "plainText",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if res.status_code >= 400:
                youtube._raise_for(res, "Kommentare")
            for item in youtube._json(res).get("items") or []:
                top = (item.get("snippet") or {}).get("topLevelComment") or {}
                sn = top.get("snippet") or {}
                author_id = (sn.get("authorChannelId") or {}).get("value")
                if own and author_id == own:
                    continue
                text = str(sn.get("textOriginal") or sn.get("textDisplay") or "").strip()
                if not text or not top.get("id"):
                    continue
                out.append(
                    Fetched(
                        str(top["id"]),
                        text,
                        sn.get("authorDisplayName"),
                        _ts(sn.get("publishedAt")),
                        sn.get("likeCount"),
                        post.id,
                    )
                )
    return out


def _ig(session: Session, settings: Settings, cred: ChannelCredential) -> tuple[Any, str]:
    """(module, token) for Instagram Login or Facebook Login connections."""
    if cred.provider == instagram.PROVIDER:
        return instagram, instagram.access_token(session, settings, cred)
    return meta, meta.page_token(settings, cred)


def _instagram_fetch(
    session: Session, settings: Settings, cred: ChannelCredential, posts: list[Post]
) -> list[Fetched]:
    mod, token = _ig(session, settings, cred)
    own = (cred.external_account_name or "").lstrip("@").casefold()
    out: list[Fetched] = []
    for post in posts:
        data = mod._get(
            f"{post.external_post_id}/comments",
            {"fields": "id,text,username,timestamp,like_count", "access_token": token},
            "Kommentare",
        )
        for c in data.get("data") or []:
            if own and str(c.get("username") or "").casefold() == own:
                continue
            text = str(c.get("text") or "").strip()
            if text and c.get("id"):
                out.append(
                    Fetched(
                        str(c["id"]),
                        text,
                        c.get("username"),
                        _ts(c.get("timestamp")),
                        c.get("like_count"),
                        post.id,
                    )
                )
    return out


def recent_posts(
    session: Session, channel: Channel, settings: Settings, now: datetime
) -> list[Post]:
    since = now - timedelta(days=settings.comment_lookback_days)
    return list(
        session.scalars(
            select(Post)
            .where(
                Post.channel_id == channel.id,
                Post.published_at >= since,
                Post.external_post_id.is_not(None),
            )
            .order_by(Post.published_at.desc())
            .limit(settings.comment_posts_per_run)
        )
    )


def fetch(
    session: Session, settings: Settings, channel: Channel, now: datetime | None = None
) -> list[Comment]:
    """Store new comments of the channel's recent posts; returns the new rows."""
    now = now or datetime.now(UTC)
    posts = recent_posts(session, channel, settings, now)
    mock_posts = [p for p in posts if p.is_mock]
    live_posts = [p for p in posts if not p.is_mock]
    found = _mock_fetch(session, channel, mock_posts) if settings.comment_mock_samples else []
    code = PlatformCode(channel.platform.code)
    if live_posts and code in (PlatformCode.YOUTUBE, PlatformCode.INSTAGRAM):
        cred = session.scalar(
            select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
        )
        if cred is not None:
            try:
                if code == PlatformCode.YOUTUBE:
                    found += _youtube_fetch(session, settings, cred, live_posts)
                else:
                    found += _instagram_fetch(session, settings, cred, live_posts)
            except httpx.HTTPError as exc:
                raise platform.TransientError(
                    f"Kommentare nicht erreichbar: {type(exc).__name__}"
                ) from exc
    if not found:
        return []
    known = set(
        session.scalars(
            select(Comment.external_id).where(
                Comment.channel_id == channel.id,
                Comment.external_id.in_([f.external_id for f in found]),
            )
        )
    )
    new: list[Comment] = []
    for f in found:
        if f.external_id in known:
            continue
        known.add(f.external_id)
        row = Comment(
            channel_id=channel.id,
            post_id=f.post_id,
            platform=code,
            external_id=f.external_id,
            author=(f.author or None) and str(f.author)[:200],
            text=f.text[:5000],
            written_at=f.written_at,
            like_count=f.like_count if isinstance(f.like_count, int) else None,
        )
        session.add(row)
        new.append(row)
    session.flush()
    return new


def add_manual(
    session: Session, settings: Settings, channel: Channel, text: str, author: str | None
) -> Comment:
    """A comment pasted by the operator (TikTok); drafted right away."""
    text = text.strip()
    if not text:
        raise CommentError("Der Kommentar ist leer.")
    digest = hashlib.sha256(f"{text}|{author}".encode()).hexdigest()[:16]
    ext = f"manual-{digest}"
    if session.scalar(
        select(Comment.id).where(Comment.channel_id == channel.id, Comment.external_id == ext)
    ):
        raise CommentError("Diesen Kommentar gibt es schon.")
    row = Comment(
        channel_id=channel.id,
        platform=PlatformCode(channel.platform.code),
        external_id=ext,
        author=(author or "").strip()[:200] or None,
        text=text[:5000],
        written_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    process(session, settings, row, channel)
    if row.status == CommentStatus.READY:  # pasted comments are answered by hand
        row.status = CommentStatus.REVIEW
        row.review_reason = "Selbst eingefügt: Antwort kopieren und in der App posten."
    session.commit()
    return row


# --- sending ---------------------------------------------------------------------------


def _send_live(session: Session, settings: Settings, comment: Comment, channel: Channel) -> str:
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    )
    if cred is None:
        raise platform.AuthExpiredError("Kanal ist nicht verbunden")
    text = comment.reply_text or ""
    if comment.platform == PlatformCode.YOUTUBE:
        if YT_COMMENT_SCOPE not in (cred.scopes or []):
            raise CommentError("Dem Kanal fehlt das Recht zum Antworten. Bitte neu verbinden.")
        token = youtube.access_token(session, settings, cred)
        with youtube.http_client(30) as client:
            res = client.post(
                f"{youtube.API}/comments",
                params={"part": "snippet"},
                json={"snippet": {"parentId": comment.external_id, "textOriginal": text}},
                headers={"Authorization": f"Bearer {token}"},
            )
        if res.status_code >= 400:
            youtube._raise_for(res, "Antwort")
        return str(youtube._json(res).get("id") or "")
    if comment.platform == PlatformCode.INSTAGRAM:
        if not {IG_LOGIN_COMMENT_SCOPE, IG_FB_COMMENT_SCOPE} & set(cred.scopes or []):
            raise CommentError("Dem Kanal fehlt das Recht zum Antworten. Bitte neu verbinden.")
        mod, token = _ig(session, settings, cred)
        data = mod._post(
            f"{comment.external_id}/replies", {"message": text, "access_token": token}, "Antwort"
        )
        return str(data.get("id") or "")
    raise CommentError("Auf dieser Plattform kann die Engine nicht selbst antworten.")


def send(
    session: Session, settings: Settings, comment: Comment, user_id: int | None = None
) -> Comment:
    """Post the reply. Simulated (and marked as test) unless every publishing switch is on."""
    if comment.status in (CommentStatus.SENT, CommentStatus.IGNORED):
        raise CommentError("Der Kommentar ist schon erledigt.")
    if not comment.reply_text or not comment.reply_text.strip():
        raise CommentError("Es gibt noch keinen Antworttext.")
    if comment.platform == PlatformCode.TIKTOK or comment.external_id.startswith("manual-"):
        raise CommentError("Hier antwortest du selbst in der App; danach „Erledigt“ klicken.")
    channel = session.get(Channel, comment.channel_id)
    assert channel is not None
    comment.attempts += 1
    simulated = (
        not settings.publishing_allowed
        or comment.external_id.startswith("mock-")
        or channel.auth_status != ChannelAuthStatus.AUTHORIZED
    )
    try:
        if simulated:
            comment.reply_external_id, comment.reply_is_mock = f"mock-reply-{comment.id}", True
        else:
            comment.reply_external_id = _send_live(session, settings, comment, channel) or None
            comment.reply_is_mock = False
    except (platform.PlatformError, CommentError, httpx.HTTPError) as exc:
        comment.status, comment.error = CommentStatus.FAILED, str(exc)[:500]
        session.commit()
        raise CommentError(str(exc)) from exc
    comment.status, comment.error = CommentStatus.SENT, None
    comment.replied_at = datetime.now(UTC)
    comment.decided_by_user_id = user_id or comment.decided_by_user_id
    audit.record(
        session,
        "comment.reply",
        user_id=user_id,
        agent=None if user_id else "community",
        entity_type="comments",
        entity_id=comment.id,
        after={"mock": comment.reply_is_mock, "platform": comment.platform.value},
    )
    session.commit()
    return comment


def mark_done(session: Session, comment: Comment, user_id: int) -> Comment:
    """The operator answered by hand (TikTok, pasted comments)."""
    if comment.status in (CommentStatus.SENT, CommentStatus.IGNORED):
        raise CommentError("Der Kommentar ist schon erledigt.")
    comment.status, comment.replied_at = CommentStatus.SENT, datetime.now(UTC)
    comment.reply_is_mock, comment.decided_by_user_id = False, user_id
    session.commit()
    return comment


def ignore(session: Session, comment: Comment, user_id: int) -> Comment:
    if comment.status == CommentStatus.SENT:
        raise CommentError("Auf diesen Kommentar wurde schon geantwortet.")
    comment.status, comment.decided_by_user_id = CommentStatus.IGNORED, user_id
    session.commit()
    return comment


def redraft(session: Session, settings: Settings, comment: Comment) -> Comment:
    if comment.status in (CommentStatus.SENT, CommentStatus.IGNORED):
        raise CommentError("Der Kommentar ist schon erledigt.")
    channel = session.get(Channel, comment.channel_id)
    assert channel is not None
    previous = comment.reply_text
    reply = draft(session, settings, comment, channel)
    if reply and reply == previous and comment.reply_source == "mock":
        # the mock is deterministic: pick the other variant so the button visibly works
        lang = language_of(comment.text, channel.language)
        options = _MOCK.get((lang, comment.kind)) or ()
        reply = next((o for o in options if o != previous), reply)
    if reply is None:
        raise CommentError("Gerade kein neuer Entwurf möglich (KI nicht verfügbar).")
    comment.reply_text = reply
    if comment.status in (CommentStatus.NEW, CommentStatus.FAILED):
        comment.status = CommentStatus.REVIEW
    session.commit()
    return comment


# --- one run per channel -----------------------------------------------------------------


@dataclass
class RunResult:
    fetched: int = 0
    drafted: int = 0
    sent: int = 0
    review: int = 0
    ignored: int = 0
    errors: list[str] | None = None


def run_channel(
    session: Session, settings: Settings, channel: Channel, now: datetime | None = None
) -> RunResult:
    result = RunResult(errors=[])
    assert result.errors is not None
    try:
        result.fetched = len(fetch(session, settings, channel, now))
    except platform.PlatformError as exc:
        result.errors.append(str(exc))
    session.commit()
    todo = session.scalars(
        select(Comment)
        .where(Comment.channel_id == channel.id, Comment.status == CommentStatus.NEW)
        .order_by(Comment.id)
        .limit(settings.comment_drafts_per_run)
    ).all()
    for c in todo:
        process(session, settings, c, channel)
        result.drafted += c.reply_text is not None
        result.ignored += c.status == CommentStatus.IGNORED
        result.review += c.status == CommentStatus.REVIEW
    session.commit()
    ready = session.scalars(
        select(Comment)
        .where(Comment.channel_id == channel.id, Comment.status == CommentStatus.READY)
        .order_by(Comment.id)
        .limit(settings.comment_replies_per_run)
    ).all()
    for c in ready:
        try:
            send(session, settings, c)
            result.sent += 1
        except CommentError as exc:
            result.errors.append(str(exc))
    return result


def channels_to_watch(session: Session, settings: Settings) -> list[Channel]:
    """Connected channels, plus every channel while test comments are on."""
    q = select(Channel).where(Channel.is_paused.is_(False))
    if not settings.comment_mock_samples:
        q = q.where(
            Channel.auth_status.in_(
                [ChannelAuthStatus.AUTHORIZED, ChannelAuthStatus.CONNECTED_RESTRICTED]
            )
        )
    return list(session.scalars(q.order_by(Channel.id)))
