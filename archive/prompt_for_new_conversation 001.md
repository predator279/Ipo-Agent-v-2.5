# IPO Analysis Agent — Master Execution Prompt

> **Instructions for the AI Agent:** Please read the following project context, finalized architectural decisions, and the highly detailed, phased implementation plan. Your goal is to execute this plan step-by-step. Let's begin with Phase 1. Do not proceed to subsequent phases until the current phase is fully implemented and verified.

---

## 1. Project Context
I am building an AI-powered Indian IPO research platform in Python + Streamlit.
**Current workflow:** Downloads RHP/DRHP PDFs → chunks + embeds into ChromaDB → parallel RAG extraction of 40+ structured fields → multi-source sentiment analysis → conversational chatbot.
**Codebase location:** `c:\Users\MANISH\Desktop\IPO project 200\`

**Problems to solve:**
1. RHP fetching is fragile (misses IPOs, relies on a flaky scraper).
2. The UI dropdown is not time-sorted.
3. Users must provide their own API keys, which is bad UX.
4. PDF chunking is too slow (10+ mins for large RHPs).
5. ChromaDB is local-only, preventing effective caching in cloud deployments.

---

## 2. Finalized Architectural Decisions (Approved)

1. **LLM Strategy**: We are using **Gemini 2.0 Flash** as the primary LLM (generous free tier, 1500 req/day) and **Groq `llama-3.3-70b-versatile`** as the fallback. Both keys will be securely stored server-side. We are completely removing the API key input fields from the UI.
2. **Data Ingestion Waterfall**: Fetch IPO data and RHP links in this priority: **Upstox API** (Primary) → **NSE `/api/ipo-detail`** → **NSE Archives Zip URL** → **SEBI Scraper** (Fallback).
3. **Chunking Optimization**: We will not use a hard page cap. We will use **PyMuPDF to scan the Table of Contents (TOC)** in the first 30 pages to locate critical sections (Financials, Risks, etc.). We will process only those relevant pages. We will run `pdfplumber` ONLY on pages flagged as having tables to drastically reduce processing time from 10-12 mins to ~2-3 mins.
4. **Vector Database & Caching**: We will use **Qdrant Cloud (1GB Free Tier)** as the production vector store instead of local ChromaDB (which gets wiped in cloud deployments). We will use **Supabase PostgreSQL (Free Tier)** for a cache registry table (`ipo_cache_registry`) and storing extracted JSON profiles (`ipo_profiles`).
5. **Nightly Pre-caching**: A **GitHub Actions Cron Job** will run every night at 2:00 AM IST. It will fetch new current/upcoming IPOs, process their RHPs, cache them in Qdrant/Supabase, and perform LRU (Least Recently Used) eviction of old past IPOs if storage exceeds 85%.
6. **Deployment**: We will deploy Phase 1 to **Streamlit Community Cloud** (100% free). Phase 2 can migrate to **Azure App Service** using student credits.

---

## 3. Execution Guide (Phase by Phase)

### Phase 1: Core Architecture & Data Ingestion (Local)

#### 1A. `agents/tools.py` — LLM Waterfall
**Goal**: Remove user key dependencies. Use server-side keys.
**Code Implementation**:
```python
import os
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI = None
from langchain_groq import ChatGroq

def get_llm(model_name=None, provider=None, temperature=0.25, **kwargs):
    """
    Waterfall: Gemini 2.0 Flash → Groq llama-3.3-70b
    Keys come from environment only — never from user input.
    """
    # 1st: Try Gemini 2.0 Flash
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key and ChatGoogleGenerativeAI:
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=gemini_key,
            temperature=temperature,
        )

    # 2nd: Try Groq
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=groq_key,
            temperature=temperature,
        )

    raise RuntimeError("No LLM available. Set GEMINI_API_KEY or GROQ_API_KEY in environment.")
```
**Action**: Update `chatbot_agent.py` and `ipo_extractor.py` to use `get_llm()` instead of hardcoded `ChatGroq`.

#### 1B. `app.py` — Remove API Key UI + Fix Dropdown
**Goal**: No key input in sidebar. Time-sorted dropdown with status badges.
**Action**:
1. Remove the entire `with st.expander("🔑 API Keys", ...)` block.
2. Load keys silently using `st.secrets` falling back to `os.environ`.
3. **Dropdown Logic Update**:
```python
# Time-sorted dropdown from unified IPO fetcher
all_ipos = []
for status, emoji, df_key in [
    ("current", "🔥", "df_Current"),
    ("upcoming", "⏳", "df_Upcoming"),
    ("past", "✅", "df_Past"),
]:
    df = st.session_state.get(df_key, pd.DataFrame())
    if not df.empty and "Company Name" in df.columns:
        date_col = "Start Date" if "Start Date" in df.columns else None
        for _, row in df.iterrows():
            name = row["Company Name"]
            date_str = f" {row[date_col]}" if date_col and pd.notna(row.get(date_col)) else ""
            label = f"[{emoji} {status.upper()}{date_str}] {name}"
            all_ipos.append({"label": label, "name": name, "symbol": row.get("Symbol","")})

