#!/usr/bin/env python3
"""
scripts/retest_nvidia_mistral.py
─────────────────────────────────
Retests NVIDIA Developer NIM and Mistral APIs using sequential execution with
pacing gaps. Measures latency, success rate, and rate limits.
"""

import os
import sys
import time
import re
import requests

# ── Load secrets ─────────────────────────────────────────────────────────────
secrets = {}
with open('.streamlit/secrets.toml') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^(\w+)\s*=\s*"([^"]+)"', line)
        if m:
            secrets[m.group(1)] = m.group(2)

nvidia_key = secrets.get("NVIDIA_API_KEY", "")
mistral_key = secrets.get("MISTRAL_API_KEY", "")

# ── Mock Financial Text (~500 tokens) ─────────────────────────────────────────
MOCK_TEXT = """
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

EXTRACTION_PROMPT = """
Extract the following parameter values from the text as valid JSON:
{
  "company_name": "string",
  "revenue_fy25": "string",
  "ebitda_fy25": "string",
  "pat_fy25": "string",
  "net_worth": "string",
  "key_risks": []
}
Output only JSON.
"""

# ── Retest Test 1 — NVIDIA NIM sequential with 2s gap ────────────────────────
def test_nvidia():
    print("\n" + "="*70)
    print("TEST 1: NVIDIA Developer NIM Sequential Retest (12 prompts, 2s gap)")
    print("="*70)
    
    if not nvidia_key:
        print("FAIL: NVIDIA_API_KEY not found in secrets.")
        return
    
    # Try different model ID formats if the first fails
    model_candidates = [
        "meta/llama-3.3-70b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "meta/llama-3.1-70b-instruct"
    ]
    
    # Pick the model to run the full test on (warmup test)
    active_model = model_candidates[0]
    print(f"Warmup call using model: {active_model}...")
    
    warmup_headers = {"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"}
    warmup_payload = {
        "model": active_model,
        "messages": [{"role": "user", "content": "say warmup ok"}],
        "max_tokens": 10
    }
    
    try:
        w_start = time.time()
        w_res = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            json=warmup_payload,
            headers=warmup_headers,
            timeout=25
        )
        w_lat = time.time() - w_start
        print(f"Warmup status: {w_res.status_code} | Latency: {w_lat:.2f}s")
        if w_res.status_code != 200:
            print(f"Warmup Failed: {w_res.text[:300]}")
            print("Trying fallback model format...")
            for alt_model in model_candidates[1:]:
                print(f"Trying warmup with: {alt_model}...")
                warmup_payload["model"] = alt_model
                w_res = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    json=warmup_payload,
                    headers=warmup_headers,
                    timeout=25
                )
                if w_res.status_code == 200:
                    active_model = alt_model
                    print(f"Success! Swapping active model to: {active_model}")
                    break
            else:
                print("All NVIDIA model warmup tests failed. Proceeding with Meta model anyway.")
    except Exception as e:
        print(f"Warmup Connection Error: {e}")
        print("Proceeding to sequential test...")

    print(f"\nStarting sequence of 12 requests using model: {active_model}...")
    start_time = time.time()
    successes = 0
    errors = []
    latencies = []

    for i in range(12):
        if i > 0:
            time.sleep(2.0) # 2-second gap
            
        print(f"  Request {i+1}/12...", end="", flush=True)
        
        headers = {"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"}
        payload = {
            "model": active_model,
            "messages": [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": MOCK_TEXT}
            ],
            "temperature": 0.1
        }
        
        t0 = time.time()
        try:
            # Fresh HTTP request per request (timeout=60)
            r = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60
            )
            lat = time.time() - t0
            latencies.append(lat)
            
            if r.status_code == 200:
                print(f"  OK   (latency: {lat:.2f}s)")
                successes += 1
            else:
                print(f"  FAIL (status: {r.status_code}, latency: {lat:.2f}s)")
                errors.append(f"Req {i+1} status {r.status_code}: {r.text[:150]}")
        except Exception as e:
            lat = time.time() - t0
            latencies.append(lat)
            print(f"  EXC  (latency: {lat:.2f}s) -> {e}")
            errors.append(f"Req {i+1} exception: {str(e)[:150]}")

    wall_time = time.time() - start_time
    avg_lat = sum(latencies)/len(latencies) if latencies else 0
    print(f"\nNVIDIA Test Finished!")
    print(f"  Successes: {successes}/12")
    print(f"  Total wall time: {wall_time:.2f}s (Avg latency: {avg_lat:.2f}s)")
    if errors:
        print("  Errors experienced:")
        for err in errors:
            print(f"    - {err}")
            
    return successes


# ── Retest Test 2 — Mistral sequential extraction ────────────────────────────
def test_mistral(model_id: str):
    print("\n" + "="*70)
    print(f"TEST 2: Mistral Sequential Extraction ({model_id}, 12 prompts, 2s gap)")
    print("="*70)
    
    if not mistral_key:
        print("FAIL: MISTRAL_API_KEY not found in secrets.")
        return
        
    start_time = time.time()
    successes = 0
    errors = []
    latencies = []

    for i in range(12):
        if i > 0:
            time.sleep(2.0) # 2-second gap (safe inside 1 RPS)
            
        print(f"  Request {i+1}/12...", end="", flush=True)
        
        headers = {"Authorization": f"Bearer {mistral_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": MOCK_TEXT}
            ],
            "temperature": 0.1
        }
        
        t0 = time.time()
        try:
            # Fresh client call (timeout=60)
            r = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60
            )
            lat = time.time() - t0
            latencies.append(lat)
            
            if r.status_code == 200:
                print(f"  OK   (latency: {lat:.2f}s)")
                successes += 1
            else:
                print(f"  FAIL (status: {r.status_code}, latency: {lat:.2f}s)")
                errors.append(f"Req {i+1} status {r.status_code}: {r.text[:150]}")
        except Exception as e:
            lat = time.time() - t0
            latencies.append(lat)
            print(f"  EXC  (latency: {lat:.2f}s) -> {e}")
            errors.append(f"Req {i+1} exception: {str(e)[:150]}")

    wall_time = time.time() - start_time
    avg_lat = sum(latencies)/len(latencies) if latencies else 0
    print(f"\nMistral ({model_id}) Test Finished!")
    print(f"  Successes: {successes}/12")
    print(f"  Total wall time: {wall_time:.2f}s (Avg latency: {avg_lat:.2f}s)")
    if errors:
        print("  Errors experienced:")
        for err in errors:
            print(f"    - {err}")
            
    return successes


if __name__ == "__main__":
    test_nvidia()
    
    # Mistral checks (Large and Small)
    test_mistral("mistral-large-latest")
    test_mistral("mistral-small-latest")
