-- supabase_schema.sql
-- Run these statements in the Supabase SQL editor (supabase.com → your project → SQL Editor)

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE 1: ipo_cache_registry
-- Tracks what IPOs are stored in Qdrant Cloud + LRU eviction metadata
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ipo_cache_registry (
    ipo_name          TEXT PRIMARY KEY,
    symbol            TEXT,
    status            TEXT,           -- 'current' | 'upcoming' | 'past'
    open_date         DATE,
    close_date        DATE,
    cached_at         TIMESTAMPTZ DEFAULT NOW(),
    last_accessed     TIMESTAMPTZ DEFAULT NOW(),
    access_count      INTEGER DEFAULT 0,
    storage_mb        FLOAT DEFAULT 0,
    protected         BOOLEAN DEFAULT FALSE,  -- TRUE = never evict (live/current IPOs)
    qdrant_collection TEXT
);

-- RPC function to increment access count atomically
CREATE OR REPLACE FUNCTION increment_access(p_ipo_name TEXT)
RETURNS VOID AS $$
BEGIN
    UPDATE ipo_cache_registry
    SET access_count = access_count + 1,
        last_accessed = NOW()
    WHERE ipo_name = p_ipo_name;
END;
$$ LANGUAGE plpgsql;


-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE 2: ipo_profiles
-- Stores extracted IPO profile JSON (replaces local ipo_analysis_cache/ folder)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ipo_profiles (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ipo_name     TEXT UNIQUE NOT NULL,
    symbol       TEXT,
    profile_json JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_updated_at
    BEFORE UPDATE ON ipo_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE 3: ipo_list_cache
-- Short-lived TTL cache for NSE IPO list responses (avoids hammering NSE API)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ipo_list_cache (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status     TEXT,           -- 'current' | 'upcoming' | 'past'
    data_json  JSONB,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups by status + recency
CREATE INDEX IF NOT EXISTS idx_ipo_list_cache_status_fetched
    ON ipo_list_cache (status, fetched_at DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY: Find LRU eviction candidates (run manually when Qdrant near capacity)
-- ─────────────────────────────────────────────────────────────────────────────
-- SELECT ipo_name, last_accessed, storage_mb, access_count
-- FROM ipo_cache_registry
-- WHERE protected = FALSE
--   AND status = 'past'
--   AND last_accessed < NOW() - INTERVAL '30 days'
-- ORDER BY last_accessed ASC
-- LIMIT 5;
--
-- After deleting from Qdrant, remove from registry:
-- DELETE FROM ipo_cache_registry WHERE ipo_name = 'deleted_ipo_name';
