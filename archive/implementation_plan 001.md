# IPO Analysis Agent — Complete Upgrade & Deployment Plan

> Based on deep-read of your codebase: `app.py`, `ipo_fetcher.py`, `rhp_agent.py`,
> `document_processor.py`, `chatbot_agent.py`, `agents/tools.py`, `ipo_extractor.py`, `sentiment_agent.py`

> **Status**: Decisions made — LLM = Gemini 2.0 Flash primary + Groq llama-3.3-70b fallback.
> Chunking details being refined (see Section 4). Vector DB decision = Qdrant Cloud.

---

## 1. Data Ingestion Overhaul

### Current Problem
- `rhp_agent.py` uses `ipopremium.in` (fragile HTML scrape with a 4-digit code hack) + SEBI (slow, misses many filings)
- `ipo_fetcher.py` only uses NSE — no fallback — and NSE rate-limits aggressively in server environments

### Proposed Source Priority (waterfall)

| Priority | Source | What it gives | How |
|----------|--------|---------------|-----|
| 1st | **Upstox API** | IPO list + details + direct RHP PDF link | REST API (no login for public data endpoints) |
| 2nd | **NSE `/api/ipo-detail?symbol=X&series=EQ`** | `issueInfo.dataList` with RHP zip URL | Needs NSE session cookie trick |
| 3rd | **NSE archives zip** `nsearchives.nseindia.com/content/ipo/RHP_<SYMBOL>.zip` | Full RHP + other docs in a zip | Download & extract |
| 4th | **SEBI scraper** (existing) | Fallback for older IPOs | Keep as-is |

### Changes to `ipo_fetcher.py`

```
NEW: fetch_upstox_ipos()         — calls Upstox public IPO list
NEW: fetch_nse_ipo_detail()      — /api/ipo-detail?symbol=X&series=EQ
MODIFY: fetch_all_ipo_data_separated()  — merge all sources, standardize columns
NEW: UNIFIED_COLUMNS schema      — one standard schema regardless of source
```

**Unified Column Schema (standardized across Upstox + NSE):**
```
Company Name | Symbol | Status | Open Date | Close Date | Price Band |
Issue Size (Cr) | Lot Size | Exchange | Series | RHP URL | Source
```

The UI table will use this schema — each row shows which source it came from.

### Changes to `rhp_agent.py`

```
NEW: _try_upstox_rhp_link()     — get direct PDF/zip URL from Upstox IPO detail
NEW: _try_nse_rhp_zip()         — download nsearchives zip, extract PDF
NEW: _try_nse_ipo_detail_rhp()  — hit /api/ipo-detail, parse issueInfo.dataList for RHP link
MODIFY: find_and_download_all_pdfs()  — run waterfall: Upstox → NSE zip → NSE detail → SEBI
NEW: _extract_zip_pdfs()        — unzip the NSE archive, pick largest PDF
```

> [!IMPORTANT]
> Upstox requires OAuth for trading endpoints, but their **market data / IPO listing endpoints are public** (no auth). Confirm this with the Upstox v2 API docs before implementation. If auth is required, we fall straight to NSE.

---

## 2. Dropdown — Time-Sensitive, NSE/Upstox-Powered

### Current Problem
- `app.py` L148–160: dropdown builds from cached `df_Current/Upcoming/Past` in session state, populated SEBI-style names with no date ordering

### Fix (in `app.py` sidebar section)

```python
# Order: Current (open today) → Upcoming (soonest open date first) → Past (most recent first)
# Label format: "[🔥 LIVE] CompanyName" | "[⏳ Upcoming 15-Jul] CompanyName" | "[✅ Past] CompanyName"
```

- Pull names from the **unified fetcher** (Upstox + NSE merged)
- Tag each with its category badge and date
- Sort: Current first → Upcoming sorted by open date ascending → Past sorted by listing date descending
- Symbol/series extracted alongside company name so it can be passed directly to `/api/ipo-detail`

---

## 3. LLM Provider — Killing the User API Key Requirement

### My Recommendation: **Backend API Key with Groq (Free Tier)**

**Option A — Groq (My top pick)**
- Groq free tier: **14,400 requests/day**, `llama-3.3-70b-versatile` at 6000 TPM
- For your use case (structured extraction = ~11 parallel calls per IPO analysis), you'd hit ~600–800 tokens per call = well within limits
- **You embed your own Groq key in the server environment** (not exposed to users)
- Users never see or enter API keys

