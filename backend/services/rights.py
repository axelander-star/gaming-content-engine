"""Rights check of gameplay material (PROJECT_SPEC section 5, business rule "deny by default").

Every criterion is checked separately and documented. A criterion can

* pass,
* be **denied** (the evidence says no, e.g. no commercial use), or
* be **missing** (the evidence is incomplete, e.g. no license document).

Material is approved only if every criterion passes. Missing evidence is
reported to the operator ("Fehlende Nachweise melden").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.enums import (
    LicenseStatus,
    MaterialStatus,
    NotificationLevel,
    PolicyStatus,
    SourceType,
)
from models.access import Notification
from models.production import GameplayFile
from models.rights import Asset, Creator, License, PublisherPolicy, Source
from services import audit, campaigns, workflow
from services.controls import get_operations

Outcome = Literal["ok", "denied", "missing"]

#: Material in these statuses is re-checked when its rights evidence changes.
RECHECK_STATUSES = (
    MaterialStatus.RIGHTS_APPROVED,
    MaterialStatus.ANALYZED,
    MaterialStatus.RIGHTS_REJECTED,
)
EXPIRY_WARNING_DAYS = 14

#: The eight questions of PROJECT_SPEC section 5 plus provenance and policy checks.
CRITERIA: tuple[tuple[str, str], ...] = (
    ("license", "Lizenz vorhanden und freigegeben"),
    ("evidence", "Lizenznachweis hinterlegt und geprüft"),
    ("provenance", "Herkunft dokumentiert, Quelle und Creator nicht gesperrt"),
    ("commercial_use", "Kommerzielle Nutzung erlaubt"),
    ("editing", "Bearbeitung erlaubt"),
    ("short_form", "Kurzvideos erlaubt"),
    ("platforms", "Alle gewünschten Plattformen abgedeckt"),
    ("languages", "Deutsche und englische Fassungen erlaubt"),
    ("validity", "Lizenz gültig"),
    ("monetization", "Monetarisierung erlaubt"),
    ("music", "Musik und weitere Bestandteile freigegeben"),
    ("publisher_policy", "Publisher-Richtlinie geprüft und erfüllt"),
)
LABELS = dict(CRITERIA)


@dataclass
class Check:
    key: str
    outcome: Outcome
    reason: str

    @property
    def label(self) -> str:
        return LABELS[self.key]


@dataclass
class RightsResult:
    checks: list[Check] = field(default_factory=list)
    license_id: int | None = None

    @property
    def approved(self) -> bool:
        return len(self.checks) == len(CRITERIA) and all(c.outcome == "ok" for c in self.checks)

    @property
    def denied(self) -> list[str]:
        return [c.key for c in self.checks if c.outcome == "denied"]

    @property
    def missing(self) -> list[str]:
        return [c.key for c in self.checks if c.outcome == "missing"]

    def as_json(self) -> list[dict[str, Any]]:
        return [{**asdict(c), "label": c.label} for c in self.checks]


def _today(today: date | None) -> date:
    return today or datetime.now(UTC).date()


def evaluate(session: Session, material: GameplayFile, today: date | None = None) -> RightsResult:
    """Check every criterion for ``material``. Does not change anything."""
    today = _today(today)
    ops = get_operations(session)
    result = RightsResult()
    add = result.checks.append

    asset = session.get(Asset, material.asset_id)
    lic = session.get(License, asset.license_id) if asset else None
    source = session.get(Source, asset.source_id) if asset else None
    creator = session.get(Creator, source.creator_id) if source and source.creator_id else None

    if asset is None or lic is None or source is None:
        # Without a license nothing else can be checked; every criterion is missing.
        for key, _ in CRITERIA:
            add(Check(key, "missing", "Kein Asset mit Lizenz verknüpft"))
        return result
    result.license_id = lic.id

    # 1. license status
    if lic.status == LicenseStatus.APPROVED:
        add(Check("license", "ok", "Lizenz freigegeben"))
    elif lic.status == LicenseStatus.PENDING:
        add(Check("license", "missing", "Lizenz ist noch nicht freigegeben"))
    else:
        add(Check("license", "denied", f"Lizenzstatus: {lic.status.value}"))

    # 2. evidence (document and human verification)
    if not lic.document_uri:
        add(Check("evidence", "missing", "Kein Lizenzdokument hochgeladen"))
    elif lic.verified_by_user_id is None:
        add(Check("evidence", "missing", "Lizenz wurde noch von niemandem geprüft"))
    else:
        add(Check("evidence", "ok", "Dokument vorhanden und geprüft"))

    # 3. provenance and block list
    if source.is_blocked or (creator is not None and creator.is_blocked):
        add(Check("provenance", "denied", "Quelle oder Creator ist gesperrt"))
    elif not (source.url or source.provenance_notes):
        add(Check("provenance", "missing", "Herkunft der Quelle ist nicht dokumentiert"))
    else:
        add(Check("provenance", "ok", f"Quelle: {source.name} ({source.type.value})"))

    # 4.–6. permissions (deny by default)
    for key, allowed, text in (
        ("commercial_use", lic.allows_commercial_use, "Kommerzielle Nutzung"),
        ("editing", lic.allows_editing, "Bearbeitung"),
        ("short_form", lic.allows_short_form, "Kurzvideos"),
    ):
        add(
            Check(
                key,
                "ok" if allowed else "denied",
                f"{text} {'erlaubt' if allowed else 'nicht erlaubt'}",
            )
        )

    # A campaign license covers only some platforms and languages; its clips go only
    # to the campaign channels (services.campaigns.target_channels), so here one
    # covered platform/language is enough.
    campaign = (
        campaigns.for_source(session, source.id) if source.type == SourceType.CAMPAIGN else None
    )

    # 7. platforms
    wanted = {p.value for p in ops.platforms}
    allowed_platforms = {str(p) for p in lic.allowed_platforms or []}
    missing_platforms = sorted(wanted - allowed_platforms)
    if not allowed_platforms:
        add(Check("platforms", "missing", "Keine Plattformen in der Lizenz angegeben"))
    elif campaign is not None:
        add(Check("platforms", "ok", "Nur Kampagne: " + ", ".join(sorted(allowed_platforms))))
    elif missing_platforms:
        add(Check("platforms", "denied", "Nicht abgedeckt: " + ", ".join(missing_platforms)))
    else:
        add(Check("platforms", "ok", "Alle Plattformen abgedeckt"))

    # 8. languages
    wanted_lang = {lang.value for lang in ops.languages}
    allowed_lang = {str(lang) for lang in lic.allowed_languages or []}
    missing_lang = sorted(wanted_lang - allowed_lang)
    if not allowed_lang:
        add(Check("languages", "missing", "Keine Sprachen in der Lizenz angegeben"))
    elif campaign is not None:
        add(Check("languages", "ok", "Nur Kampagne: " + ", ".join(sorted(allowed_lang))))
    elif missing_lang:
        add(Check("languages", "denied", "Nicht erlaubt: " + ", ".join(missing_lang)))
    else:
        add(Check("languages", "ok", "Alle Sprachfassungen erlaubt"))

    # 9. validity
    campaign_problem = campaigns.status_problem(campaign) if campaign is not None else None
    if campaign_problem:
        add(Check("validity", "denied", campaign_problem))
    elif lic.valid_from and lic.valid_from > today:
        add(Check("validity", "denied", f"Gültig erst ab {lic.valid_from.isoformat()}"))
    elif lic.valid_until and lic.valid_until < today:
        add(Check("validity", "denied", f"Abgelaufen am {lic.valid_until.isoformat()}"))
    else:
        until = lic.valid_until.isoformat() if lic.valid_until else "unbefristet"
        add(Check("validity", "ok", f"Gültig bis {until}"))

    # 10.–11. monetization and music
    add(
        Check(
            "monetization",
            "ok" if lic.allows_monetization else "denied",
            "Monetarisierung erlaubt"
            if lic.allows_monetization
            else "Monetarisierung nicht erlaubt",
        )
    )
    add(
        Check(
            "music",
            "ok" if lic.music_cleared else "denied",
            "Musik und Bestandteile freigegeben"
            if lic.music_cleared
            else "Musik/Bestandteile nicht freigegeben",
        )
    )

    # 12. publisher policy
    add(_policy_check(session, material, asset, lic))
    return result


def _policy_check(session: Session, material: GameplayFile, asset: Asset, lic: License) -> Check:
    game_id = material.game_id or asset.game_id
    if game_id is None:
        return Check("publisher_policy", "missing", "Material ist keinem Spiel zugeordnet")
    policy = session.scalar(select(PublisherPolicy).where(PublisherPolicy.game_id == game_id))
    if policy is None:
        return Check("publisher_policy", "missing", "Publisher-Richtlinie wurde noch nicht geprüft")
    if policy.status == PolicyStatus.FORBIDDEN:
        return Check(
            "publisher_policy", "denied", f"Publisher untersagt die Nutzung: {policy.notes}"
        )
    if policy.status == PolicyStatus.LICENSE_REQUIRED and not lic.publisher_permission:
        return Check(
            "publisher_policy",
            "denied",
            "Nur mit ausdrücklicher Erlaubnis des Rechteinhabers; liegt nicht vor",
        )
    return Check("publisher_policy", "ok", f"Richtlinie: {policy.status.value}")


# --- re-checks ----------------------------------------------------------------


def materials_for_license(session: Session, license_id: int) -> list[GameplayFile]:
    return list(
        session.scalars(
            select(GameplayFile)
            .join(Asset, Asset.id == GameplayFile.asset_id)
            .where(Asset.license_id == license_id)
        )
    )


def materials_for_source(session: Session, source_ids: list[int]) -> list[GameplayFile]:
    return list(
        session.scalars(
            select(GameplayFile)
            .join(Asset, Asset.id == GameplayFile.asset_id)
            .where(Asset.source_id.in_(source_ids))
        )
    )


def materials_for_game(session: Session, game_id: int) -> list[GameplayFile]:
    return list(
        session.scalars(
            select(GameplayFile)
            .join(Asset, Asset.id == GameplayFile.asset_id)
            .where(or_(GameplayFile.game_id == game_id, Asset.game_id == game_id))
        )
    )


def request_recheck(session: Session, materials: list[GameplayFile], actor: str) -> list[int]:
    """Send material back to RIGHTS_PENDING after its evidence changed."""
    moved = []
    for material in materials:
        if material.status in RECHECK_STATUSES:
            workflow.transition(session, material, MaterialStatus.RIGHTS_PENDING, actor)
            moved.append(material.id)
    return moved


# --- expiry monitoring --------------------------------------------------------


@dataclass
class SweepResult:
    expired: list[int] = field(default_factory=list)
    expiring: list[int] = field(default_factory=list)
    rechecked: list[int] = field(default_factory=list)


def expiry_sweep(session: Session, actor: str, today: date | None = None) -> SweepResult:
    """Expire outdated licenses, warn before expiry, re-check affected material."""
    today = _today(today)
    result = SweepResult()
    expired = session.scalars(
        select(License).where(
            License.status == LicenseStatus.APPROVED,
            License.valid_until.is_not(None),
            License.valid_until < today,
        )
    ).all()
    for lic in expired:
        lic.status = LicenseStatus.EXPIRED
        audit.record(
            session,
            "license.expired",
            agent=actor,
            entity_type="licenses",
            entity_id=lic.id,
            before={"status": "approved"},
            after={"status": "expired"},
        )
        session.add(
            Notification(
                level=NotificationLevel.WARNING,
                title=f"Lizenz #{lic.id} ist abgelaufen",
                body="Betroffenes Material wird erneut geprüft und nicht mehr verarbeitet.",
            )
        )
        result.expired.append(lic.id)
        result.rechecked += request_recheck(session, materials_for_license(session, lic.id), actor)

    soon = session.scalars(
        select(License).where(
            License.status == LicenseStatus.APPROVED,
            License.valid_until.is_not(None),
            License.valid_until >= today,
            License.valid_until <= today + timedelta(days=EXPIRY_WARNING_DAYS),
            License.expiry_notified_at.is_(None),
        )
    ).all()
    for lic in soon:
        assert lic.valid_until is not None
        session.add(
            Notification(
                level=NotificationLevel.WARNING,
                title=f"Lizenz #{lic.id} läuft am {lic.valid_until:%d.%m.%Y} ab",
                body="Bitte Verlängerung klären, sonst wird das Material danach gesperrt.",
            )
        )
        lic.expiry_notified_at = datetime.now(UTC)
        result.expiring.append(lic.id)
    session.flush()
    return result
