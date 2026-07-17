import os, sys, re
sys.path.insert(0, '.')

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

for k, v in secrets.items():
    if v and not v.startswith('your_') and 'placeholder' not in v.lower():
        os.environ[k] = v

from langchain_openai import ChatOpenAI

print("Testing Mistral ChatOpenAI...")
try:
    llm = ChatOpenAI(
        base_url="https://api.mistral.ai/v1",
        api_key=os.environ.get("MISTRAL_API_KEY", ""),
        model="mistral-large-latest",
        temperature=0.1,
        timeout=10,
        max_retries=1
    )
    res = llm.invoke("Say exactly MISTRAL_OK")
    print("Mistral Success:", res.content)
except Exception as e:
    print("Mistral Error:", e)

print("\nTesting NVIDIA ChatOpenAI...")
try:
    llm = ChatOpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.environ.get("NVIDIA_API_KEY", ""),
        model="meta/llama-3.3-70b-instruct",
        temperature=0.1,
        timeout=10,
        max_retries=1
    )
    res = llm.invoke("Say exactly NVIDIA_OK")
    print("NVIDIA Success:", res.content)
except Exception as e:
    print("NVIDIA Error:", e)
