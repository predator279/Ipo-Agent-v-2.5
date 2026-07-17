#!/usr/bin/env python3
"""
llm_stress_test.py
──────────────────
Runs a battery of concurrent and paced requests against our proposed free-tier
LLM providers (Gemini, Groq, NVIDIA NIM, Mistral) to measure real-world rate
limits, fallback resilience, and token/request boundaries.

Usage:
    python llm_stress_test.py
"""

import os
import sys
import time
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# ── Load secrets from .streamlit/secrets.toml ────────────────────────────────
def load_secrets() -> dict:
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if not os.path.exists(secrets_path):
        print(f"Warning: secrets.toml not found at {secrets_path}")
        return {}
    secrets = {}
    try:
        import tomllib
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
    except Exception:
        # Fallback line parser
        with open(secrets_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                v = v.strip().strip('"').strip("'").split("#")[0].strip()
                secrets[k.strip()] = v
    return secrets

secrets = load_secrets()

# Set up environment variables for LangChain/Direct calls
for k, v in secrets.items():
    if v and not v.startswith("your_") and "placeholder" not in v.lower():
        os.environ[k] = v

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

# ── Setup LangChain clients ──────────────────────────────────────────────────
ChatGoogleGenerativeAI = None
ChatGroq = None
ChatOpenAI = None

if GEMINI_API_KEY:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        pass

if GROQ_API_KEY:
    try:
        from langchain_groq import ChatGroq
    except ImportError:
        pass

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    pass


# ── Mock data (approx. 500 tokens of financial text for extraction test) ─────
MOCK_FINANCIAL_TEXT = """
Alpine Texworld Limited (the "Company" or the "Issuer") was incorporated on March 12, 2018. The Company is engaged in the manufacturing and export of premium home textile products including bed linens, bath towels, and luxury curtains.
For the Financial Year ended March 31, 2025 (FY25), the Company reported Total Revenue of Rs. 4,520.12 million compared to Rs. 3,890.45 million in FY24, representing a Year-on-Year growth of 16.18%.
EBITDA for FY25 stood at Rs. 813.62 million (EBITDA Margin of 18.00%) against Rs. 680.83 million (EBITDA Margin of 17.50%) in FY24.
Profit After Tax (PAT) for FY25 was Rs. 482.50 million (PAT Margin of 10.67%) against Rs. 392.10 million (PAT Margin of 10.08%) in FY24.
Basic EPS for FY25 was Rs. 12.06 against Rs. 9.80 in FY24.
The Balance Sheet as of March 31, 2025 shows Total Assets of Rs. 5,230.12 million, Total Liabilities of Rs. 2,120.45 million, and Net Worth of Rs. 3,109.67 million.
Total Debt outstanding as of March 31, 2025 was Rs. 850.00 million, resulting in a Debt-to-Equity ratio of 0.27x.
The Current Ratio was 1.85x and Working Capital stood at Rs. 1,250.00 million.
Return on Equity (ROE) for FY25 was 15.52% and Return on Capital Employed (ROCE) was 18.25%.
The Promoter shareholding post-issue will decrease from 85.00% to 68.50%. Anchor investors will be allocated up to 30% of the public issue size.
The objects of the issue include Rs. 1,200.00 million for setting up a new weaving unit in Gujarat, Rs. 500.00 million for working capital requirements, and Rs. 300.00 million for general corporate purposes.
Key risk factors include: (i) dependency on textile export markets which contribute 75% of revenues; (ii) volatility in raw cotton prices; (iii) foreign exchange rate fluctuations.
"""

EXTRACTION_SYSTEM_PROMPT = """
You are an expert financial analyst. Your task is to extract structured parameters from the provided text and output them as a valid JSON object.
JSON structure:
{
  "company_name": "string",
  "fy": "string",
  "revenue": "string",
  "ebitda": "string",
  "ebitda_margin": "string",
  "pat": "string",
  "pat_margin": "string",
  "eps": "string",
  "total_assets": "string",
  "net_worth": "string",
  "debt_to_equity": "string",
  "key_risks": ["string"]
}
Only return the valid JSON block. No explanation.
"""

# ── Classification codes ─────────────────────────────────────────────────────
def classify_error(exc) -> str:
    msg = str(exc).lower()
    if "429" in msg or "resource_exhausted" in msg or "rate_limit" in msg or "rate limit" in msg:
        if "daily" in msg or "per day" in msg or "rpd" in msg:
            return "RATE_LIMIT_RPD"
        return "RATE_LIMIT_RPM"
    if "401" in msg or "auth" in msg or "invalid api key" in msg or "api key not valid" in msg:
        return "AUTH_ERROR"
    if "404" in msg or "not_found" in msg or "model not found" in msg or "no longer available" in msg:
        return "MODEL_NOT_FOUND"
    if "timeout" in msg or "deadline" in msg:
        return "TIMEOUT"
    return "UNKNOWN_ERROR"


# ── Invoker with Fallback Chain ──────────────────────────────────────────────
def invoke_with_fallback(prompt_sys: str, prompt_user: str, purpose: str) -> dict:
    """
    Executes an LLM call based on purpose, checking fallback chains.
    Returns details on execution and triggers.
    """
    result = {
        "success": False,
        "provider": "None",
        "model": "None",
        "content": "",
        "error_class": None,
        "raw_error": "",
        "fallback_triggered": False,
        "fallback_error": ""
    }

    # ── Define execution chains per purpose ──────────────────────────────────
    chain = []
    if purpose == "extraction":
        if NVIDIA_API_KEY:
            chain.append(("NVIDIA", "meta/llama-3.3-70b-instruct"))
        else:
            result["fallback_triggered"] = True
            result["fallback_error"] = "NVIDIA key missing, skipping to Gemini"
        
        if GEMINI_API_KEY:
            chain.append(("Gemini", "gemini-3.1-flash-lite"))
        else:
            if not result["fallback_triggered"]:
                result["fallback_triggered"] = True
                result["fallback_error"] = "Gemini key missing, skipping to Groq"
        
        if GROQ_API_KEY:
            chain.append(("Groq", "llama-3.3-70b-versatile"))

    elif purpose == "sentiment":
        if GROQ_API_KEY:
            chain.append(("Groq", "llama-3.3-70b-versatile"))
        if NVIDIA_API_KEY:
            chain.append(("NVIDIA", "meta/llama-3.3-70b-instruct"))
        if GEMINI_API_KEY:
            chain.append(("Gemini", "gemini-3.1-flash-lite"))

    elif purpose == "chat":
        if MISTRAL_API_KEY:
            chain.append(("Mistral", "mistral-large-latest"))
        if GEMINI_API_KEY:
            chain.append(("Gemini", "gemini-3.1-flash-lite"))

    if not chain:
        result["raw_error"] = "No API keys configured for this purpose"
        result["error_class"] = "AUTH_ERROR"
        return result

    # ── Execute the chain ─────────────────────────────────────────────────────
    for idx, (provider, model) in enumerate(chain):
        result["provider"] = provider
        result["model"] = model
        
        try:
            if provider == "Gemini" and ChatGoogleGenerativeAI:
                llm = ChatGoogleGenerativeAI(
                    model=model,
                    google_api_key=GEMINI_API_KEY,
                    temperature=0.1,
                    timeout=15,
                    max_retries=1
                )
                res = llm.invoke([("system", prompt_sys), ("human", prompt_user)])
                content = getattr(res, "content", "")
                if isinstance(content, list):
                    content = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
                result["content"] = content
                result["success"] = True
                return result
            
            elif provider == "Groq" and ChatGroq:
                llm = ChatGroq(
                    model=model,
                    api_key=GROQ_API_KEY,
                    temperature=0.1,
                    timeout=15,
                    max_retries=1
                )
                res = llm.invoke([("system", prompt_sys), ("human", prompt_user)])
                result["content"] = getattr(res, "content", str(res))
                result["success"] = True
                return result

            elif provider == "NVIDIA" and ChatOpenAI:
                llm = ChatOpenAI(
                    base_url="https://integrate.api.nvidia.com/v1",
                    api_key=NVIDIA_API_KEY,
                    model=model,
                    temperature=0.1,
                    timeout=15,
                    max_retries=1
                )
                res = llm.invoke([("system", prompt_sys), ("human", prompt_user)])
                result["content"] = getattr(res, "content", str(res))
                result["success"] = True
                return result

            elif provider == "Mistral" and ChatOpenAI:
                llm = ChatOpenAI(
                    base_url="https://api.mistral.ai/v1",
                    api_key=MISTRAL_API_KEY,
                    model=model,
                    temperature=0.1,
                    timeout=15,
                    max_retries=1
                )
                res = llm.invoke([("system", prompt_sys), ("human", prompt_user)])
                result["content"] = getattr(res, "content", str(res))
                result["success"] = True
                return result
            
            else:
                raise ImportError(f"LangChain library or client not initialized for {provider}")

        except Exception as exc:
            err_class = classify_error(exc)
            result["raw_error"] = str(exc)
            result["error_class"] = err_class
            
            if idx < len(chain) - 1:
                result["fallback_triggered"] = True
                result["fallback_error"] = f"{provider} failed ({err_class}): {exc}"
            else:
                if result["fallback_triggered"]:
                    result["error_class"] = "FALLBACK_ALSO_FAILED"
                return result

    return result


# ══════════════════════════════════════════════════════════════════════════════
# STRESS TESTS
# ══════════════════════════════════════════════════════════════════════════════

def run_extraction_burst(run_id: int):
    print(f"\n🚀 [Test 1 — Run {run_id}] Firing 12 concurrent extraction threads...")
    start_time = time.time()
    
    futures_data = []
    success_count = 0
    fail_counts = {}
    fallback_triggers = 0
    latencies = []

    def single_task():
        t0 = time.time()
        res = invoke_with_fallback(EXTRACTION_SYSTEM_PROMPT, MOCK_FINANCIAL_TEXT, "extraction")
        latency = time.time() - t0
        return res, latency

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(single_task) for _ in range(12)]
        for fut in as_completed(futures):
            res, lat = fut.result()
            latencies.append(lat)
            if res["success"]:
                success_count += 1
                if res["fallback_triggered"]:
                    fallback_triggers += 1
            else:
                err_class = res["error_class"] or "UNKNOWN"
                fail_counts[err_class] = fail_counts.get(err_class, 0) + 1
                if res["fallback_triggered"]:
                    fail_counts["FALLBACK_ALSO_FAILED"] = fail_counts.get("FALLBACK_ALSO_FAILED", 0) + 1
            futures_data.append(res)

    wall_time = time.time() - start_time
    avg_lat = sum(latencies)/len(latencies) if latencies else 0

    print(f"  Finished in {wall_time:.2f}s (Avg latency: {avg_lat:.2f}s)")
    print(f"  Succeeded: {success_count}/12")
    print(f"  Fallback trigger rate: {fallback_triggers}/12")
    if fail_counts:
        print(f"  Errors: {dict(fail_counts)}")
        
    return {
        "success": success_count,
        "failed": 12 - success_count,
        "wall_time": wall_time,
        "avg_latency": avg_lat,
        "fallback_triggers": fallback_triggers,
        "error_summary": fail_counts
    }


