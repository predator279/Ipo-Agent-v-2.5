import sys
import os
import toml

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def _load_secrets():
    try:
        # Load from streamlit secrets if available
        secrets_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                secrets = toml.load(f)
                for k, v in secrets.items():
                    os.environ[k] = str(v)
            print("Loaded API keys from secrets.toml")
    except Exception as e:
        print(f"Could not load secrets.toml: {e}")

_load_secrets()

# Adjust path to import root modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ipo_fetcher import fetch_all_ipo_data_separated
from supabase_client import get_supabase, register_ipo_cached, save_profile
from chatbot_agent import process_and_store_document
from rhp_agent import analyze_rhp
import time

def run_nightly():
    print("Starting Nightly Pre-cacher...")
    os.environ["STRICT_QDRANT"] = "true"
    sb = get_supabase()
    if not sb:
        print("ERROR: Supabase not configured. Cannot run nightly cache.")
        sys.exit(1)
        
    ipo_dict = fetch_all_ipo_data_separated()
    if not ipo_dict:
        print("No data fetched from NSE. Exiting.")
        return

    # TEST MODE: Process ONLY 1 'Current' IPO
    for status in ["Current"]:
        df = ipo_dict.get(status)
        if df is None or df.empty:
            continue
            
        # Limit to 1 IPO for testing
        df = df.head(1)
            
        print(f"--- Processing {status} IPOs ---")
        for _, row in df.iterrows():
            ipo_name = row.get("_UI_Company_Name") or row.get("Company Name", "Unknown")
            symbol = row.get("_UI_Symbol") or row.get("Symbol", "")
            
            # Check if already in Supabase
            try:
                res = sb.table("ipo_cache_registry").select("*").eq("ipo_name", ipo_name).execute()
                if res.data:
                    print(f"[{ipo_name}] already cached in registry. Skipping.")
                    continue
            except Exception as e:
                print(f"Error checking registry for {ipo_name}: {e}")
                continue
                
            print(f"[{ipo_name}] Not found in cache. Starting processing...")
            
            # 1. Download RHP and Embed into Qdrant Cloud
            vectorstore = None
            try:
                print(f"[{ipo_name}] Embedding into Qdrant...")
                vectorstore = process_and_store_document(ipo_name, symbol=symbol)
            except Exception as e:
                print(f"[{ipo_name}] Failed to embed document: {e}")
                
            if not vectorstore:
                print(f"[{ipo_name}] Embedding failed or returned None. Skipping Supabase caching so it can be retried later.")
                continue
                
            # 2. Extract Document Profile
            try:
                print(f"[{ipo_name}] Extracting Document Profile...")
                profile_dict = analyze_rhp(ipo_name, symbol=symbol)
            except Exception as e:
                print(f"[{ipo_name}] Failed to analyze RHP: {e}")
                profile_dict = None
                
            # 2b. Extract Sentiment Analysis
            if profile_dict:
                try:
                    print(f"[{ipo_name}] Running Sentiment Analysis...")
                    from sentiment_agent import analyze_sentiment
                    sentiment_dict = analyze_sentiment(ipo_name)
                    profile_dict["sentiment"] = sentiment_dict
                except Exception as e:
                    print(f"[{ipo_name}] Failed to run sentiment analysis: {e}")
                
            # 3. Save to Supabase
            if profile_dict:
                save_profile(ipo_name, symbol, profile_dict)
                register_ipo_cached(ipo_name, symbol, status, protected=True)
                print(f"[{ipo_name}] Processing and caching successful.")
            else:
                print(f"[{ipo_name}] Extraction failed, did not save to Supabase.")
                
            # Rate limit the LLM calls slightly to be safe
            time.sleep(2)
            
    # TODO: Implement LRU eviction on Qdrant Cloud if capacity > 85%
    # This involves fetching Qdrant storage usage, and if high, deleting
    # embeddings for 'Past' IPOs where protected = False.
    
    print("Nightly Pre-cacher completed successfully.")

if __name__ == "__main__":
    run_nightly()
