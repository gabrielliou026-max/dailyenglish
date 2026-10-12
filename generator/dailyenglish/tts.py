"""Kokoro TTS：把聽力稿轉成 mp3。

模型檔（約 120 MB）由 GitHub Actions 下載並快取，路徑以環境變數指定：
    KOKORO_MODEL   kokoro-v1.0.int8.onnx
    KOKORO_VOICES  voices-v1.0.bin
找不到模型或套件時 from_env() 回傳 None，當天就不出聽力題。
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from typing import Protocol

from .items import Passage

log = logging.getLogger(__name__)

# 美式為主，混一些英式口音（多益聽力也有英、澳、加口音）
FEMALE_VOICES = ["af_heart", "af_bella", "af_nicole", "af_sarah", "bf_emma", "bf_isabella"]
MALE_VOICES = ["am_michael", "am_adam", "am_fenrir", "am_puck", "bm_george", "bm_lewis"]
LETTERS = "ABCD"

PAUSE_TURN = 0.45      # 對話換人
PAUSE_PROMPT = 1.2     # 應答題：題目唸完到選項
PAUSE_OPTION = 0.9     # 應答題：選項之間
MP3_KBPS = 32          # 單聲道語音，每分鐘約 240 KB


@dataclass(frozen=True)
class Segment:
    voice: str
    text: str
    pause_after: float


class TTS(Protocol):
    def render(self, segments: list[Segment]) -> tuple[bytes, int]: ...


def cast_voices(script: list[dict], rng: random.Random) -> dict[str, str]:
    """每位說話者一個聲音，同一段裡不重複。"""
    pools = {"f": rng.sample(FEMALE_VOICES, len(FEMALE_VOICES)),
             "m": rng.sample(MALE_VOICES, len(MALE_VOICES))}
    cast: dict[str, str] = {}
    for ln in script:
        if ln["speaker"] in cast:
            continue
        pool = pools["m" if ln["gender"] == "m" else "f"]
        cast[ln["speaker"]] = pool.pop(0) if pool else rng.choice(
            MALE_VOICES if ln["gender"] == "m" else FEMALE_VOICES)
    return cast


def build_segments(passage: Passage, rng: random.Random) -> list[Segment]:
    script = passage.script or []
    if not script:
        return []
    if passage.format == "question-response":
        first = script[0]
        cast = cast_voices(script, rng)
        other = "f" if first["gender"] == "m" else "m"
        answerer = cast_voices([{"speaker": "_", "gender": other}], rng)["_"]
        segs = [Segment(cast[first["speaker"]], first["text"], PAUSE_PROMPT)]
        options = passage.items[0].options if passage.items else []
        for i, opt in enumerate(options):
            segs.append(Segment(answerer, f"{LETTERS[i]}. {opt}", PAUSE_OPTION))
        return segs
    cast = cast_voices(script, rng)
    return [Segment(cast[ln["speaker"]], ln["text"], PAUSE_TURN) for ln in script]


class KokoroTTS:
    def __init__(self, model_path: str, voices_path: str):
        from kokoro_onnx import Kokoro  # 延後載入：沒有聽力時不需要這個套件
        self.kokoro = Kokoro(model_path, voices_path)

    @classmethod
    def from_env(cls) -> "KokoroTTS | None":
        model = os.environ.get("KOKORO_MODEL", "")
        voices = os.environ.get("KOKORO_VOICES", "")
        if not (os.path.isfile(model) and os.path.isfile(voices)):
            log.warning("Kokoro model files not found; listening is skipped today")
            return None
        try:
            return cls(model, voices)
        except Exception:
            log.exception("Kokoro failed to load; listening is skipped today")
            return None

    def render(self, segments: list[Segment]) -> tuple[bytes, int]:
        import lameenc
        import numpy as np

        parts = []
        rate = 24000
        for seg in segments:
            lang = "en-gb" if seg.voice.startswith("b") else "en-us"
            audio, rate = self.kokoro.create(seg.text, voice=seg.voice, speed=1.0, lang=lang)
            parts.append(np.asarray(audio, dtype=np.float32))
            parts.append(np.zeros(int(rate * seg.pause_after), dtype=np.float32))
        if not parts:
            raise ValueError("nothing to speak")
        pcm = np.concatenate(parts)
        enc = lameenc.Encoder()
        enc.set_bit_rate(MP3_KBPS)
        enc.set_in_sample_rate(rate)
        enc.set_channels(1)
        enc.set_quality(2)
        data = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        mp3 = enc.encode(data) + enc.flush()
        return bytes(mp3), int(len(pcm) * 1000 / rate)


def add_audio(tts: TTS, passages: list[Passage], rng: random.Random) -> list[Passage]:
    """替每段聽力產生音檔；失敗的那段直接捨棄，不影響其他題目。"""
    out = []
    for p in passages:
        try:
            p.audio, p.duration_ms = tts.render(build_segments(p, rng))
            out.append(p)
        except Exception:
            log.exception("TTS failed for %s passage; dropped", p.format)
    return out
