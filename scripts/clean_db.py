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



def clean_all():
    print("🧹 Cleaning up old data...")
    
    # 1. Clean Supabase
    try:
        sb = get_supabase()
        if sb:
            print("Cleaning Supabase 'ipo_profiles' table...")
            # We can't do a mass delete without a filter, so we delete where ipo_name is not null (which is everything)
            sb.table("ipo_profiles").delete().neq("ipo_name", "THIS_WILL_NEVER_MATCH").execute()
            
            print("Cleaning Supabase 'ipo_cache_registry' table...")
            sb.table("ipo_cache_registry").delete().neq("ipo_name", "THIS_WILL_NEVER_MATCH").execute()
            print("✅ Supabase wiped.")
    except Exception as e:
        print(f"⚠️ Error cleaning Supabase: {e}")

    # 2. Clean Qdrant
    try:
        q_url = os.environ.get("QDRANT_URL")
        q_key = os.environ.get("QDRANT_API_KEY")
        if q_url and q_key:
            client = QdrantClient(url=q_url, api_key=q_key)
            collections = client.get_collections().collections
            for c in collections:
                print(f"Deleting Qdrant collection: {c.name}")
                client.delete_collection(c.name)
            print("✅ Qdrant wiped.")
    except Exception as e:
        print(f"⚠️ Error cleaning Qdrant: {e}")

if __name__ == "__main__":
    clean_all()
