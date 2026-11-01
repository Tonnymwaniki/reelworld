# Studio voice research (creative-scripts step 10)

Goal: a Modal-hosted TTS function that turns each narration line
into audio, cached by line hash in `data/audio/`, played in the
player and mixed into the exported WebM. Researched 2026-11-01.
Licenses checked against project READMEs and model cards; re-check
before shipping.

## Candidates

### 1. Kokoro-82M (hexgrad) — recommended

- License: Apache 2.0, code AND weights. Commercial use and
  redistribution of generated audio allowed.
- Quality: best in its weight class; natural narration voices,
  ~50 built-in voices, blendable. No voice cloning (fixed set),
  which sidesteps cloning-consent issues entirely.
- Size/speed: 82M params, ~330MB. Runs on CPU or a small GPU;
  near-instant per line on a Modal T4.
- Modal cost: lowest of the three (small GPU, fast inference).
- Fit: line-by-line narration with fixed narrator voices is
  exactly our shape; cache-by-hash keeps repeat cost at zero.

### 2. Chatterbox Turbo (Resemble AI) — runner-up

- License: MIT, code AND weights. Commercial use and
  redistribution of generated audio allowed.
- Quality: higher expressiveness than Kokoro (emotion control,
  zero-shot cloning — we would not use cloning, fixed narrator
  voice only). Outputs carry an inaudible Perth watermark.
- Size/speed: larger model, needs a GPU (T4/A10 class), slower
  per line than Kokoro.
- Modal cost: moderate.
- Fit: pick this if narration quality matters more than cost;
  the watermark is arguably a plus (marks audio as synthetic).

### 3. Orpheus 3B (Canopy Labs) — most expressive, heaviest

- License: Apache 2.0 code and weights, BUT built on
  Llama-3.2-3B, so the Llama 3.2 Community License also applies
  (acceptable-use policy + attribution; >700M users would need a
  Meta license — irrelevant here).
- Quality: very human-like, emotion tags, zero-shot cloning
  (again, we would use a fixed voice, not cloning).
- Size/speed: 3B params; wants an A10 or better for reasonable
  speed. Slowest and most expensive per line.
- Modal cost: highest of the three.
- Fit: only if we want maximum drama and accept the dual
  license + GPU bill.

## Excluded

- F5-TTS: MIT code but CC-BY-NC-4.0 weights — no commercial use.
- Coqui XTTS v2: CPML weights — commercial restrictions.

## Approved: Kokoro-82M — built 2026-11-01

- `modal/tts.py`: Modal app `reelworld-tts` on CPU (no GPU
  needed, no payment method required), Kokoro weights baked
  into the image. `POST {text, voice, key}`
  returns raw WAV (24kHz mono); key must match the Modal
  secret `reelworld-tts` (`STUDIO_VOICE_KEY`).
- `backend/studio_voice.py`: `speak()` synthesizes each line
  once and caches `data/audio/<hash>.wav` (16-hex sha1 of
  model|voice|text). `POST /api/audio` (guarded, 429 resting;
  misses logged as provider `studio`), `GET /api/audio/{hash}`
  (404 unknown). 501 unconfigured, 502 synthesis failed.
- Player tries the Studio narrator first, falls back to the
  browser voice (Studio option dropped, note updated).
- Exporter fetches all line audios up front and mixes them at
  scene starts (128kbps); silent + honest status on failure.

Deploy (needs the `modal` package + a Modal account with
credits; the key below is yours, never commit it):

```powershell
pip install modal
modal setup
modal secret create reelworld-tts STUDIO_VOICE_KEY=<pick-a-long-random-value>
modal deploy modal/tts.py
```

Then add to `.env` (names only here): `STUDIO_VOICE_URL` (the
`https://…/speak` URL Modal prints) and `STUDIO_VOICE_KEY` (the
same value). Restart the API server. First synthesis per
container is slow (cold start); later lines reuse the warm
container, and every repeat is a cache hit.
