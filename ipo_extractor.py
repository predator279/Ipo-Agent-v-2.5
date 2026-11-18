# ipo_extractor.py
import os
import json
import re
import time
from typing import Optional, List, Dict, Any
from datetime import datetime

from langchain_chroma import Chroma
from langchain_core.messages import SystemMessage, HumanMessage
from langchain.tools import tool

from agents.tools import get_llm, classify_llm_error, extract_llm_content
from sentiment_agent import _fetch_tavily, analyze_sentiment

# ── config ────────────────────────────────────────────────────────────────────
EXTRACTION_K          = 8
CACHE_DIR             = "ipo_analysis_cache"
# ─────────────────────────────────────────────────────────────────────────────

# Globals for tool context
_current_vs = None
_current_ipo_name = None


class IPOProfile(dict):
    """
    Attribute-accessible dictionary for backward compatibility with app.py
    and dictionary-based consumers (API, frontend, scripts).
    """
    def __getattr__(self, item):
        return self.get(item)

    def __setattr__(self, key, value):
        self[key] = value


@tool
def tavily_web_search(query: str) -> str:
    """Search the web via Tavily for missing IPO details like lot size, market cap, or peer financials."""
    time.sleep(1.0)
    try:
        results = _fetch_tavily(query, max_results=3)
        return json.dumps(results)
    except Exception as e:
        return f"Search failed: {e}"


@tool
def vectorstore_search(query: str) -> str:
    """Search the official RHP document (Red Herring Prospectus) for specific details."""
    global _current_vs
    if not _current_vs:
        return "No document loaded."
    docs = _current_vs.similarity_search(query, k=EXTRACTION_K)
    return "\n\n---\n\n".join(d.page_content for d in docs)


def _get_context_for_queries(queries: List[str], k_per_query: int = 6) -> str:
    """Run multiple targeted queries against the vectorstore and return deduplicated text chunks."""
    global _current_vs
    if not _current_vs:
        return ""
    all_chunks = []
    seen = set()
    for q in queries:
        try:
            docs = _current_vs.similarity_search(q, k=k_per_query)
            # Prioritize chunks that contain table markup
            sorted_docs = sorted(docs, key=lambda d: 0 if d.metadata.get("type") == "table" or "[TABLE" in d.page_content else 1)
            for d in sorted_docs:
                content = d.page_content.strip()
                if content not in seen:
                    seen.add(content)
                    all_chunks.append(content)
        except Exception as e:
            print(f"⚠️ Vectorstore search failed for '{q}': {e}")
    return "\n\n---\n\n".join(all_chunks)


def _parse_json(raw: Any) -> Any:
    """Extract and parse the first JSON object/array from a string or LLM response."""
    if not isinstance(raw, str):
        raw = extract_llm_content(raw)
    try:
        return json.loads(raw.strip())
    except Exception:
        pass
    clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        return json.loads(clean)
    except Exception:
        pass
    m = re.search(r'\{[\s\S]+\}', clean)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    m_list = re.search(r'\[[\s\S]+\]', clean)
    if m_list:
        try:
            return json.loads(m_list.group())
        except Exception:
            pass
    return {}


# ── SECTION PROMPTS ───────────────────────────────────────────────────────────

OFFER_BASIC_PROMPT = """You are a senior financial analyst. Extract basic IPO offer details and objects of the issue from the provided RHP/DRHP excerpts and any web search results.

Output strictly valid JSON with this schema:
{
  "basic_info": {
    "issue_size": "string | null",
    "price_band": "string | null",
    "market_cap": "string | null",
    "lot_size": "number | null",
    "face_value": "string | null",
    "fresh_issue": "string | null",
    "offer_for_sale": "string | null",
    "promoter_holding_pre_pct": "number | null",
    "promoter_holding_post_pct": "number | null",
    "bid_open_date": "YYYY-MM-DD | null",
    "bid_close_date": "YYYY-MM-DD | null",
    "listing_date": "YYYY-MM-DD | null"
  },
  "objects_of_issue": {
    "total_amount": "string | null",
    "breakdown": [
      { "purpose": "string", "amount": "string | null" }
    ],
    "categories": ["string"]
  }
}

Rules:
- For monetary numbers (issue_size, fresh_issue, offer_for_sale), preserve standard units and currency (e.g. "₹2,772 Cr", "₹500 M").
- For ratios and metrics (promoter %, lot_size), output pure numbers without "%" or "x".
- Dates must use YYYY-MM-DD.
- Never fabricate numbers. If unavailable, use null or [].
- Return ONLY the JSON object — no commentary, no markdown fences.
"""