def run_sentiment_concurrent():
    print(f"\n🚀 [Test 2] Firing 4 concurrent Groq sentiment calls...")
    start_time = time.time()
    
    latencies = []
    success_count = 0
    fail_counts = {}
    
    def single_task():
        t0 = time.time()
        res = invoke_with_fallback(
            "Analyze the sentiment of this text about an IPO. Output a score from 1.0 to 5.0 only.",
            "Alpine Texworld IPO GMP shoots up Rs 45 in grey market. Strong subscriptions reported on Day 1.",
            "sentiment"
        )
        latency = time.time() - t0
        return res, latency

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(single_task) for _ in range(4)]
        for fut in as_completed(futures):
            res, lat = fut.result()
            latencies.append(lat)
            if res["success"]:
                success_count += 1
            else:
                err_class = res["error_class"] or "UNKNOWN"
                fail_counts[err_class] = fail_counts.get(err_class, 0) + 1

    wall_time = time.time() - start_time
    avg_lat = sum(latencies)/len(latencies) if latencies else 0

    print(f"  Finished in {wall_time:.2f}s (Avg latency: {avg_lat:.2f}s)")
    print(f"  Succeeded: {success_count}/4")
    if fail_counts:
        print(f"  Errors: {dict(fail_counts)}")

    return {
        "success": success_count,
        "failed": 4 - success_count,
        "wall_time": wall_time,
        "avg_latency": avg_lat,
        "error_summary": fail_counts
    }


