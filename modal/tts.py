"""Studio narration voice: Kokoro-82M on Modal.

Deploy with:  modal deploy modal/tts.py
Needs a Modal secret named "reelworld-tts" holding STUDIO_VOICE_KEY
(create with: modal secret create reelworld-tts STUDIO_VOICE_KEY=<random>).

Contract: POST {text, voice, key} -> raw WAV bytes (24kHz
mono). Errors are JSON {"detail": ...}. The ReelWorld backend
caches every line by hash, so each line is synthesized once.
"""
import io
import os

import modal

APP = "reelworld-tts"
SECRET = "reelworld-tts"
VOICES = ("af_heart", "af_sarah", "am_adam", "am_michael",
          "bf_emma", "bm_george")
DEFAULT_VOICE = "af_heart"
MAX_CHARS = 500

def _bake_weights():
    """Download Kokoro weights into the image at build time."""
    from kokoro import KPipeline
    KPipeline(lang_code="a")


image = (
    # Python 3.11: Kokoro's phonemizer chain (spacy/blis) has no
    # 3.12+ wheels and fails to compile from source.
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("espeak-ng")
    .pip_install("kokoro", "soundfile", "fastapi")
    .run_function(_bake_weights)
)

app = modal.App(APP)


_PIPE = None


def _pipeline():
    """One Kokoro pipeline per container (slow init, fast reuse)."""
    global _PIPE
    if _PIPE is None:
        from kokoro import KPipeline
        _PIPE = KPipeline(lang_code="a")
    return _PIPE


# CPU: Kokoro-82M synthesizes short lines in seconds without a
# GPU, needs no payment method, and costs far less per line.
@app.function(image=image, timeout=300,
              secrets=[modal.Secret.from_name(SECRET)])
@modal.fastapi_endpoint(method="POST")
def speak(item: dict):
    """Synthesize one narration line."""
    from fastapi.responses import JSONResponse, Response
    try:
        import soundfile as sf
    except ImportError:
        return JSONResponse({"detail": "server is missing soundfile"},
                            status_code=500)
    want = os.environ.get("STUDIO_VOICE_KEY") or ""
    if not want or (item.get("key") or "") != want:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    text = (item.get("text") or "").strip()
    voice = (item.get("voice") or DEFAULT_VOICE).strip()
    if not text:
        return JSONResponse({"detail": "text must not be empty"},
                            status_code=400)
    if len(text) > MAX_CHARS:
        return JSONResponse(
            {"detail": f"text must be {MAX_CHARS} characters or fewer"},
            status_code=400)
    if voice not in VOICES:
        return JSONResponse(
            {"detail": f"voice must be one of: {', '.join(VOICES)}"},
            status_code=400)
    try:
        import torch
        pipe = _pipeline()
        chunks = []
        for _gs, _ps, audio in pipe(text, voice=voice):
            chunks.append(audio)
        if not chunks:
            raise RuntimeError("model returned no audio")
        wav = torch.cat(chunks, dim=-1).numpy()
        buf = io.BytesIO()
        sf.write(buf, wav, 24000, format="WAV")
        return Response(buf.getvalue(), media_type="audio/wav")
    except Exception as e:
        return JSONResponse({"detail": f"synthesis failed: {e}"[:200]},
                            status_code=502)
