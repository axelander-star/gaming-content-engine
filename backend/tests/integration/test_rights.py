"""Phase 6: rights management. Material without complete rights never reaches RIGHTS_APPROVED."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    LicenseStatus,
    MaterialStatus,
    PolicyStatus,
    UserRole,
)
from models import (
    AgentDecision,
    Asset,
    Creator,
    Game,
    GameplayFile,
    Notification,
    PublisherPolicy,
    RightsCheck,
    Source,
    Trend,
)
from services import orchestrator, rights, storage
from tests.conftest import login
from tests.factories import Chain, build_chain

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.4\n% test license\n"
TODAY = datetime.now(UTC).date()


def payload(chain: Chain) -> dict[str, Any]:
    return {"entity_type": "gameplay_files", "entity_id": chain.gameplay_file.id}


def run_pipeline(db: Session, chain: Chain) -> MaterialStatus:
    """Material Scout, then the rights check, exactly as the orchestrator runs them."""
    settings = get_settings()
    scout = orchestrator.run_agent(db, settings, "material_scout", payload(chain))
    assert scout.status == AgentRunStatus.SUCCEEDED, scout.output
    assert chain.gameplay_file.status == MaterialStatus.RIGHTS_PENDING
    check = orchestrator.run_agent(db, settings, "rights_license", payload(chain))
    assert check.status == AgentRunStatus.SUCCEEDED, check.output
    db.refresh(chain.gameplay_file)
    return chain.gameplay_file.status


def _source(db: Session, chain: Chain) -> Source:
    src = db.get(Source, chain.license.source_id)
    assert src is not None
    return src


def _policy(db: Session, chain: Chain) -> PublisherPolicy:
    policy = db.scalar(
        select(PublisherPolicy).where(PublisherPolicy.game_id == chain.gameplay_file.game_id)
    )
    assert policy is not None
    return policy


def _block_creator(db: Session, chain: Chain) -> None:
    creator = db.get(Creator, _source(db, chain).creator_id)
    assert creator is not None
    creator.is_blocked = True


def _no_game(db: Session, chain: Chain) -> None:
    chain.gameplay_file.game_id = None
    asset = db.get(Asset, chain.gameplay_file.asset_id)
    assert asset is not None
    asset.game_id = None


#: (criterion, expected outcome, change that breaks exactly this criterion)
BREAKS: list[tuple[str, str, Callable[[Session, Chain], None]]] = [
    ("license", "missing", lambda db, c: setattr(c.license, "status", LicenseStatus.PENDING)),
    ("license", "denied", lambda db, c: setattr(c.license, "status", LicenseStatus.REVOKED)),
    ("license", "denied", lambda db, c: setattr(c.license, "status", LicenseStatus.REJECTED)),
    ("evidence", "missing", lambda db, c: setattr(c.license, "document_uri", None)),
    ("evidence", "missing", lambda db, c: setattr(c.license, "verified_by_user_id", None)),
    ("provenance", "denied", lambda db, c: setattr(_source(db, c), "is_blocked", True)),
    ("provenance", "denied", _block_creator),
    ("provenance", "missing", lambda db, c: setattr(_source(db, c), "provenance_notes", None)),
    ("commercial_use", "denied", lambda db, c: setattr(c.license, "allows_commercial_use", False)),
    ("editing", "denied", lambda db, c: setattr(c.license, "allows_editing", False)),
    ("short_form", "denied", lambda db, c: setattr(c.license, "allows_short_form", False)),
    ("platforms", "missing", lambda db, c: setattr(c.license, "allowed_platforms", [])),
    ("platforms", "denied", lambda db, c: setattr(c.license, "allowed_platforms", ["youtube"])),
    ("languages", "missing", lambda db, c: setattr(c.license, "allowed_languages", [])),
    ("languages", "denied", lambda db, c: setattr(c.license, "allowed_languages", ["de"])),
    (
        "validity",
        "denied",
        lambda db, c: setattr(c.license, "valid_until", TODAY - timedelta(days=1)),
    ),
    (
        "validity",
        "denied",
        lambda db, c: setattr(c.license, "valid_from", TODAY + timedelta(days=3)),
    ),
    ("monetization", "denied", lambda db, c: setattr(c.license, "allows_monetization", False)),
    ("music", "denied", lambda db, c: setattr(c.license, "music_cleared", False)),
    ("publisher_policy", "missing", lambda db, c: db.delete(_policy(db, c))),
    ("publisher_policy", "missing", _no_game),
    (
        "publisher_policy",
        "denied",
        lambda db, c: setattr(_policy(db, c), "status", PolicyStatus.FORBIDDEN),
    ),
    (
        "publisher_policy",
        "denied",
        lambda db, c: setattr(_policy(db, c), "status", PolicyStatus.LICENSE_REQUIRED),
    ),
]


def test_every_criterion_is_covered_by_a_break() -> None:
    assert {key for key, _, _ in BREAKS} == {key for key, _ in rights.CRITERIA}


def test_complete_license_is_approved(db: Session) -> None:
    chain = build_chain(db)
    assert run_pipeline(db, chain) == MaterialStatus.RIGHTS_APPROVED
    check = db.scalar(
        select(RightsCheck).where(RightsCheck.gameplay_file_id == chain.gameplay_file.id)
    )
    assert check is not None and check.approved
    assert len(check.checks) == len(rights.CRITERIA)
    assert check.missing == [] and check.denied == []


@pytest.mark.parametrize(("key", "outcome", "breaker"), BREAKS)
def test_single_failing_criterion_is_rejected(
    db: Session, key: str, outcome: str, breaker: Callable[[Session, Chain], None]
) -> None:
    chain = build_chain(db)
    breaker(db, chain)
    db.flush()
    result = rights.evaluate(db, chain.gameplay_file)
    failed = {c.key: c.outcome for c in result.checks if c.outcome != "ok"}
    assert failed == {key: outcome}, failed
    assert not result.approved

    assert run_pipeline(db, chain) == MaterialStatus.RIGHTS_REJECTED
    check = db.scalars(
        select(RightsCheck).where(RightsCheck.gameplay_file_id == chain.gameplay_file.id)
    ).one()
    assert not check.approved
    assert key in (check.missing if outcome == "missing" else check.denied)
    decision = db.scalars(
        select(AgentDecision).where(AgentDecision.decision_type == "rights_check")
    ).all()[-1]
    assert key in (decision.reasoning or "")


def test_license_required_policy_passes_with_publisher_permission(db: Session) -> None:
    chain = build_chain(db)
    _policy(db, chain).status = PolicyStatus.LICENSE_REQUIRED
    chain.license.publisher_permission = True
    db.flush()
    assert rights.evaluate(db, chain.gameplay_file).approved


def test_material_without_license_is_missing_everything(db: Session) -> None:
    orphan = GameplayFile(asset_id=-1, storage_uri="mock://x", sha256="c" * 64)  # not persisted
    result = rights.evaluate(db, orphan)
    assert not result.approved
    assert result.missing == [k for k, _ in rights.CRITERIA]


def test_scout_reports_missing_evidence_and_sorts_by_game(db: Session) -> None:
    chain = build_chain(db)
    game_id = chain.gameplay_file.game_id
    chain.gameplay_file.game_id = None  # the asset still knows the game
    chain.license.document_uri = None
    db.flush()
    run = orchestrator.run_agent(db, get_settings(), "material_scout", payload(chain))
    assert run.status == AgentRunStatus.SUCCEEDED
    assert chain.gameplay_file.game_id == game_id
    assert run.output is not None
    assert run.output["missing_evidence"] == ["Kein Lizenzdokument hochgeladen"]
    assert db.scalar(select(Notification).where(Notification.title.like("Fehlende Nachweise%")))


def test_rights_agent_waits_for_scout(db: Session) -> None:
    chain = build_chain(db)  # still DISCOVERED
    run = orchestrator.run_agent(db, get_settings(), "rights_license", payload(chain))
    assert run.status == AgentRunStatus.SKIPPED
    assert run.output is not None and run.output["gate"] == "wrong_status"


# --- expiry and re-checks -----------------------------------------------------


def test_expiry_sweep_expires_warns_and_rechecks(db: Session) -> None:
    old = build_chain(db)
    old.gameplay_file.status = MaterialStatus.ANALYZED
    old.license.valid_until = TODAY - timedelta(days=1)
    soon = build_chain(db)
    soon.license.valid_until = TODAY + timedelta(days=5)
    later = build_chain(db)
    later.license.valid_until = TODAY + timedelta(days=60)
    db.flush()

    result = rights.expiry_sweep(db, actor="test", today=TODAY)
    assert old.license.id in result.expired and old.license.status == LicenseStatus.EXPIRED
    assert old.gameplay_file.id in result.rechecked
    assert old.gameplay_file.status == MaterialStatus.RIGHTS_PENDING
    assert soon.license.id in result.expiring and soon.license.expiry_notified_at is not None
    assert later.license.id not in result.expiring

    again = rights.expiry_sweep(db, actor="test", today=TODAY)
    assert soon.license.id not in again.expiring  # warned only once
    assert old.license.id not in again.expired


def test_rights_sweep_via_orchestrator(db: Session) -> None:
    chain = build_chain(db)
    chain.license.valid_until = TODAY - timedelta(days=2)
    db.flush()
    run = orchestrator.run_agent(db, get_settings(), "rights_license", {"sweep": True})
    assert run.status == AgentRunStatus.SUCCEEDED
    assert run.output is not None and chain.license.id in run.output["expired"]


def test_material_needs_sweep_lists_trending_games_without_material(db: Session) -> None:
    covered = build_chain(db)
    covered.gameplay_file.status = MaterialStatus.RIGHTS_APPROVED
    uncovered = Game(name="Trend Ohne Material", slug="trend-ohne-material")
    db.add(uncovered)
    db.flush()
    now = datetime.now(UTC)
    for game_id, score in ((covered.gameplay_file.game_id, 9990), (uncovered.id, 9980)):
        for lang in ("de", "en"):
            db.add(
                Trend(
                    game_id=game_id, source="internal", language=lang, score=score, detected_at=now
                )
            )
    db.flush()
    run = orchestrator.run_agent(db, get_settings(), "material_scout", {"sweep": True})
    assert run.status == AgentRunStatus.SUCCEEDED, run.output
    assert run.output is not None
    names = [n["game"] for n in run.output["needs"]]
    assert names.count("Trend Ohne Material") == 1
    assert all(n["game_id"] != covered.gameplay_file.game_id for n in run.output["needs"])


# --- storage ------------------------------------------------------------------


def _settings(tmp_path: Path, **extra: Any) -> Settings:
    return get_settings().model_copy(update={"media_root": str(tmp_path), **extra})


def test_storage_accepts_valid_documents_content_addressed(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    a = storage.store_document(s, PDF, "application/pdf", "licenses/1")
    b = storage.store_document(s, PDF, "application/pdf", "licenses/1")
    assert a == b and a.uri.startswith("local://licenses/1/")
    assert storage.resolve(s, a.uri).read_bytes() == PDF


@pytest.mark.parametrize(
    ("data", "ctype"),
    [
        (b"", "application/pdf"),
        (b"<html>", "application/pdf"),
        (PDF, "text/html"),
        (b"%PDF-" + b"x" * 200, "application/pdf"),
    ],
)
def test_storage_rejects_bad_documents(tmp_path: Path, data: bytes, ctype: str) -> None:
    with pytest.raises(storage.StorageError):
        storage.store_document(_settings(tmp_path, max_document_bytes=100), data, ctype, "x")


@pytest.mark.parametrize("uri", ["local://../etc/passwd", "local:///etc/passwd", "s3://x/y"])
def test_storage_refuses_paths_outside_media_root(tmp_path: Path, uri: str) -> None:
    with pytest.raises(storage.StorageError):
        storage.resolve(_settings(tmp_path), uri)


# --- API ----------------------------------------------------------------------


@pytest.fixture
def rights_api(api: TestClient, tmp_path: Path) -> Iterator[TestClient]:
    app = api.app
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)  # type: ignore[attr-defined]
    yield api


def test_api_full_rights_workflow(
    rights_api: TestClient, db: Session, make_user: Callable[..., Any]
) -> None:
    make_user("admin@example.com", UserRole.ADMIN)
    make_user("op@example.com", UserRole.OPERATOR)
    c = rights_api
    h = login(c, "op@example.com")

    creator = c.post("/api/creators", json={"name": "Partner GmbH"}, headers=h).json()
    source = c.post(
        "/api/sources",
        json={
            "creator_id": creator["id"],
            "type": "licensed_creator",
            "name": "Partner Uploads",
            "url": "https://partner.example.com/vertrag",
        },
        headers=h,
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]

    lic = c.post("/api/licenses", json={"source_id": source_id}, headers=h)
    assert lic.status_code == 201, lic.text
    lic_body = lic.json()
    assert lic_body["status"] == "pending"
    assert not lic_body["allows_commercial_use"]  # deny by default
    lic_id = lic_body["id"]

    # operators cannot approve; admins cannot approve without a document
    assert c.post(f"/api/licenses/{lic_id}/approve", headers=h).status_code == 403
    c.post("/api/auth/logout", headers=h)
    ha = login(c, "admin@example.com")
    assert c.post(f"/api/licenses/{lic_id}/approve", headers=ha).status_code == 409

    bad = c.post(
        f"/api/licenses/{lic_id}/documents",
        files={"file": ("v.pdf", b"<script>", "application/pdf")},
        headers=ha,
    )
    assert bad.status_code == 422
    for n in (1, 2):
        up = c.post(
            f"/api/licenses/{lic_id}/documents",
            files={"file": (f"v{n}.pdf", PDF + bytes([n]), "application/pdf")},
            headers=ha,
        )
        assert up.status_code == 201, up.text
        assert up.json()["version"] == n
    docs = c.get(f"/api/licenses/{lic_id}/documents").json()
    assert [d["version"] for d in docs] == [1, 2]
    file = c.get(f"/api/licenses/{lic_id}/documents/{docs[0]['id']}/file")
    assert file.status_code == 200 and file.content == PDF + b"\x01"

    terms = {
        "allows_commercial_use": True,
        "allows_editing": True,
        "allows_short_form": True,
        "allows_monetization": True,
        "music_cleared": True,
        "allowed_platforms": ["youtube", "tiktok", "instagram", "facebook"],
        "allowed_languages": ["de", "en"],
    }
    assert c.patch(f"/api/licenses/{lic_id}", json=terms, headers=ha).status_code == 200
    approved = c.post(f"/api/licenses/{lic_id}/approve", headers=ha)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved" and approved.json()["documents"] == 2

    game = c.post("/api/games", json={"name": "Partner Spiel"}, headers=ha).json()
    assert c.post("/api/games", json={"name": "Partner Spiel"}, headers=ha).status_code == 409
    pol = c.put(
        f"/api/games/{game['id']}/policy",
        json={"status": "permitted", "notes": "Richtlinie erlaubt Clips"},
        headers=ha,
    )
    assert pol.status_code == 200, pol.text

    body = {
        "source_id": source_id,
        "license_id": lic_id,
        "game_id": game["id"],
        "storage_uri": "mock://partner/raw.mp4",
        "sha256": "a" * 64,
    }
    mat = c.post("/api/materials", json=body, headers=ha)
    assert mat.status_code == 201, mat.text
    assert mat.json()["status"] == "DISCOVERED"
    assert c.post("/api/materials", json=body, headers=ha).status_code == 409
    material_id = mat.json()["id"]

    settings = get_settings()
    p = {"entity_type": "gameplay_files", "entity_id": material_id}
    orchestrator.run_agent(db, settings, "material_scout", p)
    orchestrator.run_agent(db, settings, "rights_license", p)
    detail = c.get(f"/api/materials/{material_id}").json()
    assert detail["status"] == "RIGHTS_APPROVED", detail["last_check"]
    assert detail["last_check"]["approved"]

    # blocking the creator sends the material back to the rights check
    blocked = c.post(f"/api/creators/{creator['id']}/block", headers=ha).json()
    assert blocked["rechecked"] == [material_id]
    orchestrator.run_agent(db, settings, "rights_license", p)
    detail = c.get(f"/api/materials/{material_id}").json()
    assert detail["status"] == "RIGHTS_REJECTED"
    assert "provenance" in detail["last_check"]["denied"]

    # unblocking and a stricter policy: still rejected, now because of the policy
    assert c.post(f"/api/creators/{creator['id']}/unblock", headers=ha).status_code == 200
    c.put(
        f"/api/games/{game['id']}/policy",
        json={"status": "forbidden", "notes": "Publisher untersagt Clips"},
        headers=ha,
    )
    orchestrator.run_agent(db, settings, "rights_license", p)
    detail = c.get(f"/api/materials/{material_id}").json()
    assert detail["status"] == "RIGHTS_REJECTED"
    assert detail["last_check"]["denied"] == ["publisher_policy"]

    # editing an approved license resets it to pending
    edited = c.patch(f"/api/licenses/{lic_id}", json=terms, headers=ha).json()
    assert edited["status"] == "pending" and edited["verified_by_user_id"] is None

    criteria = c.get("/api/rights/criteria").json()
    assert [x["key"] for x in criteria] == [k for k, _ in rights.CRITERIA]


def test_api_material_requires_matching_source(
    rights_api: TestClient, db: Session, make_user: Callable[..., Any]
) -> None:
    make_user("op@example.com", UserRole.OPERATOR)
    chain = build_chain(db)
    other = Source(type=_source(db, chain).type, name="X")
    db.add(other)
    db.flush()
    h = login(rights_api, "op@example.com")
    r = rights_api.post(
        "/api/materials",
        json={
            "source_id": other.id,
            "license_id": chain.license.id,
            "storage_uri": "mock://x.mp4",
            "sha256": "b" * 64,
        },
        headers=h,
    )
    assert r.status_code == 422


def test_viewer_cannot_change_rights(rights_api: TestClient, make_user: Callable[..., Any]) -> None:
    make_user("viewer@example.com", UserRole.VIEWER)
    h = login(rights_api, "viewer@example.com")
    assert rights_api.get("/api/licenses").status_code == 200
    assert rights_api.post("/api/creators", json={"name": "x"}, headers=h).status_code == 403


def test_seeded_policy_for_gta_vi(db: Session) -> None:
    from services.seed import seed_base_data

    seed_base_data(db)
    game = db.scalar(select(Game).where(Game.slug == "grand-theft-auto-vi"))
    assert game is not None
    policy = db.scalar(select(PublisherPolicy).where(PublisherPolicy.game_id == game.id))
    assert policy is not None and policy.status == PolicyStatus.LICENSE_REQUIRED
