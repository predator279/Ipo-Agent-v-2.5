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
import pandas as pd

def _inject_metrics(profile, row, status):
    if "No of Shares Offered" in row and pd.notnull(row["No of Shares Offered"]):
        profile["issue_size"] = str(row["No of Shares Offered"])
    elif "ISSUE SIZE" in row and pd.notnull(row["ISSUE SIZE"]):
        profile["issue_size"] = str(row["ISSUE SIZE"])
        
    if "issuePrice" in row and pd.notnull(row["issuePrice"]):
        profile["price_band"] = str(row["issuePrice"])
    elif "Issue Price" in row and pd.notnull(row["Issue Price"]):
        profile["price_band"] = str(row["Issue Price"])
    elif "Price Range" in row and pd.notnull(row["Price Range"]):
        profile["price_band"] = str(row["Price Range"])
        
    profile["exchange"] = "NSE"
    return profile

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

    # TEST MODE: Process ONLY 1 IPO from each category
    for nse_status in ["Upcoming", "Current", "Past"]:
        df = ipo_dict.get(nse_status)
        if df is None or df.empty:
            continue
            
        # Limit to 1 IPO for testing
        df = df.head(1)
            
        print(f"--- Processing {nse_status} IPOs ---")
        for _, row in df.iterrows():
            ipo_name = row.get("_UI_Company_Name") or row.get("Company Name", "Unknown")
            symbol = row.get("_UI_Symbol") or row.get("Symbol", "")
            
            try:
                res = sb.table("ipo_cache_registry").select("*").eq("ipo_name", ipo_name).execute()
                if res.data:
                    cached_record = res.data[0]
                    db_status = cached_record.get("status")
                    protected = cached_record.get("protected", False)
                    q_col = cached_record.get("qdrant_collection", "")
                    db_meta = cached_record.get("nse_metadata")
                    
                    if db_status == "Past" and nse_status in ["Current", "Upcoming"]:
                        print(f"[{ipo_name}] ANOMALY: DB says Past, but NSE says {nse_status}. Skipping auto-reopen.")
                        continue
                        
                    if db_status == "Past" and nse_status == "Past":
                        if not db_meta:
                            print(f"[{ipo_name}] Backfilling missing nse_metadata for Past IPO.")
                            nse_meta = row.fillna("").to_dict()
                            register_ipo_cached(ipo_name, symbol, nse_status, protected=protected, qdrant_collection=q_col, nse_metadata=nse_meta)
                        else:
                            print(f"[{ipo_name}] Already finalized (Past). Skipping entirely.")
                        continue
                    
                    # Always update registry for Current/Upcoming to catch status changes OR live metric updates
                    print(f"[{ipo_name}] Syncing latest NSE metadata to registry...")
                    nse_meta = row.fillna("").to_dict()
                    register_ipo_cached(ipo_name, symbol, nse_status, protected=protected, qdrant_collection=q_col, nse_metadata=nse_meta)
                        
                    if nse_status in ["Current", "Upcoming"]:
                        print(f"[{ipo_name}] Refreshing sentiment analysis for active IPO...")
                        try:
                            from sentiment_agent import analyze_sentiment
                            from supabase_client import get_cached_profile
                            new_sentiment = analyze_sentiment(ipo_name)
                            profile = get_cached_profile(ipo_name)
                            if profile:
                                profile["sentiment"] = new_sentiment
                                _inject_metrics(profile, row, nse_status)
                                save_profile(ipo_name, symbol, profile)
                                print(f"[{ipo_name}] Sentiment and metrics refreshed successfully.")
                        except Exception as e:
                            print(f"[{ipo_name}] Failed to refresh sentiment: {e}")
                            
                    continue
            except Exception as e:
                print(f"Error checking registry for {ipo_name}: {e}")
                continue
                
            if nse_status == "Past":
                print(f"[{ipo_name}] Missing Past IPO. Creating lightweight metadata record only.")
                profile = _inject_metrics({}, row, nse_status)
                profile["company_overview"] = "Historical IPO data. Detailed analysis skipped."
                save_profile(ipo_name, symbol, profile)
                nse_meta = row.fillna("").to_dict()
                register_ipo_cached(ipo_name, symbol, nse_status, protected=True, nse_metadata=nse_meta)
                continue
                
            print(f"[{ipo_name}] Not found in cache. Starting full load processing...")
            
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
                from ipo_extractor import extract_ipo_profile
                profile_dict = extract_ipo_profile(vectorstore, ipo_name)
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
                profile_dict = _inject_metrics(profile_dict, row, nse_status)
                save_profile(ipo_name, symbol, profile_dict)
                nse_meta = row.fillna("").to_dict()
                register_ipo_cached(ipo_name, symbol, nse_status, protected=True, nse_metadata=nse_meta)
                print(f"[{ipo_name}] Processing and caching successful.")
            else:
                print(f"[{ipo_name}] Extraction failed, did not save to Supabase.")
                
            # Rate limit the LLM calls slightly to be safe
            time.sleep(2)
            
    print("Running LRU eviction check...")
    evict_old_ipos(sb, limit=30)
    print("Nightly Pre-cacher completed successfully.")

def evict_old_ipos(sb, limit=30):
    try:
        res = sb.table("ipo_cache_registry").select("*").execute()
        if not res.data or len(res.data) <= limit:
            return
            
        print(f"Cache size ({len(res.data)}) exceeds limit ({limit}). Evicting old Past IPOs...")
        past_ipos = [r for r in res.data if r.get("status") == "Past" and not r.get("protected")]
        past_ipos.sort(key=lambda x: x.get("last_accessed") or x.get("updated_at") or "")
        
        num_to_delete = len(res.data) - limit
        to_delete = past_ipos[:num_to_delete]
        
        if not to_delete:
            print("No unprotected Past IPOs available to evict.")
            return
            
        from qdrant_client import QdrantClient
        qdrant_url = os.environ.get("QDRANT_URL")
        qdrant_api_key = os.environ.get("QDRANT_API_KEY")
        client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key) if qdrant_url and qdrant_api_key else None
            
        for ipo in to_delete:
            name = ipo["ipo_name"]
            col = ipo.get("qdrant_collection")
            print(f"Evicting [{name}]...")
            if client and col:
                try:
                    client.delete_collection(col)
                except Exception as e:
                    print(f"  Failed to delete Qdrant collection {col}: {e}")
            sb.table("ipo_profiles").delete().eq("ipo_name", name).execute()
            sb.table("ipo_cache_registry").delete().eq("ipo_name", name).execute()
            print(f"  Successfully evicted {name}.")
    except Exception as e:
        print(f"Error during LRU eviction: {e}")

if __name__ == "__main__":
    run_nightly()
