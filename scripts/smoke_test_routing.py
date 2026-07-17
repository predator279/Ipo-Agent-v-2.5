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

from agents.tools import get_llm, extract_llm_content

print("========================================")
print("  Smoke Test: LLM Workload Routing Split")
print("========================================")

# 1. Extraction (Mistral Small)
print("\nTesting: purpose='extraction' (Primary: Mistral Small)")
try:
    llm = get_llm(purpose="extraction", temperature=0)
    print(f"  Class: {type(llm).__name__}")
    print(f"  Model: {getattr(llm, 'model_name', getattr(llm, 'model', '?'))}")
    res = llm.invoke("Say exactly MISTRAL_OK")
    print(f"  Content: {repr(extract_llm_content(res))}")
except Exception as e:
    print(f"  Error: {e}")

# 2. Sentiment (Groq Llama 3.3)
print("\nTesting: purpose='sentiment' (Primary: Groq Llama 3.3)")
try:
    llm = get_llm(purpose="sentiment", temperature=0)
    print(f"  Class: {type(llm).__name__}")
    print(f"  Model: {getattr(llm, 'model_name', getattr(llm, 'model', '?'))}")
    res = llm.invoke("Say exactly GROQ_OK")
    print(f"  Content: {repr(extract_llm_content(res))}")
except Exception as e:
    print(f"  Error: {e}")

# 3. Chatbot (Gemini 3.1 Flash-Lite)
print("\nTesting: purpose='chat' (Primary: Gemini 3.1 Flash-Lite)")
try:
    llm = get_llm(purpose="chat", temperature=0.1)
    print(f"  Class: {type(llm).__name__}")
    print(f"  Model: {getattr(llm, 'model_name', getattr(llm, 'model', '?'))}")
    res = llm.invoke("Say exactly GEMINI_OK")
    print(f"  Content: {repr(extract_llm_content(res))}")
except Exception as e:
    print(f"  Error: {e}")

print("\nSmoke Test Done!")
print("========================================")
