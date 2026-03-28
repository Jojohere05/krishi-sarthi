"""Speech utilities for Krishi Saarthi.

This module provides helper functions to:
- convert audio bytes (voice input) to Hindi text using a local STT engine
- convert Hindi text replies to audio bytes using a TTS engine

By default, these functions try to use optional third‑party libraries.
You can swap implementations depending on your deployment.
"""
from __future__ import annotations

import base64
from io import BytesIO
from typing import Optional

# STT: Whisper (local, offline). Install with:
#   pip install git+https://github.com/openai/whisper.git
try:  # pragma: no cover - optional dependency
    import whisper  # type: ignore
    _whisper_model: Optional["whisper.Whisper"] = None
except Exception:  # pragma: no cover - optional dependency missing
    whisper = None  # type: ignore
    _whisper_model = None

# TTS: gTTS (simple Hindi TTS, needs internet). Install with:
#   pip install gTTS
try:  # pragma: no cover - optional dependency
    from gtts import gTTS  # type: ignore
except Exception:  # pragma: no cover - optional dependency missing
    gTTS = None  # type: ignore


def transcribe_audio_to_text(audio_bytes: bytes, language: str = "hi") -> str:
    """Convert raw audio bytes to text using Whisper if available.

    Parameters
    ----------
    audio_bytes: bytes
        Binary audio data (e.g. WAV/MP3/OGG) from UploadFile.
    language: str
        Target language hint (default "hi" for Hindi).

    Returns
    -------
    str
        Transcribed text. If no STT engine is available, returns empty string.
    """
    if whisper is None:
        # No STT backend installed – caller should handle empty string
        return ""

    global _whisper_model
    if _whisper_model is None:
        # Load a small multilingual model; adjust as needed
        _whisper_model = whisper.load_model("small")

    # Whisper expects a file-like object; wrap bytes in BytesIO
    with BytesIO(audio_bytes) as buf:
        # Let Whisper handle format detection; language is a hint
        result = _whisper_model.transcribe(buf, language=language)
    text = (result.get("text") or "").strip()
    return text


def synthesize_text_to_speech_hi(text: str) -> bytes:
    """Convert Hindi text to speech audio bytes using gTTS if available.

    Returns raw MP3 bytes. If TTS is not available, returns empty bytes.
    The caller can decide whether to fall back to text-only when this is empty.
    """
    if not text:
        return b""
    if gTTS is None:
        return b""

    buf = BytesIO()
    tts = gTTS(text=text, lang="hi")
    tts.write_to_fp(buf)
    buf.seek(0)
    return buf.read()


def encode_audio_base64(audio_bytes: bytes) -> str:
    """Encode audio bytes to base64 string for JSON APIs."""
    if not audio_bytes:
        return ""
    return base64.b64encode(audio_bytes).decode("ascii")
