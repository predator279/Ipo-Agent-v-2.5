#!/usr/bin/env python3
"""
scripts/check_llm_keys.py
─────────────────────────
Validates API keys and lists available models for each provider.
Run this BEFORE starting the Streamlit app to confirm your keys work.

Usage:
    python scripts/check_llm_keys.py

Keys are read from .streamlit/secrets.toml (same as the app).
"""

import os
import sys
import json
import requests
from pathlib import Path

# ── Load secrets.toml ────────────────────────────────────────────────────────
SECRETS_PATH = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"

def load_secrets() -> dict:
    if not SECRETS_PATH.exists():
        print(f"Warning: secrets.toml not found at {SECRETS_PATH}")
        return {}
    try:
        import tomllib          # stdlib in Python 3.11+
        with open(SECRETS_PATH, "rb") as f:
            return tomllib.load(f)
    except (ModuleNotFoundError, ImportError):
        pass
    try:
        import tomli            # pip install tomli  (Python < 3.11)
        with open(SECRETS_PATH, "rb") as f:
            return tomli.load(f)
    except (ModuleNotFoundError, ImportError):
        pass
    # Last resort: simple line parser (no dependencies)
    secrets = {}
    with open(SECRETS_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'").split("#")[0].strip()
            secrets[k.strip()] = v
    return secrets


secrets = load_secrets()

def s(key):
    return secrets.get(key, os.getenv(key, ""))

GEMINI_KEY  = s("GEMINI_API_KEY")
GROQ_KEY    = s("GROQ_API_KEY")
NVIDIA_KEY  = s("NVIDIA_API_KEY")
MISTRAL_KEY = s("MISTRAL_API_KEY")

SEP  = "─" * 62
SEP2 = "═" * 62


def is_placeholder(key):
    return not key or key.startswith("your_") or "placeholder" in key.lower()


# ════════════════════════════════════════════════════════════════
# GEMINI
# ════════════════════════════════════════════════════════════════

def check_gemini(api_key):
    print(f"\n{SEP}")
    print("GEMINI  (Google AI Studio)")
    print(SEP)

    if is_placeholder(api_key):
        print("  SKIP  GEMINI_API_KEY is missing or placeholder.")
        print("        Get a free key at: https://aistudio.google.com/apikey")
        return

    if api_key.startswith("ya29."):
        print(f"  FAIL  GEMINI_API_KEY is a short-lived OAuth token (ya29.).")
        print("        Get a persistent API key at https://aistudio.google.com/apikey")
        return

    print(f"  Key prefix: {api_key[:12]}...  [format OK]")
    print("  Calling ListModels...")

    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models"
            f"?key={api_key}&pageSize=100",
            timeout=15,
        )
    except Exception as exc:
        print(f"  FAIL  Network error: {exc}")
        return

    if r.status_code != 200:
        print(f"  FAIL  API returned HTTP {r.status_code}")
        try:
            err = r.json()["error"]
            print(f"        {err.get('status')}: {err.get('message')}")
        except Exception:
            print(f"        {r.text[:300]}")
        return

    data  = r.json()
    models = data.get("models", [])

    generative = [
        m for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    print(f"  OK    Key valid!  {len(generative)} generative models found:\n")

    for m in sorted(generative, key=lambda x: x["name"]):
        name = m["name"].replace("models/", "")
        dname = m.get("displayName", name)
        print(f"    {name:<50}  ({dname})")

    # Pick best available flash-lite or flash model (lite is better for extraction rate limits)
    lite = sorted([
        m["name"].replace("models/", "")
        for m in generative
        if "flash-lite" in m["name"].lower() and "preview" not in m["name"].lower()
    ])
    flash = sorted([
        m["name"].replace("models/", "")
        for m in generative
        if "flash" in m["name"].lower() and "lite" not in m["name"].lower() and "preview" not in m["name"].lower()
    ])

    if lite:
        best = lite[-1]
        print(f"\n  RECOMMENDED FOR EXTRACTION: Set GEMINI_MODEL = \"{best}\" (30 RPM, 250K TPM free)")
    elif flash:
        best = flash[-1]
        print(f"\n  RECOMMENDED FOR EXTRACTION: Set GEMINI_MODEL = \"{best}\" (15 RPM free)")


# ════════════════════════════════════════════════════════════════
# GROQ
# ════════════════════════════════════════════════════════════════

def check_groq(api_key):
    print(f"\n{SEP}")
    print("GROQ")
    print(SEP)

    if is_placeholder(api_key):
        print("  SKIP  GROQ_API_KEY is missing or placeholder.")
        print("        Get a free key at: https://console.groq.com/keys")
        return

    if not api_key.startswith("gsk_"):
        print(f"  WARN  GROQ_API_KEY has unexpected format (expected gsk_...): {api_key[:10]}...")

    print(f"  Key prefix: {api_key[:12]}...")
    print("  Calling /v1/models...")

    try:
        r = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": "Bearer " + api_key},
            timeout=10,
        )
    except Exception as exc:
        print(f"  FAIL  Network error: {exc}")
        return

    if r.status_code != 200:
        print(f"  FAIL  API returned HTTP {r.status_code}")
        print(f"        {r.text[:300]}")
        return

    models = sorted(
        [m for m in r.json().get("data", [])],
        key=lambda x: x.get("id", "")
    )
    print(f"  OK    Key valid!  {len(models)} models found:\n")
    for m in models:
        print(f"    {m.get('id')}")

    # Pick best llama 70b
    llama70 = sorted([
        m["id"] for m in models
        if "llama" in m.get("id","").lower() and "70b" in m.get("id","").lower()
    ])
    if llama70:
        best = llama70[-1]
        print(f"\n  RECOMMENDED FOR SENTIMENT: Set GROQ_MODEL = \"{best}\" (30 RPM free, 12K TPM limit)")


