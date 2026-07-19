import os
import sys
import toml

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def _load_secrets():
    try:
        secrets_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                secrets = toml.load(f)
                for k, v in secrets.items():
                    os.environ[k] = str(v)
    except Exception as e:
        print(f"Error loading secrets: {e}")

_load_secrets()

from qdrant_client import QdrantClient
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from supabase_client import get_supabase
from chatbot_agent import _safe_name

def clean_specific_ipo(ipo_name: str):
    print(f"🧹 Cleaning up data for '{ipo_name}'...")
    
    # 1. Clean Supabase
    try:
        sb = get_supabase()
        if sb:
            print("Cleaning Supabase 'ipo_profiles' table...")
            res1 = sb.table("ipo_profiles").delete().eq("ipo_name", ipo_name).execute()
            print(f"Deleted from ipo_profiles: {res1.data}")
            
            print("Cleaning Supabase 'ipo_cache_registry' table...")
            res2 = sb.table("ipo_cache_registry").delete().eq("ipo_name", ipo_name).execute()
            print(f"Deleted from ipo_cache_registry: {res2.data}")
            print("✅ Supabase cleaned.")
    except Exception as e:
        print(f"⚠️ Error cleaning Supabase: {e}")

    # 2. Clean Qdrant
    try:
        q_url = os.environ.get("QDRANT_URL")
        q_key = os.environ.get("QDRANT_API_KEY")
        if q_url and q_key:
            client = QdrantClient(url=q_url, api_key=q_key)
            cname = _safe_name(ipo_name)
            
            # Check if collection exists
            collections = client.get_collections().collections
            exists = any(c.name == cname for c in collections)
            
            if exists:
                print(f"Deleting Qdrant collection: {cname}")
                client.delete_collection(cname)
                print("✅ Qdrant collection deleted.")
            else:
                print(f"ℹ️ Qdrant collection '{cname}' does not exist.")
    except Exception as e:
        print(f"⚠️ Error cleaning Qdrant: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = "Caliber Mining and Logistics Limited"
    clean_specific_ipo(target)
