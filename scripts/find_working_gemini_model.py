"""
scripts/find_working_gemini_model.py
────────────────────────────────────
Probes each Gemini model from your ListModels response and finds the first one
that actually accepts a generateContent request. Prints the winner and updates
GEMINI_MODEL in agents/tools.py automatically.
"""
import sys, os, re, requests

sys.path.insert(0, '.')

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

api_key = secrets.get('GEMINI_API_KEY', os.getenv('GEMINI_API_KEY', ''))
if not api_key:
    print("FAIL: GEMINI_API_KEY not found in secrets.toml")
    sys.exit(1)

print(f"Using key: {api_key[:15]}...\n")

# ── Get live model list ───────────────────────────────────────────────────────
r = requests.get(
    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=100",
    timeout=15
)
if r.status_code != 200:
    print(f"FAIL: ListModels returned {r.status_code}: {r.text[:200]}")
    sys.exit(1)

all_models = [
    m["name"].replace("models/", "")
    for m in r.json().get("models", [])
    if "generateContent" in m.get("supportedGenerationMethods", [])
]

# ── Probe order: prefer stable flash models, avoid image/tts/robotics/preview ─
def score(name):
    """Lower = more preferred."""
    n = name.lower()
    if "tts" in n or "image" in n or "robotics" in n or "computer-use" in n:
        return 999   # skip these — not text LLMs
    if "lyria" in n or "gemma" in n or "antigravity" in n or "deep-research" in n:
        return 998   # skip non-Gemini models
    if "whisper" in n or "omni" in n or "guard" in n:
        return 997

    # prefer newest stable flash
    if name == "gemini-3.5-flash":        return 1
    if name == "gemini-3.1-flash-lite":   return 2
    if name == "gemini-3-flash-preview":  return 3
    if name == "gemini-flash-latest":     return 4
    if name == "gemini-flash-lite-latest":return 5
    if name == "gemini-2.5-flash-lite":   return 6
    if name == "gemini-2.5-pro":          return 7
    if name == "gemini-2.0-flash-lite":   return 8
    if "preview" in name:                 return 50
    if "flash" in n:                      return 30
    if "pro" in n:                        return 40
    return 60

candidates = sorted(
    [m for m in all_models if score(m) < 900],
    key=score
)

print(f"Testing {len(candidates)} models in preference order:\n")

# ── Minimal generateContent probe ────────────────────────────────────────────
def probe(model_id):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_id}:generateContent?key={api_key}"
    )
    payload = {"contents": [{"parts": [{"text": "Reply with one word: OK"}]}]}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            text = (
                resp.json()
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            return True, text
        else:
            err = resp.json().get("error", {})
            return False, f"HTTP {resp.status_code}: {err.get('message','')[:120]}"
    except Exception as e:
        return False, str(e)[:120]


winner = None
for model in candidates:
    print(f"  Testing {model:<50}", end="", flush=True)
    ok, msg = probe(model)
    if ok:
        print(f"  OK  (response: {repr(msg[:30])})")
        winner = model
        break
    else:
        print(f"  FAIL  {msg}")

print()
if not winner:
    print("No working Gemini model found. App will use Groq as primary.")
    sys.exit(0)

print(f"WINNER: {winner}")

# ── Patch agents/tools.py ─────────────────────────────────────────────────────
tools_path = os.path.join('agents', 'tools.py')
with open(tools_path) as f:
    content = f.read()

old_line = next(
    (line for line in content.splitlines() if line.strip().startswith('GEMINI_MODEL')),
    None
)
if old_line:
    new_line = f'GEMINI_MODEL = "{winner}"'
    content = content.replace(old_line, new_line)
    with open(tools_path, 'w') as f:
        f.write(content)
    print(f"\nPatched agents/tools.py:")
    print(f"  Before: {old_line.strip()}")
    print(f"  After:  {new_line}")
else:
    print("WARNING: Could not find GEMINI_MODEL line in agents/tools.py — update it manually.")

print("\nDone. Restart the Streamlit app to apply.")
