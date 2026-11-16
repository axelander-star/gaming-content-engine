"""Agents 21 and 22 (extension phase E7): Media Library and Own Production.

Media Library makes the preview and the 9:16 rendition of new library files; the
original stays untouched. Own Production renders a production from script,
voice, own pictures and subtitles into a library video. Neither agent publishes
anything: the result waits in the library for the approval center (E8).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select

from agents.base import Agent, AgentContext, AgentResult, AgentSkipError
from core.enums import CostCategory, LibraryStatus, NotificationLevel, ProductionStatus
from models.library import LibraryItem, OwnProduction
from services import library, notify, own_production, render, splitter, voice
from services.controls import get_operations
from services.queue import get_redis


def _int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class MediaLibraryAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        item_id = (
            _int(payload, "entity_id") if payload.get("entity_type") == "library_items" else None
        )
        splits: list[LibraryItem] = []
        if item_id is not None:
            item = s.scalar(select(LibraryItem).where(LibraryItem.id == item_id).with_for_update())
            items = [item] if item is not None and item.status == LibraryStatus.PROCESSING else []
            if item is not None and item.split_state == "queued":
                splits = [item]
        else:
            items = library.pending(s)
            splits = splitter.pending(s)
        expired = [] if item_id is not None else library.expire_originals(s, settings)
        for row in expired:
            ctx.decide(
                "library_original_deleted",
                row,
                "Original nach Ablauf der Aufbewahrungsfrist gelöscht"
                + (" und Datei archiviert (keine 9:16-Fassung)" if row["archived"] else ""),
                entity_type="library_items",
                entity_id=row["item_id"],
            )
        if not items and not expired and not splits:  # skipped runs do not count
            raise AgentSkipError("Keine neuen Dateien in der Mediathek")
        if not items and not splits:
            return AgentResult(output={"processed": [], "originals_deleted": expired})
        limit = get_operations(s).max_parallel_render_jobs
        done = []
        cut = []
        with render.render_slot(get_redis(), limit, settings.render_slot_ttl_s):
            for item in splits:
                info = splitter.run(s, settings, item)
                cut.append(info)
                made = len(info.get("made") or [])
                ctx.decide(
                    "library_split",
                    info,
                    (
                        f"„{item.title}“ in {made} Shorts zerlegt"
                        if info["status"] == "done"
                        else f"„{item.title}“ ließ sich nicht zerlegen: {info.get('error')}"
                    ),
                    entity_type="library_items",
                    entity_id=item.id,
                )
                if info["status"] == "done":
                    notify.add(
                        s,
                        f"Fertig: {made} Shorts aus „{item.title}“",
                        "Liegen in der Mediathek und können im Freigabecenter vorbereitet werden.",
                        level=NotificationLevel.INFO,
                        kind="split_done",
                        link="/mediathek",
                    )
            for item in items:
                info = library.process(s, settings, item)
                done.append(info)
                ctx.decide(
                    "library_processed",
                    info,
                    (
                        f"„{item.title}“: Vorschau und Hochformat fertig"
                        + (f" ({info.get('skipped')})" if info.get("skipped") else "")
                        if item.status == LibraryStatus.READY
                        else f"„{item.title}“ konnte nicht verarbeitet werden: {item.error_message}"
                    ),
                    entity_type="library_items",
                    entity_id=item.id,
                )
        return AgentResult(output={"processed": done, "split": cut, "originals_deleted": expired})


class OwnProductionAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        prod_id = (
            _int(payload, "entity_id") if payload.get("entity_type") == "own_productions" else None
        )
        prod = (
            s.scalar(select(OwnProduction).where(OwnProduction.id == prod_id).with_for_update())
            if prod_id is not None
            else None
        )
        if prod is None or prod.status != ProductionStatus.QUEUED:
            raise AgentSkipError("Keine wartende Produktion")
        # paid voices: ask the budget first (the mock voice costs nothing)
        provider = voice.get_provider(get_operations(s).tts_provider, settings)
        estimate = Decimal(0)
        if provider is not None and provider.cost_per_second_eur > 0:
            spoken = sum(
                voice.spoken_seconds(str(seg.get("text") or ""), prod.language)
                for seg in prod.segments
                if isinstance(seg, dict)
            )
            estimate = (provider.cost_per_second_eur * Decimal(str(round(spoken, 1)))).quantize(
                Decimal("0.0001")
            )
            ctx.authorize_cost(estimate)
        limit = get_operations(s).max_parallel_render_jobs
        with render.render_slot(get_redis(), limit, settings.render_slot_ttl_s):
            own_production.run(s, settings, prod)
        done = prod.status.value == ProductionStatus.DONE.value  # status changed by run()
        if estimate > 0 and done and provider is not None:
            ctx.add_cost(
                estimate,
                CostCategory.TTS,
                provider=provider.name,
                description=f"Eigenproduktion #{prod.id}",
            )
        info = {
            "production_id": prod.id,
            "status": prod.status.value,
            "item_id": prod.output_item_id,
            "duration_s": prod.duration_s,
            "render_seconds": prod.render_seconds,
            "error": prod.error_message,
        }
        ctx.decide(
            "production_rendered" if done else "production_failed",
            info,
            (
                f"„{prod.title}“: {prod.duration_s:.0f} s Video in {prod.render_seconds:.1f} s "
                "gerendert, liegt in der Mediathek."
                if done
                else f"„{prod.title}“ fehlgeschlagen: {prod.error_message}"
            ),
            entity_type="own_productions",
            entity_id=prod.id,
        )
        return AgentResult(output=info)
