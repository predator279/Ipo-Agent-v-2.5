import sys
import os
import tomllib
import time

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Load Secrets
secrets_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".streamlit", "secrets.toml")
if os.path.exists(secrets_path):
    with open(secrets_path, "rb") as f:
        secrets = tomllib.load(f)
        for k, v in secrets.items():
            if isinstance(v, str):
                os.environ[k] = v
    print("✅ Loaded API keys from secrets.toml")

# Disable Chroma telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Adjust path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chatbot_agent import _get_vectorstore, _safe_name
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from supabase_client import get_supabase, save_profile
from ipo_extractor import extract_ipo_profile, CACHE_DIR
import re

ACTIVE_IPOS = [
    ("Crystal Crop Protection Limited", "CRYSTALCP", "Current"),
    ("Mahanadi Coalfields Limited", "MAHACOAL", "Upcoming"),
    ("Watrana Rentals Limited", "WATRANA", "Upcoming")
]

def run_reextraction():
    print(f"\n🚀 Starting One-Time Re-Extraction for {len(ACTIVE_IPOS)} Active IPOs...")
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    sb = get_supabase()

    for idx, (ipo_name, symbol, status) in enumerate(ACTIVE_IPOS, 1):
        print(f"\n[{idx}/{len(ACTIVE_IPOS)}] Processing '{ipo_name}' ({symbol}) [{status}]...")
        cname = _safe_name(ipo_name)
        
        # 1. Connect to existing vectorstore (NO re-embedding)
        try:
            vectorstore = _get_vectorstore(cname, embeddings, create=False)
            print(f"  ✅ Connected to existing vectorstore ({type(vectorstore).__name__})")
        except Exception as e:
            print(f"  ❌ Could not connect to vectorstore for {ipo_name}: {e}")
            continue

        # 2. Clear old profile cache file so fresh section extraction runs
        safe_cache_name = re.sub(r"[^a-zA-Z0-9_-]", "_", ipo_name)
        cache_file = os.path.join(CACHE_DIR, f"{safe_cache_name}_profile.json")
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
                print(f"  🗑️ Cleared stale local cache file: {cache_file}")
            except Exception as e:
                print(f"  ⚠️ Could not remove stale cache file: {e}")

        # 3. Run new section extraction
        start_time = time.time()
        try:
            profile = extract_ipo_profile(
                vectorstore, ipo_name,
                progress_callback=lambda msg: print(f"    ⏳ {msg}")
            )
            elapsed = time.time() - start_time
            print(f"  ✅ Extracted profile in {elapsed:.1f}s")
        except Exception as e:
            print(f"  ❌ Extraction failed for {ipo_name}: {e}")
            continue

        # 4. Save to Supabase
        if profile and sb:
            try:
                save_profile(ipo_name, symbol, profile)
                print(f"  💾 Successfully updated Supabase 'ipo_profiles' table for {ipo_name}")
            except Exception as e:
                print(f"  ⚠️ Failed to save to Supabase: {e}")

        # Rate limit breather between IPOs
        time.sleep(2.0)

    print("\n🎉 One-Time Re-Extraction Completed Successfully!")

if __name__ == "__main__":
    run_reextraction()
