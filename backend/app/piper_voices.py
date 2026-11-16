"""Download the Piper voices. Run with ``python -m app.piper_voices fetch``.

Fetches every voice in ``services.voice.PIPER_VOICES`` (only voices whose licence
allows commercial use) from the official repository rhasspy/piper-voices into
``PIPER_VOICE_DIR`` and checks each model against its pinned SHA256. A file that
does not match is deleted and the command fails. ``list`` shows what is there.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import httpx

from core.config import Settings, get_settings
from services.voice import PIPER_VOICES

BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
#: Replaced in tests.
TRANSPORT: httpx.BaseTransport | None = None


class FetchError(RuntimeError):
    pass


def _download(client: httpx.Client, url: str, dest: Path) -> str:
    """Stream ``url`` to ``dest`` (via a temporary file); return the SHA256."""
    digest = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with client.stream("GET", url) as res:
            if res.status_code != 200:
                raise FetchError(f"{url}: HTTP {res.status_code}")
            with tmp.open("wb") as fh:
                for chunk in res.iter_bytes(1024 * 1024):
                    digest.update(chunk)
                    fh.write(chunk)
        tmp.replace(dest)
    except httpx.HTTPError as exc:
        raise FetchError(f"{url}: {type(exc).__name__}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(settings: Settings, names: list[str] | None = None) -> list[str]:
    """Download missing or damaged voices; returns the names that were downloaded."""
    target = Path(settings.piper_voice_dir)
    target.mkdir(parents=True, exist_ok=True)
    fetched = []
    with httpx.Client(transport=TRANSPORT, follow_redirects=True, timeout=120) as client:
        for name in names or list(PIPER_VOICES):
            if name not in PIPER_VOICES:
                raise FetchError(f"{name} ist keine freigegebene Stimme")
            folder, sha, _licence = PIPER_VOICES[name]
            model, config = target / f"{name}.onnx", target / f"{name}.onnx.json"
            if model.is_file() and config.is_file() and _sha256(model) == sha:
                continue
            got = _download(client, f"{BASE_URL}/{folder}/{name}.onnx", model)
            if got != sha:
                model.unlink(missing_ok=True)
                raise FetchError(f"{name}: Prüfsumme stimmt nicht ({got[:12]}…), Datei gelöscht")
            _download(client, f"{BASE_URL}/{folder}/{name}.onnx.json", config)
            fetched.append(name)
    return fetched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.piper_voices")
    parser.add_argument("command", choices=["fetch", "list"])
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.command == "fetch":
        try:
            done = fetch(settings)
        except FetchError as exc:
            print(f"Fehler: {exc}")
            return 1
        print(f"Geladen: {', '.join(done) or 'nichts, alles vorhanden'}")
        return 0
    target = Path(settings.piper_voice_dir)
    for name, (_folder, sha, licence) in PIPER_VOICES.items():
        model = target / f"{name}.onnx"
        state = "ok" if model.is_file() and _sha256(model) == sha else "fehlt"
        print(f"{name:<26} {state:<6} {licence}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