**Option B — Google Gemini API (your question)**
- Google's terms allow using Gemini API in your own product (3rd-party apps are allowed)
- `gemini-2.0-flash` has a **generous free tier**: 1M tokens/min, 1500 req/day free
- Risk: if the app goes viral, you blow through the free tier fast
- `langchain-google-genai` integrates cleanly

**Option C — OpenRouter with model fallback**
- Lets you route across many free models (Mistral, Qwen, DeepSeek, etc.)
- Free tier models can be slow/unreliable
- Good as a secondary fallback

> [!IMPORTANT]
> **My recommendation**: Use **Gemini 2.0 Flash** as primary (free, your own project, 1500 req/day) with **Groq llama-3.3-70b** as fallback (also free, better for structured JSON extraction). Both keys stay **server-side only** — never ask users. Remove the API key UI entirely from the sidebar.

### Changes to `agents/tools.py`
```python
# Priority order in get_llm():
# 1. GEMINI_API_KEY (env) → langchain-google-genai ChatGoogleGenerativeAI
# 2. GROQ_API_KEY (env)   → ChatGroq (current)
# 3. OPENROUTER_API_KEY   → ChatOpenAI with openrouter base
# Raise error if none available
```

### Changes to `app.py`
- Remove the entire "🔑 API Keys" expander from sidebar
- Load keys from `st.secrets` (Streamlit Cloud) or env vars (Azure/Render)
- Tavily key stays server-side too

---

## 4. Chunking Speed — From 10–12 min → ~2 min

Here's where the time actually goes in your current pipeline:

| Step | Time (1000-page PDF) | Root Cause |
|------|---------------------|------------|
| `pdfplumber.extract_tables()` on every page | ~5–7 min | pdfplumber is slow — it does layout analysis on each page even when there are no tables |
| `all-MiniLM-L6-v2` embedding ~8000 chunks | ~3–4 min | Small batch size (64) means thousands of forward passes through the model |
| PDF download (25–50 MB) | ~1–2 min | Already handled with streaming resume |

---

### ✅ Fix A — Smart TOC-based Section Detection (REVISED from hard page cap)

> **You are right to be skeptical of the 400-page cap.** A 1400-page RHP will have financial statements on pages 900–1200. A hard cap would silently miss everything important. Here's the correct approach:

**Strategy: Parse the Table of Contents first, then only process relevant sections.**

Almost every RHP has a TOC in the first 10–20 pages. We can detect it with PyMuPDF (fast) and extract page ranges for sections we care about:

```
Section detection targets:
  - "Business Overview"         → usually pages 80–150
  - "Risk Factors"              → usually pages 150–250  
  - "Financial Statements"      → can be pages 800–1200 in long RHPs
  - "Objects of the Issue"      → early-mid section
  - "Management Discussion"     → mid section
  - "Basis of Allotment"        → near end
```

**Implementation plan for `document_processor.py`:**
```python
# Step 1: Fast full-document scan with PyMuPDF only (~10 seconds for 1200 pages)
#         → Build a page_index: {page_num: section_tag}
#         → Parse TOC from first 25 pages to get section → page range map
# Step 2: Process ONLY pages that fall in important sections
#         → Typically ~300–500 pages even for a 1200-page RHP
# Step 3: On those selected pages, run pdfplumber for table extraction
# Fallback: If TOC detection fails → fall back to current full-doc approach
#           with a UI warning "Full scan mode (slower)"
```

This is smarter than a page cap — it's **content-aware selection**. For a 1200-page RHP, you end up processing ~350–450 pages instead of 900 (current cap) or all 1200.

We also add **a real-time progress bar** in Streamlit showing:
- `"Scanning TOC... (page 3/15)"`
- `"Found 6 key sections spanning 420 pages"`
- `"Parsing page 312/420 — Financial Statements"`
- `"Embedding 6,240 chunks... (batch 12/49)"`

---

### ✅ Fix B — PyMuPDF-first, pdfplumber only for flagged pages

Your current code opens **both** `pdfplumber` and `fitz` (PyMuPDF) for every single page, but calls `pdfplumber.extract_tables()` on all of them. pdfplumber's table detection does heavy layout analysis even on pages that have zero tables (text-only narrative pages).