options = ["--- Type manually ---"] + [x["label"] for x in all_ipos]
selected = st.selectbox("Choose an IPO:", options)
```

#### 1C. `ipo_fetcher.py` — Upstox + NSE Unified Data
**Goal**: Fetch from Upstox API as primary, NSE endpoints as fallback. Create a unified schema.
**Action**:
1. Add `fetch_upstox_ipos()` which hits public Upstox market data endpoints for IPO details and direct RHP links.
2. Add `fetch_nse_ipo_detail(symbol)` for `/api/ipo-detail?symbol={symbol}&series=EQ`.
3. Update `fetch_all_ipo_data_separated()` to merge and standardize columns: `[Company Name, Symbol, Status, Start Date, End Date, Price Band, Issue Size, RHP URL, Source]`.

#### 1D. `rhp_agent.py` — RHP Download Waterfall
**Goal**: Drop `ipopremium.in`. Implement robust waterfall.
**Implementation details**:
1. **Upstox**: Try to use direct RHP link if provided by `fetch_upstox_ipos()`.
2. **NSE Zip**: Try direct URL `https://nsearchives.nseindia.com/content/ipo/RHP_{symbol}.zip`. Implement `_extract_zip_pdfs()` to unzip and extract the largest PDF (>2MB).
3. **NSE Detail**: Use `fetch_nse_ipo_detail(symbol)`, parse `issueInfo.dataList` for "Red Herring Prospectus" URL.
4. **SEBI Scraper**: Keep existing logic as fallback.

---

### Phase 2: Chunking Speed Optimization

#### 2A. `document_processor.py` — Smart TOC Detection
**Goal**: Content-aware selection instead of a hard page cap. PyMuPDF-first dual-pass.
**Implementation details**:
```python
TARGET_SECTIONS = {
    "business overview": "business",
    "risk factors": "risks",
    "financial statements": "financials",
    "objects of the issue": "objects",
    "management discussion": "mgmt",
    "basis of allotment": "allotment",
}

def _detect_toc_sections(mupdf_pdf):
    # Fast pass: scan first 30 pages with PyMuPDF for TOC matching TARGET_SECTIONS
    # Returns mapping of section to page number
    pass

def _get_pages_to_process(mupdf_pdf, toc_sections):
    # Returns set of pages to process, adding a +/- 20 page buffer around sections
    pass

# Dual-Pass Architecture in process_pdf_with_pdfplumber:
# Pass 1: For each page in pages_to_process, use PyMuPDF to extract text and heuristic flag 'has_table'
# Pass 2: ONLY for pages where has_table=True, use pdfplumber to extract markdown tables
```
**Action**: Implement this architecture and wire up a granular progress callback to Streamlit.

#### 2B. `chatbot_agent.py` — Embedding Batch Size & Qdrant
**Goal**: Increase embedding speed by 30-40% and add cloud DB support.
**Action**:
1. Change `batch_size = 64` to `batch_size = 256` for embedding insertion.
2. Initialize embeddings explicitly:
   ```python
   embeddings = HuggingFaceEmbeddings(
       model_name=EMBEDDING_MODEL,
       encode_kwargs={"batch_size": 256, "normalize_embeddings": True},
       model_kwargs={"device": "cpu"}
   )
   ```
3. Implement Qdrant support (`pip install langchain-qdrant qdrant-client`). If `USE_QDRANT=true`, initialize `QdrantVectorStore`. Otherwise, fallback to local `Chroma`.

---

### Phase 3: Cloud Caching & Pre-Caching Scheduler

#### 3A. Supabase Setup (`supabase_client.py`)
**Goal**: Persistent metadata and profile cache.
**Action**: Create a client (`pip install supabase`) to interact with:
1. `ipo_cache_registry`: Track what's stored in Qdrant (columns: `ipo_name, symbol, status, cached_at, last_accessed, storage_mb, protected`).
2. `ipo_profiles`: Stores the final RAG-extracted JSON (replaces local `ipo_analysis_cache/`).

#### 3B. GitHub Actions Nightly Pre-Cacher
**Goal**: Pre-cache current/upcoming IPOs at 2:00 AM IST and run LRU eviction.
**Implementation Details**:
1. Create `scripts/nightly_precache.py`:
   - Fetch current/upcoming IPOs.
   - If not in `ipo_cache_registry`, download RHP → chunk → embed to Qdrant → save profile to Supabase.
   - Mark `protected=TRUE` for Current IPOs.
   - Storage Check: If Qdrant > 85% full, execute LRU eviction (delete oldest 'Past' IPOs from Qdrant where `protected=FALSE` and update registry).
2. Create `.github/workflows/nightly_precache.yml`:
   - Cron trigger: `30 20 * * *`.
   - Uses GitHub repository secrets.

---

### Phase 4: Deployment

1. **`requirements.txt`**: Generate pinned requirements including `streamlit`, `langchain-google-genai`, `qdrant-client`, `supabase`, `PyMuPDF`, etc.
2. **Streamlit Community Cloud**:
   - Push to public GitHub repo.
   - Deploy via share.streamlit.io.
   - Configure secrets (`st.secrets`) in the cloud dashboard. Set `USE_QDRANT=true`.

---
**Agent Instruction**: Please acknowledge these instructions and begin execution strictly following Phase 1. Start by modifying `agents/tools.py`. Do not move to the next file until the previous one is fully implemented and tested.
