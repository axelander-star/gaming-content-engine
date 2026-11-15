"""Every API route needs a signed-in role, and every changing route the CSRF check.

Guards against a new endpoint (extension phases E1–E8 added many) that forgets
``Viewer``/``Operator``/``Admin`` or the router-level ``csrf_protect``.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

import api

#: Routes that are public on purpose: login, health checks, and the OAuth return
#: (protected by the signed, provider-bound ``state``).
PUBLIC = {
    ("POST", "/auth/login"),
    ("GET", "/health"),
    ("GET", "/health/ready"),
    ("GET", "/oauth/{provider}/callback"),
}


def _names(dependant: Any) -> list[str]:
    out: list[str] = []
    for sub in dependant.dependencies:
        out.append(getattr(sub.call, "__qualname__", repr(sub.call)))
        out.extend(_names(sub))
    return out


def _routes() -> list[tuple[str, str, list[str]]]:
    rows, seen = [], set()
    for info in pkgutil.iter_modules(api.__path__):
        module = importlib.import_module(f"api.{info.name}")
        for obj in vars(module).values():
            if not isinstance(obj, APIRouter) or id(obj) in seen:
                continue
            seen.add(id(obj))
            router_deps = [getattr(d.dependency, "__qualname__", "") for d in obj.dependencies]
            for route in obj.routes:
                if isinstance(route, APIRoute):
                    deps = router_deps + _names(route.dependant)
                    for method in route.methods or ():
                        rows.append((method, route.path, deps))
    return rows


def test_all_routes_need_a_role_and_changes_need_csrf() -> None:
    rows = _routes()
    assert len(rows) > 100  # the inventory really found the API
    problems = []
    for method, path, deps in rows:
        if (method, path) in PUBLIC:
            continue
        # require_role(...) or get_current_user (any signed-in user, e.g. logout, /me)
        if not any("require_role" in d or d == "get_current_user" for d in deps):
            problems.append(f"{method} {path}: no role check")
        if method not in ("GET", "HEAD") and not any("csrf" in d for d in deps):
            problems.append(f"{method} {path}: no CSRF check")
    assert problems == []


def test_new_extension_routes_are_in_the_inventory() -> None:
    paths = {p for _m, p, _d in _routes()}
    for expected in (
        "/approval/prepare",
        "/approval/{variant_id}/approve",
        "/library/{item_id}/file",
        "/productions/{production_id}/render",
        "/ideas/{idea_id}/accept",
        "/messages",
    ):
        assert any(p.endswith(expected) for p in paths), expected