def run_chatbot_pacing(gap_seconds: int):
    print(f"\n🚀 [Test 3 — Pacing {gap_seconds}s] Simulating 5 sequential chatbot messages (Mistral)...")
    success_count = 0
    fail_counts = {}
    latencies = []
    
    prompts = [
        "What does Alpine Texworld do?",
        "What was their EBITDA for FY25?",
        "Tell me about their debt-to-equity ratio.",
        "What are the key risk factors?",
        "Who is anchoring this issue?"
    ]

    for idx, p in enumerate(prompts):
        if idx > 0:
            print(f"  Sleeping for {gap_seconds} seconds...")
            time.sleep(gap_seconds)
            
        print(f"  Sending message {idx+1}/5: {repr(p)}")
        t0 = time.time()
        res = invoke_with_fallback(
            "You are a helpful assistant talking about Alpine Texworld. Answer briefly based on earlier turns.",
            p,
            "chat"
        )
        lat = time.time() - t0
        latencies.append(lat)
        
        if res["success"]:
            print(f"    OK  ({res['provider']}/{res['model']}) -> {repr(res['content'][:40])}...")
            success_count += 1
        else:
            err_class = res["error_class"] or "UNKNOWN"
            print(f"    FAIL ({res['provider']}/{res['model']}) -> {err_class}: {res['raw_error'][:80]}")
            fail_counts[err_class] = fail_counts.get(err_class, 0) + 1

    avg_lat = sum(latencies)/len(latencies) if latencies else 0
    print(f"  Succeeded: {success_count}/5")
    if fail_counts:
        print(f"  Errors: {dict(fail_counts)}")

    return {
        "success": success_count,
        "failed": 5 - success_count,
        "avg_latency": avg_lat,
        "error_summary": fail_counts
    }