# ════════════════════════════════════════════════════════════════
# NVIDIA NIM
# ════════════════════════════════════════════════════════════════

def check_nvidia(api_key):
    print(f"\n{SEP}")
    print("NVIDIA Developer NIM API")
    print(SEP)

    if is_placeholder(api_key):
        print("  SKIP  NVIDIA_API_KEY is missing or placeholder.")
        print("        Get a free developer key at: https://build.nvidia.com")
        return

    if not api_key.startswith("nvapi-"):
        print(f"  WARN  NVIDIA_API_KEY has unexpected format (expected nvapi-...): {api_key[:10]}...")

    print(f"  Key prefix: {api_key[:12]}...")
    print("  Calling /v1/models...")

    try:
        r = requests.get(
            "https://integrate.api.nvidia.com/v1/models",
            headers={"Authorization": "Bearer " + api_key},
            timeout=10,
        )
    except Exception as exc:
        print(f"  FAIL  Network error: {exc}")
        return

    if r.status_code != 200:
        print(f"  FAIL  API returned HTTP {r.status_code}")
        print(f"        {r.text[:300]}")
        return

    models = sorted(
        [m for m in r.json().get("data", [])],
        key=lambda x: x.get("id", "")
    )
    generative = [
        m for m in models
        if "meta/llama" in m.get("id", "").lower() or "nvidia/" in m.get("id", "").lower() or "deepseek" in m.get("id", "").lower()
    ]
    print(f"  OK    Key valid!  {len(generative)} relevant generative models found (subset of {len(models)} total):\n")
    for m in generative[:30]:  # print first 30 to avoid flooding
        print(f"    {m.get('id')}")
    if len(generative) > 30:
        print(f"    ... and {len(generative) - 30} more models.")

    # Recommend Meta/Llama 3.3 70b or Nemotron 70b
    rec = "meta/llama-3.3-70b-instruct"
    print(f"\n  RECOMMENDED FOR EXTRACTION: Use Model \"{rec}\" (40 RPM free, high context)")


# ════════════════════════════════════════════════════════════════
# MISTRAL AI
# ════════════════════════════════════════════════════════════════

def check_mistral(api_key):
    print(f"\n{SEP}")
    print("MISTRAL AI (La Plateforme)")
    print(SEP)

    if is_placeholder(api_key):
        print("  SKIP  MISTRAL_API_KEY is missing or placeholder.")
        print("        Get a free key at: https://console.mistral.ai")
        return

    print(f"  Key prefix: {api_key[:12]}...")
    print("  Calling /v1/models...")

    try:
        r = requests.get(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": "Bearer " + api_key},
            timeout=10,
        )
    except Exception as exc:
        print(f"  FAIL  Network error: {exc}")
        return

    if r.status_code != 200:
        print(f"  FAIL  API returned HTTP {r.status_code}")
        print(f"        {r.text[:300]}")
        return

    models = sorted(
        [m for m in r.json().get("data", [])],
        key=lambda x: x.get("id", "")
    )
    print(f"  OK    Key valid!  {len(models)} models found:\n")
    for m in models:
        print(f"    {m.get('id')}")

    # Recommend Mistral Large or Small
    large = [m["id"] for m in models if "large" in m["id"].lower()]
    if large:
        print(f"\n  RECOMMENDED FOR CHATBOT: Use Model \"{large[-1]}\" (1 RPS / 60 RPM free, high quality)")


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{SEP2}")
    print("  IPO Analyzer — LLM Key Diagnostic")
    print(SEP2)
    print(f"  Reading from: {SECRETS_PATH.resolve()}")
    print(f"  GEMINI_API_KEY:  {'yes' if GEMINI_KEY else 'NO'}")
    print(f"  GROQ_API_KEY:    {'yes' if GROQ_KEY else 'NO'}")
    print(f"  NVIDIA_API_KEY:  {'yes' if NVIDIA_KEY else 'NO'}")
    print(f"  MISTRAL_API_KEY: {'yes' if MISTRAL_KEY else 'NO'}")

    check_gemini(GEMINI_KEY)
    check_groq(GROQ_KEY)
    check_nvidia(NVIDIA_KEY)
    check_mistral(MISTRAL_KEY)

    print(f"\n{SEP2}")
    print("  After updating keys/model names, re-run this script to confirm.")
    print(SEP2 + "\n")

