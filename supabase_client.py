# supabase_client.py
"""
Supabase client helpers for the IPO Analysis Agent.
Provides:
  - get_supabase()           → singleton client (None if not configured)
  - get_cached_profile()     → fetch extracted IPO profile JSON
  - save_profile()           → upsert IPO profile JSON
  - update_last_accessed()   → bump access count + timestamp in registry

Tables used (create via Supabase SQL editor):
  ipo_cache_registry  — what IPOs are in Qdrant, with LRU eviction metadata
  ipo_profiles        — extracted profile JSON (replaces ipo_analysis_cache/ folder)
  ipo_list_cache      — TTL cache for NSE IPO lists

Graceful degradation: if SUPABASE_URL/KEY are missing, all functions return None
and the app falls back to local file cache.
"""

import os

try:
    from supabase import create_client, Client as SupabaseClient
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    SupabaseClient = None

_client = None


def get_supabase():
    """Returns a singleton Supabase client, or None if not configured."""
    global _client
    if _client is not None:
        return _client

    if not SUPABASE_AVAILABLE:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None  # graceful — fall back to local cache

    try:
        _client = create_client(url, key)
    except Exception as exc:
        print(f"[supabase_client] Failed to create client: {exc}")
        return None

    return _client


def get_cached_profile(ipo_name: str) -> dict | None:
    """
    Fetches the extracted IPO profile JSON from the ipo_profiles table.
    Returns the profile dict, or None if not found / Supabase not configured.
    """
    sb = get_supabase()
    if not sb:
        return None
    try:
        res = (
            sb.table("ipo_profiles")
            .select("profile_json")
            .eq("ipo_name", ipo_name)
            .execute()
        )
        if res.data:
            return res.data[0]["profile_json"]
    except Exception as exc:
        print(f"[supabase_client] get_cached_profile({ipo_name}) failed: {exc}")
    return None


def save_profile(ipo_name: str, symbol: str, profile_dict: dict) -> None:
    """
    Upserts the extracted IPO profile JSON into the ipo_profiles table.
    No-op if Supabase is not configured.
    """
    sb = get_supabase()
    if not sb:
        return
    try:
        sb.table("ipo_profiles").upsert({
            "ipo_name":    ipo_name,
            "symbol":      symbol,
            "profile_json": profile_dict,
            "updated_at":  "NOW()",
        }, on_conflict="ipo_name").execute()
    except Exception as exc:
        print(f"[supabase_client] save_profile({ipo_name}) failed: {exc}")


def update_last_accessed(ipo_name: str) -> None:
    """
    Increments access_count and updates last_accessed in ipo_cache_registry.
    Requires a Supabase RPC function 'increment_access'.
    No-op if Supabase is not configured or RPC not found.
    """
    sb = get_supabase()
    if not sb:
        return
    try:
        sb.rpc("increment_access", {"p_ipo_name": ipo_name}).execute()
    except Exception as exc:
        print(f"[supabase_client] update_last_accessed({ipo_name}) failed: {exc}")


def register_ipo_cached(
    ipo_name: str,
    symbol: str,
    status: str,
    protected: bool = False,
    qdrant_collection: str = "",
    nse_metadata: dict = None,
) -> None:
    """
    Registers an IPO in ipo_cache_registry after it has been cached in Qdrant.
    No-op if Supabase is not configured.
    """
    sb = get_supabase()
    if not sb:
        return
    try:
        payload = {
            "ipo_name":          ipo_name,
            "symbol":            symbol,
            "status":            status,
            "protected":         protected,
            "qdrant_collection": qdrant_collection or ipo_name.replace(" ", "_"),
        }
        if nse_metadata is not None:
            payload["nse_metadata"] = nse_metadata
            
        sb.table("ipo_cache_registry").upsert(payload, on_conflict="ipo_name").execute()
    except Exception as exc:
        print(f"[supabase_client] register_ipo_cached({ipo_name}) failed: {exc}")
