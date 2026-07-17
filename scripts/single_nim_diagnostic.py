import os, re, requests, time

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

url = "https://integrate.api.nvidia.com/v1/chat/completions"
payload = {
    "model": "meta/llama-3.3-70b-instruct",
    "messages": [{"role": "user", "content": "Reply with just the word CONFIRMED."}],
    "max_tokens": 10,
    "temperature": 0.1,
    "stream": False
}
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Bearer {nvidia_key}"
}

start = time.time()
try:
    response = requests.post(url, json=payload, headers=headers, timeout=90)
    print(f"Status: {response.status_code}")
    print(f"Time: {time.time()-start:.1f}s")
    print(f"Response: {response.text[:200]}")
except requests.exceptions.Timeout:
    print(f"TIMEOUT after {time.time()-start:.1f}s")
except Exception as e:
    print(f"ERROR: {e}")
