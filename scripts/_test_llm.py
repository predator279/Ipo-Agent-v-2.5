import sys, os, re
sys.path.insert(0, '.')

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

from agents.tools import get_llm, extract_llm_content, GEMINI_MODEL, GROQ_MODEL
print(f"GEMINI_MODEL = {GEMINI_MODEL}")
print(f"GROQ_MODEL   = {GROQ_MODEL}")
print()

llm = get_llm(temperature=0)
print(f"LLM type : {type(llm).__name__}")
print(f"LLM model: {getattr(llm, 'model', getattr(llm, 'model_name', '?'))}")
print()

result = llm.invoke('Reply with exactly: STACK_OK')
raw_content = getattr(result, 'content', str(result))
normalised  = extract_llm_content(result)

print(f"raw content type : {type(raw_content).__name__}")
print(f"normalised string: {repr(normalised)}")
print()

if isinstance(normalised, str) and normalised.strip():
    print("SUCCESS: extract_llm_content works correctly!")
else:
    print("FAIL: normalised content is empty or not a string")