**The fix:**
```
Pass 1 — PyMuPDF (fast, ~10s for 1000 pages):
  For every page in selected sections:
    → extract raw text (fitz.get_text)
    → check if it looks like it has a table (heuristic: lots of | or whitespace columns)
    → tag page as has_table=True/False

Pass 2 — pdfplumber (slow, only on has_table=True pages):
    → run extract_tables() on maybe 20–30% of pages
    → convert to markdown, store as TABLE chunks

Result: pdfplumber runs on ~200 pages instead of ~900 → ~65% time saving on the table pass.
```

Progress bar is wired to these passes separately so the user sees exactly what's happening.

---

### ✅ Fix C — Vector DB Cache: ChromaDB vs pgvector vs Pinecone vs Qdrant

> **Your question: If we already use ChromaDB, why switch? And what's the industry standard?**

**Why ChromaDB alone fails in cloud deployment:**
ChromaDB stores its files locally on disk (`ipo_vectorstores/` folder). When you deploy to Streamlit Cloud or Azure App Service, **every app restart wipes the disk** (ephemeral filesystem). So a user who analyzed LASERPOWER IPO yesterday gets a 10-minute wait again today, defeating the whole cache idea.

**The options (all free tiers):**

| DB | Free Tier | Best For | Our Fit |
|----|-----------|----------|---------|
| **ChromaDB** (local) | Unlimited (local disk) | Local dev | ✅ Dev only, ❌ Production |
| **Supabase pgvector** | 500 MB database | SQL + vectors in one place | ⚠️ OK for small scale |
| **Pinecone Serverless** | 2 GB free (Starter) | Industry standard, cloud-native | ✅ Good |
| **Qdrant Cloud** | **1 GB free** (no credit card) | Purpose-built vector DB, fast | ✅✅ **Best for us** |
| **Weaviate Cloud** | 14-day trial only | Large scale | ❌ Not free long-term |

**What Pinecone is:** Pinecone is the most well-known managed vector database — used by companies like Notion, Shopify, etc. It's excellent but the free tier is 1 index only and was recently changed to "Serverless" pricing.

**My recommendation: Qdrant Cloud**
- Free forever (1 GB, no credit card needed)
- Built specifically for vector search (not a bolt-on like pgvector)
- Has a `langchain-qdrant` integration so 10-line swap from ChromaDB
- 1 GB holds approximately **15–20 fully indexed IPO vectorstores** (each IPO = ~50–80 MB)
- When an IPO is already in Qdrant, load time = <2 seconds instead of 10 minutes

**Plan:**
```
Local dev  → ChromaDB (unchanged, works perfectly)
Production → Qdrant Cloud (drop-in swap via LangChain)
```

The `chatbot_agent.py` change is minimal:
```python
# From:
from langchain_chroma import Chroma
vectorstore = Chroma(persist_directory=..., embedding_function=embeddings)

# To (production only, env-flag controlled):
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
vectorstore = QdrantVectorStore(client=client, collection_name=ipo_name, embedding=embeddings)
```

Same LangChain interface — `vectorstore.similarity_search()` works identically.

---

### ✅ Fix D — Embedding Batch Size (Explained in Detail)

**What's happening now:**
Your `chatbot_agent.py` L152 loops through chunks in batches of 64:
```python
batch_size = 64
for i in range(0, total_chunks, batch_size):
    batch = all_docs[i : i + 64]
    vectorstore.add_documents(documents=batch)
```

For a 1000-page RHP with ~8,000 chunks, this means **125 separate calls** to ChromaDB's `add_documents()`, each of which:
1. Calls `HuggingFaceEmbeddings.embed_documents()` for 64 chunks
2. The embedding model processes those 64 texts through `all-MiniLM-L6-v2` (a neural network)
3. Writes the 64 vectors + metadata to ChromaDB
4. Repeat 124 more times

**The problem:** Each `embed_documents()` call has Python overhead — loading the batch, calling the tokenizer, running inference. With 125 calls, that overhead multiplies.

**The fix — batch_size = 256:**
```python
batch_size = 256  # was 64
```
Now you have ~31 calls instead of 125. The model processes 256 texts at once, which is much more efficient because:
- The tokenizer processes a full batch in one shot
- The transformer model runs one forward pass over 256 inputs (GPUs/CPUs are optimized for this)
- ChromaDB insert overhead happens 4x less

