"""Focused checks for parser backend selection (backend/chat.py).

Covers resolve_parser precedence + chat_kwargs extras: pure env logic,
no model or database. Uses dummy keys only, never the real .env values.
Run from the project root:  python backend/test_parser_env.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat as chat_mod  # noqa: E402  (needs the sys.path line above)

ENV_KEYS = ("PARSER_BASE_URL", "PARSER_KEY_ENV", "PARSER_MODEL",
            "META_API_BASE_URL", "LLAMA_API_BASE",
            "LLAMA_WONDER_MODEL", "META_API_MODEL")
KEYS = ("META_API_KEY", "BASETEN_API_KEY")

saved = {k: os.environ.get(k) for k in ENV_KEYS + KEYS}


def resolve_with(env):
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)
    base, key_env, model = chat_mod.resolve_parser()
    return base, key_env, model, chat_mod.chat_kwargs()


CASES = [
    # (env, want_base, want_key, want_model, want_effort, label)
    ({"META_API_BASE_URL": "https://api.meta.ai/v1",
      "META_API_MODEL": "muse-spark-1.3"},
     "https://api.meta.ai/v1", "META_API_KEY", "muse-spark-1.3", "minimal",
     "meta-model-api"),
    ({"META_API_BASE_URL": "https://api.meta.ai/v1",
      "META_API_MODEL": "muse-spark-1.3",
      "LLAMA_WONDER_MODEL": "Llama-4-Maverick-17B-128E-Instruct"},
     "https://api.meta.ai/v1", "META_API_KEY", "muse-spark-1.3", "minimal",
     "stale-llama-model-loses"),
    ({"PARSER_BASE_URL": "https://api.meta.ai/v1",
      "PARSER_MODEL": "muse-spark-1.3"},
     "https://api.meta.ai/v1", "META_API_KEY", "muse-spark-1.3", "minimal",
     "explicit-meta-picks-meta-key"),
    ({"LLAMA_API_BASE": "https://api.llama.com/compat/v1",
      "LLAMA_WONDER_MODEL": "Llama-4-Maverick-17B-128E-Instruct"},
     "https://api.llama.com/compat/v1", "META_API_KEY",
     "Llama-4-Maverick-17B-128E-Instruct", None,
     "llama-fallback-no-effort"),
    ({},
     "https://inference.baseten.co/v1", "BASETEN_API_KEY",
     "meta-models/muse-spark-open-1026", None,
     "baseten-default"),
]

fails = 0
try:
    for k in KEYS:
        os.environ[k] = "test-dummy"
    for env, base, key_env, model, effort, label in CASES:
        got_base, got_key, got_model, kw = resolve_with(env)
        got_effort = (kw.get("extra_body") or {}).get("reasoning_effort")
        ok = ((got_base, got_key, got_model, got_effort)
              == (base, key_env, model, effort))
        if not ok:
            fails += 1
            print(f"FAIL {label}: got {(got_base, got_key, got_model, got_effort)}")
finally:
    for k in ENV_KEYS + KEYS:
        if saved[k] is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = saved[k]
print(f"test_parser_env.py: {len(CASES) - fails}/{len(CASES)} checks passed")
sys.exit(1 if fails else 0)
