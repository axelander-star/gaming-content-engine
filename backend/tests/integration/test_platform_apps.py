"""TikTok app keys entered in the dashboard instead of the server's .env."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import PlatformCode, UserRole
from models import Channel, User
from models.access import SystemSetting
from services import platform, platform_apps, tiktok
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

REDIRECT = "https://studio.example/api/oauth/tiktok/callback"


@pytest.fixture
def base() -> Settings:
    return get_settings().model_copy(
        update={"tiktok_client_key": "", "tiktok_client_secret": SecretStr("")}
    )


def test_saved_keys_are_used_and_the_secret_is_encrypted(db: Session, base: Settings) -> None:
    assert not platform_apps.status(db, base, "tiktok").configured
    st = platform_apps.save(
        db, base, "tiktok", client_key="aw123", client_secret="s3cr3t",
        redirect_uri=REDIRECT, user_id=None,
    )  # fmt: skip
    assert st.configured and st.source == "studio" and st.secret_set and st.redirect_uri_ok
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == "platform_app.tiktok"))
    assert row is not None and "s3cr3t" not in str(row.value)

    eff = platform_apps.apply(db, base)
    assert eff.tiktok_client_key == "aw123"
    assert eff.tiktok_client_secret.get_secret_value() == "s3cr3t"
    url = urlparse(tiktok.authorization_url(eff, "st"))
    q = parse_qs(url.query)
    assert q["client_key"] == ["aw123"] and q["redirect_uri"] == [REDIRECT]
    # the original settings stay untouched
    assert base.tiktok_client_key == ""


def test_empty_secret_keeps_the_saved_one(db: Session, base: Settings) -> None:
    platform_apps.save(db, base, "tiktok", client_key="a", client_secret="one",
                       redirect_uri=REDIRECT, user_id=None)  # fmt: skip
    platform_apps.save(db, base, "tiktok", client_key="b", client_secret="",
                       redirect_uri=REDIRECT, user_id=None)  # fmt: skip
    eff = platform_apps.apply(db, base)
    assert eff.tiktok_client_key == "b"
    assert eff.tiktok_client_secret.get_secret_value() == "one"


@pytest.mark.parametrize(
    ("key", "secret", "redirect", "message"),
    [
        ("", "x", REDIRECT, "Client Key fehlt"),
        ("k", "", REDIRECT, "Client Secret fehlt"),
        ("k", "x", "http://studio.example/cb", "https://"),
        ("k", "x", REDIRECT + "?a=1", "https://"),
        ("k y", "x", REDIRECT, "Leerzeichen"),
    ],
)
def test_bad_input_is_refused(
    db: Session, base: Settings, key: str, secret: str, redirect: str, message: str
) -> None:
    with pytest.raises(platform_apps.PlatformAppError, match=message):
        platform_apps.save(db, base, "tiktok", client_key=key, client_secret=secret,
                           redirect_uri=redirect, user_id=None)  # fmt: skip


def test_environment_applies_when_nothing_is_saved(db: Session, base: Settings) -> None:
    env = base.model_copy(
        update={"tiktok_client_key": "env-key", "tiktok_client_secret": SecretStr("env")}
    )
    st = platform_apps.status(db, env, "tiktok")
    assert st.configured and st.source == "env"
    platform_apps.save(db, env, "tiktok", client_key="studio-key", client_secret="",
                       redirect_uri="", user_id=None)  # fmt: skip
    eff = platform_apps.apply(db, env)
    assert eff.tiktok_client_key == "studio-key"
    assert eff.tiktok_client_secret.get_secret_value() == "env"  # empty → environment
    platform_apps.clear(db, env, "tiktok", None)
    assert platform_apps.apply(db, env).tiktok_client_key == "env-key"


def test_api_saves_keys_and_connect_uses_them(
    db: Session, api: TestClient, make_user: Callable[..., User], base: Settings
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: base  # type: ignore[attr-defined]
    build_chain(db)
    channel = db.scalar(select(Channel).where(Channel.platform.has(code=PlatformCode.TIKTOK)))
    assert channel is not None
    make_user("admin@example.com", UserRole.ADMIN)
    make_user("op@example.com", UserRole.OPERATOR)
    db.commit()

    h_op = login(api, "op@example.com")
    assert api.get("/api/system/platform-apps/tiktok").status_code == 403
    api.post("/api/auth/logout", headers=h_op)
    h = login(api, "admin@example.com")

    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    assert res.status_code == 409 and "TikTok-App" in res.json()["detail"]

    body = {"client_key": "aw-key", "client_secret": "top-secret", "redirect_uri": REDIRECT}
    res = api.put("/api/system/platform-apps/tiktok", json=body, headers=h)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["configured"] and out["source"] == "studio" and "top-secret" not in res.text

    res = api.get("/api/system/platform-apps/tiktok")
    assert res.json()["client_key"] == "aw-key" and "top-secret" not in res.text

    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    assert res.status_code == 200, res.text
    q = parse_qs(urlparse(res.json()["url"]).query)
    assert q["client_key"] == ["aw-key"] and q["redirect_uri"] == [REDIRECT]

    bad = {"client_key": "aw-key", "client_secret": "", "redirect_uri": "http://x/cb"}
    res = api.put("/api/system/platform-apps/tiktok", json=bad, headers=h)
    assert res.status_code == 422 and "https://" in res.json()["detail"]
    assert api.get("/api/system/platform-apps/nope").status_code == 404

    res = api.delete("/api/system/platform-apps/tiktok", headers=h)
    assert res.status_code == 200 and not res.json()["configured"]


def test_instagram_keys_from_the_studio(
    db: Session, api: TestClient, make_user: Callable[..., User], base: Settings
) -> None:
    ig = base.model_copy(
        update={
            "instagram_login": "instagram",
            "instagram_app_id": "",
            "instagram_app_secret": SecretStr(""),
        }
    )
    api.app.dependency_overrides[get_settings] = lambda: ig  # type: ignore[attr-defined]
    build_chain(db)
    channel = db.scalar(select(Channel).where(Channel.platform.has(code=PlatformCode.INSTAGRAM)))
    assert channel is not None
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")

    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    assert res.status_code == 409 and "Instagram-App" in res.json()["detail"]

    redirect = "https://studio.example/api/oauth/instagram/callback"
    body = {"client_key": "1234567890", "client_secret": "ig-secret", "redirect_uri": redirect}
    res = api.put("/api/system/platform-apps/instagram", json=body, headers=h)
    assert res.status_code == 200 and res.json()["configured"] and "ig-secret" not in res.text

    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    assert res.status_code == 200, res.text
    q = parse_qs(urlparse(res.json()["url"]).query)
    assert q["client_id"] == ["1234567890"] and q["redirect_uri"] == [redirect]


def test_meta_app_from_the_studio_connects_instagram_via_facebook_login(
    db: Session, api: TestClient, make_user: Callable[..., User], base: Settings
) -> None:
    """New Meta apps only offer the Facebook login: a saved Meta app takes over Instagram."""
    st = base.model_copy(
        update={
            "instagram_login": "instagram",
            "instagram_app_id": "",
            "instagram_app_secret": SecretStr(""),
            "meta_app_id": "",
            "meta_app_secret": SecretStr(""),
        }
    )
    api.app.dependency_overrides[get_settings] = lambda: st  # type: ignore[attr-defined]
    build_chain(db)
    channel = db.scalar(select(Channel).where(Channel.platform.has(code=PlatformCode.INSTAGRAM)))
    assert channel is not None
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")

    redirect = "https://studio.example/api/oauth/meta/callback"
    bad = {"client_key": "555", "client_secret": "s", "redirect_uri": redirect, "config_id": "x1"}
    res = api.put("/api/system/platform-apps/meta", json=bad, headers=h)
    assert res.status_code == 422 and "Ziffern" in res.json()["detail"]

    body = {"client_key": "555", "client_secret": "meta-s", "redirect_uri": redirect,
            "config_id": "98765"}  # fmt: skip
    res = api.put("/api/system/platform-apps/meta", json=body, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["config_id"] == "98765" and "meta-s" not in res.text

    eff = platform_apps.apply(db, st)
    assert eff.instagram_login == "facebook" and eff.meta_login_config_id == "98765"

    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    assert res.status_code == 200, res.text
    url = urlparse(res.json()["url"])
    q = parse_qs(url.query)
    assert url.netloc == "www.facebook.com"
    assert q["client_id"] == ["555"] and q["redirect_uri"] == [redirect]
    assert q["config_id"] == ["98765"] and "scope" not in q
    state = q["state"][0]
    assert platform.read_state(eff, "meta", state)[0] == channel.id

    # an Instagram Login app, if present, keeps priority
    platform_apps.save(db, st, "instagram", client_key="111", client_secret="ig",
                       redirect_uri="", user_id=None)  # fmt: skip
    assert platform_apps.apply(db, st).instagram_login == "instagram"


def test_unknown_meta_failure_shows_metas_message(
    db: Session,
    api: TestClient,
    make_user: Callable[..., User],
    base: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure without a known reason carries Meta's own message to the dashboard."""
    import httpx

    from services import meta

    def fake(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": 100, "message": "Invalid config_id\nfor this app"}},
        )

    monkeypatch.setattr(platform, "TRANSPORT", httpx.MockTransport(fake))
    st = base.model_copy(update={"instagram_app_id": "", "instagram_app_secret": SecretStr("")})
    api.app.dependency_overrides[get_settings] = lambda: st  # type: ignore[attr-defined]
    build_chain(db)
    channel = db.scalar(select(Channel).where(Channel.platform.has(code=PlatformCode.INSTAGRAM)))
    assert channel is not None
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    h = login(api, "admin@example.com")
    body = {"client_key": "555", "client_secret": "meta-s",
            "redirect_uri": "https://studio.example/api/oauth/meta/callback"}  # fmt: skip
    assert api.put("/api/system/platform-apps/meta", json=body, headers=h).status_code == 200
    res = api.post(f"/api/channels/{channel.id}/connect", headers=h)
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]
    cb = api.get("/api/oauth/meta/callback", params={"state": state, "code": "c"},
                 follow_redirects=False)  # fmt: skip
    assert cb.status_code == 303
    q = parse_qs(urlparse(cb.headers["location"]).query)
    assert q["meta"] == ["failed"]
    assert q["detail"] == ["Anmeldung: Meta 400 Invalid config_id for this app"]
    assert "meta-s" not in cb.headers["location"]
    assert meta.PROVIDER == "meta"