FINANCIALS_METRICS_PROMPT = """You are a senior financial analyst specializing in Indian IPOs. Extract multi-year restated financial figures, key metrics, and peer comparison from the provided RHP/DRHP excerpts.

Look especially for tables titled "Restated Consolidated Summary Statement of Profit and Loss", "Summary Financial Information", and "Key Performance Indicators".

Output strictly valid JSON with this schema:
{
  "financial_summary": {
    "yearly_financials": [
      {
        "year": "string, e.g. FY2026, FY2025, FY2024",
        "revenue": "string | null",
        "ebitda": "string | null",
        "ebitda_margin_pct": "number | null",
        "pat": "string | null",
        "pat_margin_pct": "number | null",
        "eps": "number | null",
        "cfo": "string | null"
      }
    ],
    "key_metrics": {
      "balance_sheet": [
        { "label": "string", "value": "string" }
      ],
      "return_ratios": [
        { "label": "string", "value": "string" }
      ],
      "valuation_multiples": [
        { "label": "string", "value": "string" }
      ],
      "sector_kpis": [
        { "label": "string", "value": "string" }
      ]
    },
    "ipo_structure": "string | null",
    "pre_ipo_placements": "string | null"
  },
  "peer_comparison": [
    {
      "name": "string",
      "pe": "number | null",
      "revenue": "string | null",
      "pat_margin_pct": "number | null"
    }
  ]
}

Rules:
- In yearly_financials, extract all disclosed fiscal years (typically 3 to 5 years, e.g. FY2026, FY2025, FY2024).
- For large monetary figures (revenue, ebitda, pat, cfo), format as strings with denomination (e.g. "₹31,519.68 M", "₹2,690.51 Cr").
- Margins, ratios, and EPS must be pure numbers without "%" or "₹" symbols.
- In key_metrics, include stated metrics like Net Worth, Net Debt, NAV, RoNW (%), RoCE (%), P/E ratio.
- If peer comparison is not in the text, return [] (empty list). Never output "NA".
- Return ONLY the JSON object — no commentary, no markdown fences.
"""

BUSINESS_OVERVIEW_PROMPT = """You are a senior financial analyst. Extract the company and business overview from the provided RHP/DRHP excerpts.

Output strictly valid JSON with this schema:
{
  "business_overview": {
    "business_model": "string | null",
    "competitive_moat": "string | null",
    "revenue_streams": ["string"],
    "customer_segments": ["string"]
  },
  "company_overview": {
    "name": "string",
    "industry": "string | null",
    "ipo_status": "string | null",
    "headquarters": {
      "corporate_office": "string | null",
      "registered_office": "string | null"
    },
    "incorporation_year": "number | null"
  }
}

Rules:
- Keep business model and competitive moat clear, concise, and informative.
- If incorporation year is not stated, return null.
- Return ONLY the JSON object — no commentary, no markdown fences.
"""

MANAGEMENT_PROMOTERS_PROMPT = """You are a senior financial analyst. Extract key management personnel, promoters, and litigation details from the provided RHP/DRHP excerpts.

Output strictly valid JSON with this schema:
{
  "management": {
    "key_management": [
      { "name": "string", "role": "string" }
    ],
    "promoters": [
      { "name": "string", "type": "string | null" }
    ],
    "litigations": {
      "status_summary": "string | null",
      "details": "string | null"
    }
  }
}

Rules:
- Include up to 6-8 key managerial personnel (MD, Executive Directors, CEO, CFO, CS).
- Include all individual and corporate promoters disclosed.
- In litigations, summarize pending material legal proceedings.
- Return ONLY the JSON object — no commentary, no markdown fences.
"""

RISK_FACTORS_PROMPT = """Extract the risk factors from the RHP/DRHP document.
Sort every risk factor into exactly one of these categories (do not create new ones):
- Business & Operational Risks
- Financial Risks
- Regulatory & Legal Risks
- Market & Liquidity Risks
- Offer-Related Risks
- Management & Governance Risks
- Industry & Competition Risks
- Other Risks

Each description should be a single self-contained sentence.

Return ONLY a JSON array with this schema:
[
  {"category": "<one of the fixed categories above>", "description": "string"}
]
"""

