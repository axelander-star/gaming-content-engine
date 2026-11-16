"""Piper as the real voice (operator decision 16.11.2026).

The real voices cannot be downloaded in CI (no network to Hugging Face), so a
small stand-in program plays ``piper``: it takes the same arguments, reads the
text from stdin and writes a WAV whose length depends on the text.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
from pathlib import Path

import httpx
import pytest

from app import piper_voices
from core.config import Settings, get_settings
from core.enums import Language
from services import voice

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
]

FAKE_PIPER = """#!/bin/sh
# stand-in for piper: --model M --output_file F, text on stdin
while [ $# -gt 0 ]; do
  case "$1" in --model) model="$2"; shift 2;; --output_file) out="$2"; shift 2;; *) shift;; esac
done
text=$(cat)
echo "$model|$text" >> "$(dirname "$0")/calls.log"
words=$(echo "$text" | wc -w)
ffmpeg -v error -y -f lavfi -t "$words" -i "sine=f=220:r=22050" -ac 1 "$out"
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    fake = tmp_path / "bin" / "piper"
    fake.parent.mkdir()
    fake.write_text(FAKE_PIPER)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    voices = tmp_path / "voices"
    voices.mkdir()
    for name in voice.PIPER_VOICES:
        (voices / f"{name}.onnx").write_bytes(b"model")
        (voices / f"{name}.onnx.json").write_text("{}")
    return get_settings().model_copy(
        update={"piper_bin": str(fake), "piper_voice_dir": str(voices)}
    )


def test_piper_speaks_through_its_own_program(settings: Settings, tmp_path: Path) -> None:
    provider = voice.get_provider("piper", settings)
    assert isinstance(provider, voice.PiperVoice)
    assert provider.commercial_use_cleared and provider.cost_per_second_eur == 0
    assert provider.voices == {
        Language.DE: "de_DE-thorsten-medium",
        Language.EN: "en_US-ljspeech-high",
    }
    out = tmp_path / "beat.wav"
    seconds = provider.synthesize(
        "Drei Fehler\nbeim Lagern; rm -rf /", Language.DE, "de_DE-thorsten-medium", out
    )
    assert seconds == pytest.approx(7.0, abs=0.1)  # 7 words, one second each in the stand-in
    assert out.is_file() and not out.with_suffix(".piper.wav").exists()
    log = (Path(settings.piper_bin).parent / "calls.log").read_text().strip()
    # text arrives on stdin as one line, never as a command line argument
    assert log.endswith("de_DE-thorsten-medium.onnx|Drei Fehler beim Lagern; rm -rf /")


def test_only_cleared_and_downloaded_voices(settings: Settings, tmp_path: Path) -> None:
    provider = voice.PiperVoice(settings)
    with pytest.raises(voice.VoiceError, match="nicht für kommerzielle Nutzung"):
        provider.synthesize("Hallo", Language.DE, "de_DE-pavoque-low", tmp_path / "x.wav")
    (Path(settings.piper_voice_dir) / "en_US-ljspeech-high.onnx").unlink()
    with pytest.raises(voice.VoiceError, match=r"app\.piper_voices fetch"):
        provider.synthesize("Hello", Language.EN, "en_US-ljspeech-high", tmp_path / "y.wav")
    missing = settings.model_copy(update={"piper_bin": str(tmp_path / "nope")})
    with pytest.raises(voice.VoiceError, match="nicht installiert"):
        voice.PiperVoice(missing).synthesize(
            "Hallo", Language.DE, "de_DE-thorsten-medium", tmp_path / "z.wav"
        )


def test_fetch_checks_the_pinned_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = b"thorsten-model"
    name = "de_DE-thorsten-medium"
    folder, _sha, licence = voice.PIPER_VOICES[name]
    monkeypatch.setitem(
        voice.PIPER_VOICES, name, (folder, hashlib.sha256(good).hexdigest(), licence)
    )
    served: dict[str, bytes] = {
        f"/{folder}/{name}.onnx": good,
        f"/{folder}/{name}.onnx.json": b'{"audio": {}}',
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/rhasspy/piper-voices/resolve/main")
        return httpx.Response(200, content=served[path]) if path in served else httpx.Response(404)

    monkeypatch.setattr(piper_voices, "TRANSPORT", httpx.MockTransport(handler))
    settings = get_settings().model_copy(update={"piper_voice_dir": str(tmp_path / "v")})
    assert piper_voices.fetch(settings, [name]) == [name]
    assert (tmp_path / "v" / f"{name}.onnx").read_bytes() == good
    assert piper_voices.fetch(settings, [name]) == []  # present and intact: nothing to do

    (tmp_path / "v" / f"{name}.onnx").write_bytes(b"damaged")
    served[f"/{folder}/{name}.onnx"] = b"tampered"
    with pytest.raises(piper_voices.FetchError, match="Prüfsumme"):
        piper_voices.fetch(settings, [name])
    assert not (tmp_path / "v" / f"{name}.onnx").exists()  # a bad file is not kept
    with pytest.raises(piper_voices.FetchError, match="keine freigegebene Stimme"):
        piper_voices.fetch(settings, ["de_DE-pavoque-low"])


def test_cli_list(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(piper_voices, "get_settings", lambda: settings)
    assert piper_voices.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "de_DE-thorsten-medium" in out and "CC0" in out and "fehlt" in out  # fake bytes
