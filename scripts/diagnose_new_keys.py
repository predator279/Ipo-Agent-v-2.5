import os, requests, re

# Load secrets
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

print("=== NVIDIA NIM KEY TEST ===")
if nvidia_key:
    headers = {"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"}
    payload = {
        "model": "meta/llama-3.3-70b-instruct",
        "messages": [{"role": "user", "content": "say OK"}],
        "max_tokens": 10
    }
    try:
        r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions", json=payload, headers=headers, timeout=10)
        print("NVIDIA Status:", r.status_code)
        print("NVIDIA Response:", r.text[:300])
    except Exception as e:
        print("NVIDIA Connection Error:", e)
else:
    print("NVIDIA key not set")

print("\n=== MISTRAL KEY TEST ===")
if mistral_key:
    headers = {"Authorization": f"Bearer {mistral_key}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-small-latest",
        "messages": [{"role": "user", "content": "say OK"}],
        "max_tokens": 10
    }
    try:
        r = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers, timeout=10)
        print("Mistral Status:", r.status_code)
        print("Mistral Response:", r.text[:300])
    except Exception as e:
        print("Mistral Connection Error:", e)
else:
    print("Mistral key not set")