STRENGTHS_PROMPT = """Extract the competitive strengths from the RHP/DRHP document.
Sort every strength into exactly one of these categories (do not create new ones):
- Business & Operational Strengths
- Financial Strengths
- Management & Promoter Strengths
- Market & Competitive Strengths
- Product & Technology Strengths
- Other Strengths

Each description should be a single self-contained sentence.

Return ONLY a JSON array with this schema:
[
  {"category": "<one of the fixed categories above>", "description": "string"}
]
"""


# ── FOCUSED PIPELINES ─────────────────────────────────────────────────────────

def _extract_offer_and_basic(llm, ipo_name: str) -> dict:
    """Pipeline 1: Offer Details & Objects of the Issue."""
    queries = [
        "The Offer Summary Issue Size Price Band Fresh Issue Offer for Sale Lot Size Face Value",
        "Objects of the Offer Requirements of Funds Net Proceeds",
        "Shareholding Pattern Promoters Pre-Issue Post-Issue Shareholding percentage"
    ]
    ctx = _get_context_for_queries(queries, k_per_query=6)
    
    # Check if we should supplement with Tavily if RHP context is thin
    extra_info = ""
    try:
        search_res = _fetch_tavily(f"{ipo_name} IPO price band lot size issue size dates", max_results=2)
        if search_res:
            extra_info = f"\n\nWeb Search Reference:\n{json.dumps(search_res)}"
    except Exception:
        pass

    prompt_user = f"Extract basic IPO offer info and objects of issue for '{ipo_name}'.\n\nRHP Excerpts:\n{ctx}{extra_info}"
    
    try:
        raw = llm.invoke([
            SystemMessage(content=OFFER_BASIC_PROMPT),
            HumanMessage(content=prompt_user)
        ])
        return _parse_json(raw)
    except Exception as e:
        print(f"⚠️ Offer & Basic extraction failed: {e}")
        return {}


def _extract_financials_and_metrics(llm, ipo_name: str) -> dict:
    """Pipeline 2: Multi-Year Restated Financials, KPIs, Ratios & Peers."""
    queries = [
        "Restated Consolidated Summary Statement of Profit and Loss Revenue from Operations EBITDA Profit for the year PAT",
        "Key Performance Indicators Return on Net Worth RoNW RoCE Net Asset Value Total Borrowings Net Worth",
        "Basis for Issue Price Comparison with Listed Industry Peers Peer Group Net Asset Value PE Ratio"
    ]
    ctx = _get_context_for_queries(queries, k_per_query=6)
    
    prompt_user = f"Extract restated multi-year financials, key metrics, and peer comparison for '{ipo_name}'.\n\nRHP Excerpts:\n{ctx}"
    
    try:
        raw = llm.invoke([
            SystemMessage(content=FINANCIALS_METRICS_PROMPT),
            HumanMessage(content=prompt_user)
        ])
        return _parse_json(raw)
    except Exception as e:
        print(f"⚠️ Financials & Metrics extraction failed: {e}")
        return {}


def _extract_business_overview(llm, ipo_name: str) -> dict:
    """Pipeline 3: Business Model, Revenue Streams, Corporate Profile."""
    queries = [
        "Our Business Business Model Competitive Moat Revenue Streams Products Services",
        "Company Overview Date of Incorporation Corporate Office Registered Office Industry Sector"
    ]
    ctx = _get_context_for_queries(queries, k_per_query=5)
    
    prompt_user = f"Extract business model, moat, and company overview for '{ipo_name}'.\n\nRHP Excerpts:\n{ctx}"
    
    try:
        raw = llm.invoke([
            SystemMessage(content=BUSINESS_OVERVIEW_PROMPT),
            HumanMessage(content=prompt_user)
        ])
        return _parse_json(raw)
    except Exception as e:
        print(f"⚠️ Business Overview extraction failed: {e}")
        return {}


