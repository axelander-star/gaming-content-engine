"""Agents 19 and 20 (extension phase E5): Research and Idea Lab.

Research collects feed items per active topic area. The idea lab turns unused
items into scored ideas. Neither agent can change the plan, start production or
publish: ideas wait in the idea lab until the operator decides.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentContext, AgentResult, AgentSkipError
from services import ai, ideas, research


def _project_id(payload: dict[str, Any]) -> int | None:
    value = payload.get("project_id")
    return value if isinstance(value, int) else None


class ResearchAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        projects = research.active_projects(ctx.session, _project_id(payload))
        results: list[dict[str, Any]] = []
        for project in projects:
            result = research.collect(ctx.session, ctx.settings, project)
            results.append(
                {
                    "project": result.project,
                    "sources": result.sources,
                    "new_items": result.new_items,
                    "errors": result.errors[:5],
                }
            )
        mode = ctx.settings.research_sources_mode
        ctx.decide(
            "research",
            {"projects": len(results), "new_items": sum(r["new_items"] for r in results)},
            "; ".join(
                f"{r['project']}: {r['new_items']} neue Einträge aus {r['sources'] or 'Beispiel'}"
                f"-Quellen" + (f", {len(r['errors'])} Fehler" if r["errors"] else "")
                for r in results
            )
            or "Kein aktiver Themenbereich.",
            inputs={"mode": mode},
        )
        return AgentResult(output={"mode": mode, "projects": results})


class IdeaLabAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        out: list[dict[str, Any]] = []
        for project in research.active_projects(ctx.session, _project_id(payload)):
            name = project.name
            try:
                result = ideas.draft(ctx.session, ctx.settings, project, agent_run_id=ctx.run.id)
            except ai.AIBlockedError as exc:
                raise AgentSkipError(f"KI nicht verfügbar: {exc.reason}") from exc
            except (ai.AIRefusedError, ai.AIFailedError) as exc:
                out.append({"project": name, "error": str(exc)})
                continue
            out.append(
                {
                    "project": name,
                    "items": result.items,
                    "ideas": [i.id for i in result.ideas],
                    "skipped": result.skipped,
                    "provider": result.provider,
                }
            )
            if result.ideas:
                ctx.decide(
                    "ideas",
                    {"project": name, "ideas": len(result.ideas)},
                    f"{len(result.ideas)} Ideen aus {result.items} Recherche-Einträgen; "
                    f"beste: „{max(result.ideas, key=lambda i: i.score).title}“.",
                    entity_type="content_projects",
                    entity_id=project.id,
                )
        return AgentResult(output={"projects": out})