**Also:** Explicitly set the encoding batch size in the embedding model:
```python
embeddings = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL,
    encode_kwargs={"batch_size": 64, "normalize_embeddings": True},
    model_kwargs={"device": "cpu"}
)
```

**Expected speedup: 30–40% faster embedding phase.** Not as dramatic as Fix A or Fix B, but it compounds.

---

### ✅ Fix E — FAISS vs ChromaDB (Explained in Detail)

**What FAISS is:**
FAISS (Facebook AI Similarity Search) is a library for fast approximate nearest neighbor (ANN) search in high-dimensional spaces. It's what powers similarity search at massive scale (Meta uses it for billions of vectors).

**ChromaDB vs FAISS — how they differ:**

| | ChromaDB | FAISS |
|--|----------|-------|
| Storage | Persistent (disk) | In-memory only* |
| Search speed | Medium | Very fast (10–100x) |
| Insert speed | Slower (write-to-disk) | Fast (in-memory) |
| Metadata filtering | ✅ Built-in | ❌ Manual |
| Cloud-hosted | ❌ Self-host only | ❌ In-memory only |
| LangChain support | ✅ `langchain-chroma` | ✅ `langchain-community` |
| Best for | Persistent local store | Fast session-level search |

*FAISS can save/load from disk with `faiss.write_index()` but it's manual.

**Why FAISS is faster:** ChromaDB writes to SQLite under the hood for each `add_documents()`. FAISS just builds an in-memory index structure — no disk I/O, no database transactions.

**The actual bottleneck in your app** is NOT ChromaDB search speed (searching is fast even in ChromaDB). The bottleneck is:
1. Embedding 8,000 chunks through `all-MiniLM-L6-v2` (neural network inference)
2. pdfplumber running on every page

So FAISS doesn't solve the real problem — it would only make the `vectorstore.similarity_search()` call faster, which currently takes ~0.5 seconds and is NOT your 10-minute bottleneck.

**My recommendation: Skip FAISS.** It adds complexity without solving the actual slow parts. Fix A + Fix B + Fix C (Qdrant cache) give you 80% of the speed improvement with far less complexity.

---

### Speed Summary After All Fixes

| Fix | Time Saved | Complexity |
|-----|-----------|------------|
| Fix A — Smart TOC section detection | ~4–5 min | Medium |
| Fix B — PyMuPDF-first, pdfplumber selective | ~2–3 min | Low-Medium |
| Fix C — Qdrant Cloud cache (2nd+ loads) | ~9 min (10min→<5sec) | Medium |
| Fix D — Larger embedding batch (256) | ~1 min | Very Low |
| Fix E — FAISS | ~0 min (wrong bottleneck) | Skip |

**Target: First-time analysis: ~2–3 min. Repeat analysis: <5 seconds.**

---

## 5. Deployment Architecture

### Recommended Stack

```
┌────────────────────────────────────────────────────────────────┐
│                    FRONTEND / APP LAYER                        │
│                    Streamlit (app.py)                          │
│          Deployed on: Azure App Service (Free / B1)            │
│          or Streamlit Community Cloud (free, easiest)          │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ calls
                              ▼
┌────────────────────────────────────────────────────────────────┐
│                    BACKEND API LAYER  (NEW)                    │
│                    FastAPI (api/main.py)                        │
│  Endpoints:                                                    │
│   POST /analyze/{ipo_name}  → triggers full pipeline           │
│   GET  /ipos/list           → returns unified IPO list         │
│   GET  /ipos/cached         → list IPOs already in DB cache    │
│  Deployed on: Azure App Service (same or separate)             │
└────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
┌───────────────────────┐    ┌──────────────────────────────┐
│  Supabase (Free tier) │    │  Azure Blob Storage (Free)   │
│  - pgvector           │    │  - Downloaded PDFs/zips      │
│    (vectorstore)      │    │  - Keeps PDFs off the app    │
│  - ipo_profiles table │    │    server                    │
│    (analysis cache)   │    └──────────────────────────────┘
│  - ipo_list table     │
│    (live market data) │
└───────────────────────┘
```

### Platform Comparison