def _extract_management_and_promoters(llm, ipo_name: str) -> dict:
    """Pipeline 4: Key Management Personnel, Promoters & Legal."""
    queries = [
        "Our Management Board of Directors Key Managerial Personnel Executive Directors Managing Director",
        "Our Promoters Individual Promoters Corporate Promoters Outstanding Litigation Material Litigations"
    ]
    ctx = _get_context_for_queries(queries, k_per_query=5)
    
    prompt_user = f"Extract key management personnel, promoters, and litigations for '{ipo_name}'.\n\nRHP Excerpts:\n{ctx}"
    
    try:
        raw = llm.invoke([
            SystemMessage(content=MANAGEMENT_PROMOTERS_PROMPT),
            HumanMessage(content=prompt_user)
        ])
        return _parse_json(raw)
    except Exception as e:
        print(f"⚠️ Management & Promoters extraction failed: {e}")
        return {}


def format_sentiment_data(sentiment_data: dict) -> dict:
    """Formats the raw sentiment dictionary into the strict JSON schema expected by the UI."""
    if "error" in sentiment_data:
        return {
            "gmp": None, "score": None, "sentiment_label": "Neutral",
            "summary": [], "positives": [], "negatives": [],
            "subscription": {"total": None, "qib": None, "nii": None, "retail": None},
            "articles": [], "sources_used": []
        }
        
    gmp_val = sentiment_data.get("gmp")
    score_val = sentiment_data.get("score")
    
    def _clean_gmp(val):
        if val is None:
            return None
        v = str(val).strip()
        if not v or v in ("-", "--", "0", "0.0", "N/A", "null", "None"):
            return None
        if "🔥" in v or not re.search(r"\d", v):
            return None
        return v

    def _parse_num(val):
        if val is None: return None
        v = str(val).lower().replace("₹", "").replace(",", "").replace("%", "").replace("x", "").strip()
        try:
            return float(v)
        except Exception:
            return None
            
    sub_raw = sentiment_data.get("subscription_estimate", {})
    sub_dict = {"total": None, "qib": None, "nii": None, "retail": None}
    
    if isinstance(sub_raw, dict):
        sub_dict.update({
            "total": sub_raw.get("total"),
            "qib": sub_raw.get("qib"),
            "nii": sub_raw.get("nii"),
            "retail": sub_raw.get("retail")
        })
    elif isinstance(sub_raw, str) and sub_raw:
        sub_dict["total"] = sub_raw

    sentiment_json = {
        "gmp": _clean_gmp(gmp_val),
        "score": _parse_num(score_val),
        "sentiment_label": sentiment_data.get("sentiment_label", "Neutral").replace("📉", "").replace("🚀", "").replace("📈", "").strip(),
        "summary": sentiment_data.get("summary", []),
        "positives": sentiment_data.get("positives", []),
        "negatives": sentiment_data.get("negatives", []),
        "subscription_estimate": sub_dict,
        "articles": sentiment_data.get("articles", []),
        "sources_used": sentiment_data.get("sources_used", [])
    }
    
    valid_labels = ["Positive", "Negative", "Neutral"]
    if sentiment_json["sentiment_label"] not in valid_labels:
        sentiment_json["sentiment_label"] = "Neutral"
        
    return sentiment_json


