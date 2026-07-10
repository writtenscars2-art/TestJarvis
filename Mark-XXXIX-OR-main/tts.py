"""
tts.py — TTS engine for JARVIS
Primary  : ElevenLabs (streaming PCM, high quality)
Fallback : Windows SAPI via win32com (free, built-in, no quota)

Automatically switches to SAPI when ElevenLabs returns quota_exceeded.
Switches back to ElevenLabs as soon as it works again.
"""
import json
import threading
import queue
import sys
from pathlib import Path

import sounddevice as sd

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

SAMPLE_RATE = 22050
CHANNELS    = 1
CHUNK_SIZE  = 4096


def _load_el_config() -> tuple[str, str]:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (
            data.get("elevenlabs_api_key",  "").strip(),
            data.get("elevenlabs_voice_id", "").strip(),
        )
    except Exception as e:
        print(f"[TTS] ERROR Could not load config: {e}")
        return "", ""


def _sapi_speak(text: str):
    """Windows built-in TTS via SAPI — free, no quota, works offline."""
    try:
        from win32com.client import Dispatch
        sapi = Dispatch("SAPI.SpVoice")
        sapi.Rate = 1      # slightly faster than default
        sapi.Volume = 100
        sapi.Speak(text)
    except Exception as e:
        print(f"[TTS] SAPI error: {e} — printing instead")
        print(f"JARVIS: {text}")


class ElevenLabsTTS:
    """
    Thread-safe TTS engine with automatic SAPI fallback.
    Quota errors are caught and SAPI is used transparently.
    """

    def __init__(self, on_speaking_change=None):
        self._api_key, self._voice_id = _load_el_config()
        self._on_speaking_change      = on_speaking_change
        self._q: queue.Queue          = queue.Queue()
        self._el_available            = bool(self._api_key and self._voice_id)
        self._quota_exceeded          = False   # set True on quota error
        self._quota_retry_at          = 0.0     # timestamp when to retry ElevenLabs
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

        if self._el_available:
            print(f"[TTS] OK ElevenLabs ready -- voice: {self._voice_id}")
        else:
            print("[TTS] ElevenLabs not configured -- using SAPI fallback")

    def speak(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        self._q.put(text)

    def stop(self):
        self._q.put(None)

    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                break
            self._play(item)

    def _play(self, text: str):
        self._set_speaking(True)
        try:
            import time as _t
            # If quota was exceeded, retry ElevenLabs after 5 minutes
            if self._quota_exceeded and _t.time() > self._quota_retry_at:
                self._quota_exceeded = False
                print("[TTS] Retrying ElevenLabs after cooldown...")

            # Use ElevenLabs if available and quota not exceeded
            if self._el_available and not self._quota_exceeded:
                try:
                    self._play_elevenlabs(text)
                    return
                except Exception as e:
                    err = str(e).lower()
                    if "quota_exceeded" in err or "quota exceeded" in err or "0 credits" in err:
                        self._quota_exceeded = True
                        self._quota_retry_at = _t.time() + 300  # retry in 5 minutes
                        print("[TTS] ElevenLabs quota exhausted — switching to SAPI (retry in 5 min)")
                    else:
                        print(f"[TTS] ElevenLabs error: {str(e)[:120]}")

            # SAPI fallback
            _sapi_speak(text)

        finally:
            self._set_speaking(False)

    def _play_elevenlabs(self, text: str):
        from elevenlabs import ElevenLabs
        client     = ElevenLabs(api_key=self._api_key)
        audio_iter = client.text_to_speech.convert(
            voice_id=self._voice_id,
            text=text,
            model_id="eleven_flash_v2_5",
            output_format="pcm_22050",
        )
        stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            for chunk in audio_iter:
                if chunk:
                    stream.write(chunk)
        finally:
            stream.stop()
            stream.close()

    def _set_speaking(self, value: bool):
        if self._on_speaking_change:
            try:
                self._on_speaking_change(value)
            except Exception:
                pass


# ── Module-level singleton ─────────────────────────────────────────────────────
_tts_instance: ElevenLabsTTS | None = None
_lock = threading.Lock()


def get_tts(on_speaking_change=None) -> ElevenLabsTTS:
    global _tts_instance
    with _lock:
        if _tts_instance is None:
            _tts_instance = ElevenLabsTTS(on_speaking_change=on_speaking_change)
        return _tts_instance


def speak(text: str):
    get_tts().speak(text)
