"""Channel assistant: coverage per topic area and "create channel" tasks."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from core.enums import (
    ChannelSetupStatus,
    ContentProjectStatus,
    Language,
    MailAliasStatus,
    PlatformCode,
)
from models.channel_setup import ChannelSetupTask
from models.channels import Channel
from models.projects import ContentProject
from services import channel_setup, mail_alias, storage

router = APIRouter(
    prefix="/channel-setup", tags=["channel-setup"], dependencies=[Depends(csrf_protect)]
)


class SlotOut(BaseModel):
    platform: PlatformCode
    language: Language
    state: str
    channel_id: int | None
    channel_name: str | None
    task_id: int | None


class CoverageOut(BaseModel):
    project_id: int
    project: str
    project_status: ContentProjectStatus
    slots: list[SlotOut]
    missing: int


class NameOption(BaseModel):
    name: str
    reason: str


class TaskOut(BaseModel):
    id: int
    content_project_id: int
    content_project: str
    platform: PlatformCode
    platform_label: str
    language: Language
    status: ChannelSetupStatus
    display_name: str
    handle: str
    alt_handles: list[str]
    handle_check: dict[str, str]
    bio: str
    bio_max: int
    email: str | None
    email_status: MailAliasStatus
    email_error: str | None
    has_avatar: bool
    has_banner: bool
    signup_url: str
    steps: list[str]
    text_source: str
    name_options: list[NameOption]
    research_facts: list[str]
    research_live: bool
    researched_at: str | None
    channel_id: int | None
    created_at: datetime
    completed_at: datetime | None


class MailStatusOut(BaseModel):
    mode: str
    domain: str
    forward_to_set: bool
    problem: str | None


class MailCheckOut(BaseModel):
    ok: bool
    mode: str
    enabled: bool | None
    status: str | None
    rules_used: int | None
    rule_limit: int
    findings: list[str]


class TestMailOut(BaseModel):
    status: str
    to: str
    message: str


class PrepareIn(BaseModel):
    project_id: int
    platforms: list[PlatformCode] | None = None
    languages: list[Language] | None = None


class TaskPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    handle: str | None = Field(default=None, max_length=40)
    bio: str | None = Field(default=None, max_length=1000)


class CompleteIn(BaseModel):
    handle: str | None = Field(default=None, max_length=40)


class CompleteOut(BaseModel):
    task: TaskOut
    channel_id: int


def _out(task: ChannelSetupTask) -> TaskOut:
    rules = channel_setup.RULES[task.platform]
    return TaskOut(
        id=task.id,
        content_project_id=task.content_project_id,
        content_project=task.content_project.name,
        platform=task.platform,
        platform_label=rules.label,
        language=task.language,
        status=task.status,
        display_name=task.display_name,
        handle=task.handle,
        alt_handles=[str(h) for h in task.alt_handles],
        handle_check={str(k): str(v) for k, v in task.handle_check.items()},
        bio=task.bio,
        bio_max=rules.bio_max,
        email=task.email,
        email_status=task.email_status,
        email_error=task.email_error,
        has_avatar=bool(task.avatar_uri),
        has_banner=bool(task.banner_uri),
        signup_url=rules.signup_url,
        steps=list(rules.steps),
        text_source=task.text_source,
        name_options=[
            NameOption(name=str(o.get("name", "")), reason=str(o.get("reason", "")))
            for o in task.name_options or []
            if isinstance(o, dict) and o.get("name")
        ],
        research_facts=[str(f) for f in (task.research or {}).get("facts", [])],
        research_live=bool((task.research or {}).get("live")),
        researched_at=(task.research or {}).get("collected_at"),
        channel_id=task.channel_id,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


def _task(db: DbSession, task_id: int) -> ChannelSetupTask:
    task = db.get(ChannelSetupTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Aufgabe nicht gefunden")
    return task


def _coverage_out(cov: channel_setup.Coverage) -> CoverageOut:
    return CoverageOut(
        project_id=cov.project.id,
        project=cov.project.name,
        project_status=cov.project.status,
        slots=[
            SlotOut(
                platform=s.platform,
                language=s.language,
                state=s.state,
                channel_id=s.channel_id,
                channel_name=s.channel_name,
                task_id=s.task_id,
            )
            for s in cov.slots
        ],
        missing=len(cov.missing),
    )


@router.get("/coverage", response_model=list[CoverageOut])
def coverage(_: Viewer, db: DbSession) -> list[CoverageOut]:
    """Per topic area: which platform/language has a channel, a prepared task or nothing."""
    projects = db.scalars(
        select(ContentProject)
        .where(ContentProject.status != ContentProjectStatus.ARCHIVED)
        .order_by(ContentProject.priority, ContentProject.name)
    ).all()
    return [_coverage_out(channel_setup.coverage(db, p)) for p in projects]


@router.get("/mail", response_model=MailStatusOut)
def mail_status(_: Viewer, settings: AppSettings) -> MailStatusOut:
    return MailStatusOut(
        mode=settings.mail_routing_mode,
        domain=settings.mail_alias_domain,
        forward_to_set=bool(settings.mail_forward_to.strip()),
        problem=mail_alias.live_problem(settings) if settings.mail_routing_mode == "live" else None,
    )


@router.post("/mail/check", response_model=MailCheckOut)
def mail_check(_: Admin, settings: AppSettings) -> MailCheckOut:
    """Read-only check at Cloudflare: Email Routing active, rules left before the limit."""
    res = mail_alias.check(settings)
    return MailCheckOut(
        ok=res.ok,
        mode=res.mode,
        enabled=res.enabled,
        status=res.status,
        rules_used=res.rules_used,
        rule_limit=res.rule_limit,
        findings=list(res.findings),
    )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    _: Viewer, db: DbSession, state: ChannelSetupStatus = ChannelSetupStatus.OPEN
) -> list[TaskOut]:
    rows = db.scalars(
        select(ChannelSetupTask)
        .where(ChannelSetupTask.status == state)
        .order_by(
            ChannelSetupTask.id.desc() if state != ChannelSetupStatus.OPEN else ChannelSetupTask.id
        )
        .limit(200)
    ).all()
    return [_out(t) for t in rows]


@router.post("/prepare", response_model=list[TaskOut], status_code=201)
def prepare(body: PrepareIn, admin: Admin, db: DbSession, settings: AppSettings) -> list[TaskOut]:
    """Prepare every missing channel of a topic area (name, bio, images, e-mail)."""
    project = db.get(ContentProject, body.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
    try:
        tasks = channel_setup.prepare(
            db,
            settings,
            project,
            platforms=body.platforms,
            languages=body.languages,
            user_id=admin.id,
        )
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return [_out(t) for t in tasks]


@router.post("/channels/{channel_id}/prepare", response_model=TaskOut, status_code=201)
def prepare_for_channel(
    channel_id: int, admin: Admin, db: DbSession, settings: AppSettings
) -> TaskOut:
    """Prepare values for an existing channel that is not connected yet (placeholder)."""
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kanal nicht gefunden")
    try:
        task = channel_setup.prepare_for_channel(db, settings, channel, user_id=admin.id)
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def edit_task(
    task_id: int, body: TaskPatch, _: Admin, db: DbSession, settings: AppSettings
) -> TaskOut:
    task = _task(db, task_id)
    try:
        channel_setup.update(
            db, settings, task, display_name=body.display_name, handle=body.handle, bio=body.bio
        )
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(task)


@router.post("/tasks/{task_id}/research", response_model=TaskOut)
def research_again(task_id: int, admin: Admin, db: DbSession, settings: AppSettings) -> TaskOut:
    """Fresh market data and new name ideas for an open task."""
    task = _task(db, task_id)
    try:
        channel_setup.research_again(db, settings, task, user_id=admin.id)
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(task)


@router.post("/tasks/{task_id}/email", response_model=TaskOut)
def retry_email(task_id: int, _: Admin, db: DbSession, settings: AppSettings) -> TaskOut:
    task = _task(db, task_id)
    try:
        channel_setup.retry_email(db, settings, task)
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(task)


@router.post("/tasks/{task_id}/test-mail", response_model=TestMailOut)
def test_mail(task_id: int, _: Admin, db: DbSession, settings: AppSettings) -> TestMailOut:
    """Send a test mail to the forwarding address; the operator checks the inbox."""
    task = _task(db, task_id)
    try:
        mail = channel_setup.send_test_mail(db, settings, task)
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if mail.status == "sent":
        message = "Testmail verschickt. Sie sollte in ein bis zwei Minuten in deinem Postfach sein."
    elif mail.status == "mock":
        message = (
            "Mailversand im Testmodus (MAIL_MODE=mock): Die Mail liegt nur im Postausgang. "
            "Für einen echten Test MAIL_MODE=smtp setzen oder selbst eine Mail an die Adresse "
            "schicken."
        )
    else:
        message = f"Versand fehlgeschlagen: {mail.error or 'unbekannter Fehler'}"
    return TestMailOut(status=mail.status, to=mail.to_address, message=message)


@router.post("/tasks/{task_id}/complete", response_model=CompleteOut)
def complete(task_id: int, body: CompleteIn, admin: Admin, db: DbSession) -> CompleteOut:
    """The account exists now: add the channel (paused, not connected) for the OAuth step."""
    task = _task(db, task_id)
    try:
        channel = channel_setup.complete(db, task, admin.id, handle=body.handle)
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return CompleteOut(task=_out(task), channel_id=channel.id)


@router.post("/tasks/{task_id}/dismiss", response_model=TaskOut)
def dismiss(task_id: int, admin: Admin, db: DbSession, settings: AppSettings) -> TaskOut:
    task = _task(db, task_id)
    try:
        channel_setup.dismiss(db, settings, task, admin.id)
    except channel_setup.SetupError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out(task)


def _image(db: DbSession, settings: AppSettings, task_id: int, kind: str) -> FileResponse:
    task = _task(db, task_id)
    uri = task.avatar_uri if kind == "avatar" else task.banner_uri
    if not uri:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kein Bild vorhanden")
    path = storage.resolve(settings, uri)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bilddatei fehlt")
    name = f"{task.handle}-{'profilbild' if kind == 'avatar' else 'banner'}.png"
    return FileResponse(path, media_type="image/png", filename=name)


@router.get("/tasks/{task_id}/avatar.png")
def avatar(task_id: int, _: Viewer, db: DbSession, settings: AppSettings) -> FileResponse:
    return _image(db, settings, task_id, "avatar")


@router.get("/tasks/{task_id}/banner.png")
def banner(task_id: int, _: Viewer, db: DbSession, settings: AppSettings) -> FileResponse:
    return _image(db, settings, task_id, "banner")
