"""
ReelWorld: test the reasoning provider configured in .env.

Uses the same settings as chat.py:
    PARSER_BASE_URL   (default: Baseten)
    PARSER_KEY_ENV    name of the variable that holds the key (default: BASETEN_API_KEY)
    PARSER_MODEL      model name

Run from the project root:
    python backend\\test_parser.py

It prints which provider answered, how long it took, and the reply.
It never prints your key.
"""
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

base = os.getenv("PARSER_BASE_URL", "https://inference.baseten.co/v1")
key_name = os.getenv("PARSER_KEY_ENV", "BASETEN_API_KEY")
model = os.getenv("PARSER_MODEL", "meta-models/muse-spark-open-1026")

if key_name not in os.environ:
    raise SystemExit(f"{key_name} is not set in .env")

client = OpenAI(base_url=base, api_key=os.environ[key_name])
start = time.time()
resp = client.chat.completions.create(
    model=model,
    max_tokens=3000,
    messages=[{"role": "user", "content": "Reply with one short sentence: what is a market?"}],
)
print(f"Provider: {base}")
print(f"Model:    {model}")
print(f"Key from: {key_name}")
print(f"Time:     {time.time() - start:.1f}s")
print(f"Reply:    {resp.choices[0].message.content}")