def extract_ipo_profile(vectorstore: Chroma, ipo_name: str, progress_callback=None) -> dict:
    """
    Main entry point for extraction.
    Executes focused modular extraction pipelines corresponding to standard RHP chapters:
      1. Offer Details & Basic Info
      2. Financial Statements & Key Metrics
      3. Business & Company Overview
      4. Management, Promoters & Legal
      5. Risk Factors & Competitive Strengths
      6. Web Market Sentiment
    """
    global _current_vs, _current_ipo_name
    _current_vs = vectorstore
    _current_ipo_name = ipo_name
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", ipo_name)
    cache_path = os.path.join(CACHE_DIR, f"{safe}_profile.json")

    if os.path.exists(cache_path):
        if progress_callback: progress_callback("Loading cached IPO profile…")
        try:
            with open(cache_path) as f:
                data = json.load(f)
                return IPOProfile(data)
        except Exception:
            pass

    llm = get_llm(purpose="extraction", temperature=0)
    
    # ── Pipeline 1: Offer & Basic Info ───────────────────────────────────────
    if progress_callback: progress_callback("Extracting Offer Details & Basic Info (1/5)...")
    offer_data = _extract_offer_and_basic(llm, ipo_name)
    time.sleep(1.0)
    
    # ── Pipeline 2: Financials & Metrics ─────────────────────────────────────
    if progress_callback: progress_callback("Extracting Restated Financials & KPIs (2/5)...")
    fin_data = _extract_financials_and_metrics(llm, ipo_name)
    time.sleep(1.0)

    # ── Pipeline 3: Business Overview ────────────────────────────────────────
    if progress_callback: progress_callback("Extracting Business Model & Corporate Profile (3/5)...")
    biz_data = _extract_business_overview(llm, ipo_name)
    time.sleep(1.0)

    # ── Pipeline 4: Management & Promoters ───────────────────────────────────
    if progress_callback: progress_callback("Extracting Management, Promoters & Legal (4/5)...")
    mgmt_data = _extract_management_and_promoters(llm, ipo_name)
    time.sleep(1.0)

    # ── Pipeline 5: Risks & Strengths ────────────────────────────────────────
    if progress_callback: progress_callback("Extracting Risk Factors & Strengths (5/5)...")
    risk_ctx = _get_context_for_queries(["risk factors key risks litigation regulatory principal risks"], k_per_query=6)
    risk_user = f"Extract risk factors for '{ipo_name}'. RHP Excerpts:\n{risk_ctx}"
    try:
        risk_raw = llm.invoke([
            SystemMessage(content=RISK_FACTORS_PROMPT),
            HumanMessage(content=risk_user)
        ])
        risk_json = _parse_json(risk_raw)
    except Exception:
        risk_json = []
    
    time.sleep(1.0)
    strength_ctx = _get_context_for_queries(["competitive strengths business advantages key strengths competitive moat"], k_per_query=6)
    strength_user = f"Extract competitive strengths for '{ipo_name}'. RHP Excerpts:\n{strength_ctx}"
    try:
        strength_raw = llm.invoke([
            SystemMessage(content=STRENGTHS_PROMPT),
            HumanMessage(content=strength_user)
        ])
        strength_json = _parse_json(strength_raw)
    except Exception:
        strength_json = []

    # ── Pipeline 6: Market Sentiment ─────────────────────────────────────────
    sentiment_data = analyze_sentiment(ipo_name)
    sentiment_json = format_sentiment_data(sentiment_data)

    # ── Assemble Final JSON Schema ───────────────────────────────────────────
    final_profile = {
        "meta": {
            "company_name": ipo_name,
            "slug": safe,
            "exchange": None,
            "last_updated": datetime.now().isoformat()
        },
        "basic_info": offer_data.get("basic_info") or {
            "issue_size": None, "price_band": None, "market_cap": None, "lot_size": None,
            "face_value": None, "fresh_issue": None, "offer_for_sale": None,
            "promoter_holding_pre_pct": None, "promoter_holding_post_pct": None,
            "bid_open_date": None, "bid_close_date": None, "listing_date": None
        },
        "business_overview": biz_data.get("business_overview") or {
            "business_model": None, "competitive_moat": None, "revenue_streams": [], "customer_segments": []
        },
        "financial_summary": fin_data.get("financial_summary") or {
            "yearly_financials": [],
            "key_metrics": { "balance_sheet": [], "return_ratios": [], "valuation_multiples": [], "sector_kpis": [] },
            "ipo_structure": None,
            "pre_ipo_placements": None
        },
        "peer_comparison": fin_data.get("peer_comparison") or [],
        "objects_of_issue": offer_data.get("objects_of_issue") or {
            "total_amount": None, "breakdown": [], "categories": []
        },
        "management": mgmt_data.get("management") or {
            "key_management": [], "promoters": [], "litigations": { "status_summary": None, "details": None }
        },
        "company_overview": biz_data.get("company_overview") or {
            "name": ipo_name, "industry": None, "ipo_status": None,
            "headquarters": { "corporate_office": None, "registered_office": None },
            "incorporation_year": None
        },
        "risk_factors": risk_json if isinstance(risk_json, list) else [],
        "strengths": strength_json if isinstance(strength_json, list) else [],
        "sentiment": sentiment_json
    }

    # Save to disk cache
    try:
        with open(cache_path, "w") as f:
            json.dump(final_profile, f, indent=2)
    except Exception as e:
        print(f"Failed to cache profile: {e}")

    return IPOProfile(final_profile)