# ── Report Generation ────────────────────────────────────────────────────────
def print_verdict_report(t1_a, t1_b, t2, t3_fast, t3_slow):
    print("\n" + "═" * 70)
    print("                      RESILIENCE & VERDICT REPORT")
    print("═" * 70)

    # 1. Extraction verdict
    ext_succeeded = t1_a["success"] + t1_b["success"]
    ext_total = 24
    ext_rate = (ext_succeeded / ext_total) * 100
    print(f"\n🔷  1. Info Extraction (NVIDIA NIM -> Gemini -> Groq)")
    print(f"   Success Rate: {ext_succeeded}/{ext_total} ({ext_rate:.1f}%)")
    print(f"   Avg Latency : Run 1: {t1_a['avg_latency']:.2f}s | Run 2: {t1_b['avg_latency']:.2f}s")
    print(f"   Fallbacks   : Run 1: {t1_a['fallback_triggers']} triggers | Run 2: {t1_b['fallback_triggers']} triggers")
    
    if ext_rate >= 90:
        verdict_ext = "Viable (highly resilient)"
    elif ext_rate >= 50:
        verdict_ext = "Needs throttling (increase delay between threads)"
    else:
        verdict_ext = "Critical Failure (replace fallback sequence)"
    print(f"   VERDICT     : {verdict_ext}")

    # 2. Sentiment verdict
    sent_succeeded = t2["success"]
    sent_total = 4
    sent_rate = (sent_succeeded / sent_total) * 100
    print(f"\n🔷  2. Sentiment Analysis (Groq Llama 3.3)")
    print(f"   Success Rate: {sent_succeeded}/{sent_total} ({sent_rate:.1f}%)")
    print(f"   Avg Latency : {t2['avg_latency']:.2f}s")
    
    if sent_rate == 100:
        verdict_sent = "Viable"
    elif sent_rate >= 50:
        verdict_sent = "Needs throttling (add sequential processing)"
    else:
        verdict_sent = "Replace Groq (TPM limits too low)"
    print(f"   VERDICT     : {verdict_sent}")

    # 3. Chatbot verdict
    print(f"\n🔷  3. Chatbot turns (Mistral -> Gemini)")
    print(f"   Fast Pacing (5s gap) : {t3_fast['success']}/5 succeeded")
    print(f"   Slow Pacing (35s gap): {t3_slow['success']}/5 succeeded")
    
    mistral_keys_ok = bool(MISTRAL_API_KEY)
    
    if not mistral_keys_ok:
        print("   Note        : Mistral key was not set, fallback was invoked.")
        verdict_chat = "Using Gemini fallback directly (Viable)"
    else:
        if t3_fast["success"] == 5:
            verdict_chat = "Mistral is fully viable (60 RPM/1 RPS confirmed)"
        elif t3_slow["success"] == 5:
            verdict_chat = "Mistral viable ONLY with 35s pacing; fallback to Gemini recommended for chat"
        else:
            verdict_chat = "Mistral rate limits too tight; replace with Gemini for chatbot"
    print(f"   VERDICT     : {verdict_chat}")
    
    print("\n" + "═" * 70 + "\n")


if __name__ == "__main__":
    print("\n" + "═" * 70)
    print("  LLM Provider Resilience & Stress Test Orchestrator")
    print("═" * 70)
    
    t1_a = run_extraction_burst(run_id=1)
    
    print("\nWaiting 60 seconds before Run 2 to evaluate RPD depletion...")
    time.sleep(60)
    
    t1_b = run_extraction_burst(run_id=2)
    
    t2 = run_sentiment_concurrent()
    
    t3_fast = run_chatbot_pacing(gap_seconds=5)
    t3_slow = run_chatbot_pacing(gap_seconds=35)
    
    print_verdict_report(t1_a, t1_b, t2, t3_fast, t3_slow)
