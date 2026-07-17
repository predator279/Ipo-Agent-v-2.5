import sys
import os

# Adjust path to import root modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ipo_fetcher import fetch_all_ipo_data_separated
from supabase_client import get_supabase, register_ipo_cached, save_profile

def run_nightly():
    print("Starting Nightly Pre-cacher...")
    sb = get_supabase()
    if not sb:
        print("ERROR: Supabase not configured. Cannot run nightly cache.")
        sys.exit(1)
        
    ipo_dict = fetch_all_ipo_data_separated()
    if not ipo_dict:
        print("No data fetched from NSE. Exiting.")
        return

    # Process Upcoming & Current IPOs
    for status in ["Upcoming", "Current"]:
        df = ipo_dict.get(status)
        if df is None or df.empty:
            continue
            
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
            
            # ---------------------------------------------------------
            # TODO: Implement full agentic pipeline here
            # 1. Download RHP
            # 2. Extract Document Profile
            # 3. Embed into Qdrant Cloud
            # 4. Save to Supabase (ipo_profiles & ipo_cache_registry)
            # ---------------------------------------------------------
            
            # Placeholder for saving
            # save_profile(ipo_name, symbol, {"dummy": "data"})
            # register_ipo_cached(ipo_name, symbol, status, protected=True)
            print(f"[{ipo_name}] Placeholder: Processing successful.")
            
    # TODO: Implement LRU eviction on Qdrant Cloud if capacity > 85%
    # This involves fetching Qdrant storage usage, and if high, deleting
    # embeddings for 'Past' IPOs where protected = False.
    
    print("Nightly Pre-cacher completed successfully.")

if __name__ == "__main__":
    run_nightly()