| Platform | Cost | Pros | Cons |
|----------|------|------|------|
| **Streamlit Community Cloud** | Free | Zero config, 1-click deploy from GitHub | 1 GB RAM limit, sleeps on idle, no background workers |
| **Render.com** | Free → $7/mo | Easy Docker, persistent disks, no sleep on paid | Cold starts on free tier |
| **Azure App Service** (Student Pack) | Free w/ $100 credit | Your existing credit, scales well | More config needed |
| **Railway.app** | $5/mo | Easiest Docker deploy, persistent storage | Cost |

> [!IMPORTANT]
> **My recommendation for you right now**: Start with **Streamlit Community Cloud** for immediate free deployment (just push to GitHub, link repo). Then migrate to **Azure App Service + Supabase** once the architecture is solidified. The Student Pack gives you $100 Azure credit — use it for the App Service after the initial public release.

### FastAPI Backend (new `api/` folder)
- Needed because Streamlit can't handle long background jobs (10+ min PDF processing) well
- FastAPI will expose `/analyze` as a background task with SSE (Server-Sent Events) for progress
- Streamlit frontend polls or listens to SSE for progress updates
- This also enables future React/Next.js frontend swap

---

## 6. Supabase Integration

### Tables to create

```sql
-- Stores extracted IPO analysis (replaces ipo_analysis_cache/ folder)
CREATE TABLE ipo_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ipo_name TEXT UNIQUE NOT NULL,
  symbol TEXT,
  profile_json JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Stores IPO list from NSE/Upstox (replaces live fetching each time)
CREATE TABLE ipo_list (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name TEXT NOT NULL,
  symbol TEXT,
  status TEXT,  -- 'current' | 'upcoming' | 'past'
  open_date DATE,
  close_date DATE,
  price_band TEXT,
  issue_size TEXT,
  rhp_url TEXT,
  source TEXT,  -- 'upstox' | 'nse' | 'sebi'
  fetched_at TIMESTAMPTZ DEFAULT NOW()
);

-- pgvector extension for vectorstore (replaces local ChromaDB)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE ipo_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ipo_name TEXT NOT NULL,
  page_number INT,
  chunk_type TEXT,  -- 'text' | 'table'
  content TEXT,
  embedding VECTOR(384),  -- all-MiniLM-L6-v2 = 384 dims
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON ipo_chunks USING ivfflat (embedding vector_cosine_ops);
```

---

## 7. Execution Order (Phased Plan)

### Phase 1 — Local Improvements (do first, ~2-3 days)
- [ ] Fix data ingestion: add NSE `/api/ipo-detail` + NSE archives zip fallback (no Upstox for now)
- [ ] Fix dropdown: time-sorted, labeled with status badge
- [ ] Fix chunking speed: max_pages=400 default + PyMuPDF-first approach
- [ ] Remove user API key requirement: embed keys server-side via `secrets.toml`
- [ ] Add Gemini 2.0 Flash support to `agents/tools.py`
- [ ] Increase embedding batch size to 256

### Phase 2 — Architecture (local, ~2-3 days)
- [ ] Create `api/main.py` — FastAPI wrapper for the pipeline
- [ ] Add Supabase client to project
- [ ] Store/retrieve `ipo_profiles` from Supabase (replaces `ipo_analysis_cache/`)
- [ ] Store/retrieve IPO list from Supabase `ipo_list` table (with 1hr TTL refresh)
- [ ] Migrate vectorstore to Supabase pgvector (or keep ChromaDB locally for now)

### Phase 3 — Deploy (Streamlit Cloud first, then Azure)
- [ ] Create `requirements.txt` pinned versions
- [ ] Create `Dockerfile` for Azure deploy
- [ ] Set all secrets in Streamlit Cloud / Azure App Service environment
- [ ] Deploy to Streamlit Community Cloud (GitHub push → done)
- [ ] Test, then deploy to Azure App Service using Student Pack credits

---


> [!IMPORTANT]
> **Q5 — Azure vs Streamlit Cloud**: Do you want to go directly to Azure (using your student credit) or start with Streamlit Community Cloud (zero config, free, but 1 GB RAM which might be tight for sentence-transformers)?

---

## 9. What We Are NOT Changing (Yet)

- `ipo_extractor.py` — the parallel extraction logic is solid, keep as-is
- `sentiment_agent.py` — Tavily + Reddit + Google News pipeline works well
- `chatbot_agent.py` — hybrid BM25 + ChromaDB RAG is good, only increase batch size
- Overall Streamlit UI layout — UI redesign is Phase 4 (your point 5)
