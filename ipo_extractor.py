# ipo_extractor.py
import os
import json
import re
import time
from typing import Optional, List, Dict, Any
from datetime import datetime

from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain.tools import tool

from agents.tools import get_llm, classify_llm_error
from sentiment_agent import _fetch_tavily, analyze_sentiment

# ── config ────────────────────────────────────────────────────────────────────
EXTRACTION_K          = 8
CACHE_DIR             = "ipo_analysis_cache"
# ─────────────────────────────────────────────────────────────────────────────

# Globals for tool context
_current_vs = None
_current_ipo_name = None


@tool
def tavily_web_search(query: str) -> str:
    """Search the web via Tavily for missing IPO details like lot size, market cap, or peer financials."""
    time.sleep(1.5) # respect rate limit
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


def _parse_json(raw: str) -> Any:
    """Extract and parse the first JSON object/array from a string."""
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
    return {}


USER_SYSTEM_PROMPT = """Extract IPO information into **exactly** the schema below — same keys, same nesting, same types — for every IPO, regardless of industry. Never add extra top-level keys. Never rename keys. Never invent new categories where an enum is specified.

## Source priority (apply to every field)
1. **Primary source**: the RHP/DRHP document text for this IPO (use `vectorstore_search`).
2. **Fallback**: if a field is not present or not clearly stated in the RHP/DRHP, search Tavily for it (e.g. `"<company name> IPO lot size"`, `"<company name> IPO market cap"`).
3. **If still unavailable after both**: use `null` for scalar fields, `[]` for list fields — **except** `peer_comparison` fields, which use the string `"NA"`.
4. **Never fabricate or estimate a plausible-sounding number.** A missing field must stay missing.

## Global type rules
- Any field that is inherently numeric (gmp, score, pe, revenue, market_cap, pat_margin_pct, promoter %, subscription multiples, etc.) must be output as a **number**, with no "x", "₹", "Cr", or "%" characters embedded in the value. Put units in field names/labels, not in the value.
- Dates use `YYYY-MM-DD`.
- Do not output placeholder sentences like "Not disclosed in the provided text" anywhere — use `null`/`[]` per the rule above.

## Schema
{
  "meta": {
    "company_name": "string",
    "slug": "string",
    "exchange": "string",
    "last_updated": "ISO 8601 timestamp"
  },
  "basic_info": {
    "issue_size": "string | null",
    "price_band": "string | null",
    "market_cap": "number | null",
    "lot_size": "number | null",
    "face_value": "number | null",
    "fresh_issue": "string | null",
    "offer_for_sale": "string | null",
    "promoter_holding_pre_pct": "number | null",
    "promoter_holding_post_pct": "number | null",
    "bid_open_date": "date | null",
    "bid_close_date": "date | null",
    "listing_date": "date | null"
  },
  "business_overview": {
    "business_model": "string | null",
    "competitive_moat": "string | null",
    "revenue_streams": ["string"],
    "customer_segments": ["string"]
  },
  "financial_summary": {
    "yearly_financials": [
      {
        "year": "string, e.g. FY2024",
        "revenue": "number | null",
        "ebitda": "number | null",
        "ebitda_margin_pct": "number | null",
        "pat": "number | null",
        "pat_margin_pct": "number | null",
        "eps": "number | null",
        "cfo": "number | null"
      }
    ],
    "key_metrics": {
      "balance_sheet": [ {"label": "string", "value": "string"} ],
      "return_ratios": [ {"label": "string", "value": "string"} ],
      "valuation_multiples": [ {"label": "string", "value": "string"} ],
      "sector_kpis": [ {"label": "string", "value": "string"} ]
    },
    "ipo_structure": "string | null",
    "pre_ipo_placements": "string | null"
  },
  "peer_comparison": [
    {
      "name": "string | \"NA\"",
      "pe": "number | \"NA\"",
      "revenue": "number | \"NA\"",
      "pat_margin_pct": "number | \"NA\""
    }
  ],
  "objects_of_issue": {
    "total_amount": "string | null",
    "breakdown": [ {"purpose": "string", "amount": "number | null"} ],
    "categories": ["string"]
  },
  "management": {
    "key_management": [ {"name": "string", "role": "string"} ],
    "promoters": [ {"name": "string", "type": "string | null"} ],
    "litigations": {
      "status_summary": "string | null",
      "details": "string | null"
    }
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

## Field-specific instructions
- `basic_info`: Pull from RHP first. If missing, search Tavily before falling back to null.
- `peer_comparison`: Try RHP first, then Tavily. If missing, output string "NA".
- `financial_summary.key_metrics`: Extract generic {label, value} arrays based on the RHP's key metrics. Don't invent metrics.
- `financial_summary.yearly_financials`: 3 fiscal years typically. Null for missing line items.

## Output requirements
Return **only** the JSON object — no markdown fences, no commentary.
Every key in the schema above must be present in the output, even when its value is null or []."""

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


def _agentic_extraction(llm, sys_prompt: str, user_prompt: str, max_steps=12, progress_callback=None) -> str:
    """Custom tool-calling loop prioritizing Mistral RPS limits."""
    tools = [tavily_web_search, vectorstore_search]
    llm_with_tools = llm.bind_tools(tools)
    
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    for i in range(max_steps):
        time.sleep(1.5) # Global rate limit buffer for Mistral
        
        try:
            response = llm_with_tools.invoke(messages)
            messages.append(response)
            
            if not response.tool_calls:
                return response.content
                
            for tool_call in response.tool_calls:
                if progress_callback:
                    progress_callback(f"Running tool: {tool_call['name']}...")
                    
                if tool_call['name'] == 'tavily_web_search':
                    res = tavily_web_search.invoke(tool_call['args'])
                elif tool_call['name'] == 'vectorstore_search':
                    res = vectorstore_search.invoke(tool_call['args'])
                else:
                    res = "Unknown tool"
                
                messages.append(ToolMessage(content=res, tool_call_id=tool_call['id']))
                
        except Exception as exc:
            print(f"⚠️ Agent step failed: {exc}")
            # Try to gracefully exit if it's a rate limit or terminal error
            break
            
    # If it exits the loop without returning, try one last forced generation
    return messages[-1].content if hasattr(messages[-1], 'content') else ""


def extract_ipo_profile(vectorstore: Chroma, ipo_name: str, progress_callback=None) -> dict:
    """
    Main entry point for extraction.
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
                return json.load(f)
        except Exception:
            pass

    llm = get_llm(purpose="extraction", temperature=0)
    
    if progress_callback: progress_callback("Starting Agentic Extraction (Phase 1/3)...")
    
    # 1. Main Agentic Extraction
    main_user = f"Extract the profile for '{ipo_name}'. Start by searching the vectorstore for 'basic info', 'financials', 'peers', 'management'. Use tavily_web_search for missing facts."
    main_raw = _agentic_extraction(llm, USER_SYSTEM_PROMPT, main_user, progress_callback=progress_callback)
    main_json = _parse_json(main_raw)
    
    if progress_callback: progress_callback("Extracting Risk Factors & Strengths (Phase 2/3)...")
    
    # 2. Risk Factors Extraction (Lightweight, no tools needed, just vectorstore)
    risk_ctx = vectorstore_search.invoke({"query": "risk factors key risks litigation regulatory"})
    risk_user = f"Extract risk factors for '{ipo_name}'. RHP Excerpts:\n{risk_ctx}"
    
    time.sleep(1.5)
    risk_raw = llm.invoke([
        SystemMessage(content=RISK_FACTORS_PROMPT),
        HumanMessage(content=risk_user)
    ])
    risk_json = _parse_json(risk_raw.content)
    
    # 2.5 Strengths Extraction
    strength_ctx = vectorstore_search.invoke({"query": "competitive strengths business advantages key strengths"})
    strength_user = f"Extract competitive strengths for '{ipo_name}'. RHP Excerpts:\n{strength_ctx}"
    
    time.sleep(1.5)
    strength_raw = llm.invoke([
        SystemMessage(content=STRENGTHS_PROMPT),
        HumanMessage(content=strength_user)
    ])
    strength_json = _parse_json(strength_raw.content)
    
    if progress_callback: progress_callback("Fetching Sentiment & Finalizing (Phase 3/3)...")
    
    # 3. Sentiment Extraction (Reuse sentiment_agent)
    # The sentiment agent returns a dict which we inject into the new schema
    sentiment_data = analyze_sentiment(ipo_name)
    if "error" in sentiment_data:
        sentiment_json = {
            "gmp": None, "score": None, "sentiment_label": "Neutral",
            "summary": [], "positives": [], "negatives": [],
            "subscription": {"total": None, "qib": None, "nii": None, "retail": None},
            "articles": [], "sources_used": []
        }
    else:
        # Map old sentiment format to new strict numeric schema
        gmp_val = sentiment_data.get("gmp")
        score_val = sentiment_data.get("score")
        
        def _parse_num(val):
            if val is None: return None
            v = str(val).lower().replace("₹", "").replace(",", "").replace("%", "").replace("x", "").strip()
            try:
                return float(v)
            except:
                return None
                
        # Handle subscription object
        sub_raw = sentiment_data.get("subscription_estimate", "")
        sub_dict = {"total": None, "qib": None, "nii": None, "retail": None}
        if isinstance(sub_raw, str):
            # Try to extract numbers from string like "1.21x (Total), 0.29x (QIB)"
            m_tot = re.search(r'([\d.]+)\s*x?\s*\(total\)', sub_raw, re.I)
            m_qib = re.search(r'([\d.]+)\s*x?\s*\(qib\)', sub_raw, re.I)
            m_nii = re.search(r'([\d.]+)\s*x?\s*\(nii\)', sub_raw, re.I)
            m_ret = re.search(r'([\d.]+)\s*x?\s*\(retail\)', sub_raw, re.I)
            if m_tot: sub_dict["total"] = float(m_tot.group(1))
            if m_qib: sub_dict["qib"] = float(m_qib.group(1))
            if m_nii: sub_dict["nii"] = float(m_nii.group(1))
            if m_ret: sub_dict["retail"] = float(m_ret.group(1))
            
        sentiment_json = {
            "gmp": _parse_num(gmp_val),
            "score": _parse_num(score_val),
            "sentiment_label": sentiment_data.get("sentiment_label", "Neutral").replace("📉", "").replace("🚀", "").replace("📈", "").strip(),
            "summary": sentiment_data.get("summary", []),
            "positives": sentiment_data.get("positives", []),
            "negatives": sentiment_data.get("negatives", []),
            "subscription": sub_dict,
            "articles": sentiment_data.get("articles", []),
            "sources_used": sentiment_data.get("sources_used", [])
        }
        
        # fallback label fix
        valid_labels = ["Positive", "Negative", "Neutral"]
        if sentiment_json["sentiment_label"] not in valid_labels:
            sentiment_json["sentiment_label"] = "Neutral"

    # Assemble Final JSON
    final_profile = main_json
    final_profile["risk_factors"] = risk_json if isinstance(risk_json, list) else []
    final_profile["strengths"] = strength_json if isinstance(strength_json, list) else []
    final_profile["sentiment"] = sentiment_json
    
    # Ensure meta fields exist
    if "meta" not in final_profile:
        final_profile["meta"] = {}
    final_profile["meta"]["company_name"] = ipo_name
    final_profile["meta"]["slug"] = safe
    final_profile["meta"]["last_updated"] = datetime.now().isoformat()
    
    # Save cache
    try:
        with open(cache_path, "w") as f:
            json.dump(final_profile, f, indent=2)
    except Exception as e:
        print(f"Failed to cache profile: {e}")
        
    return final_profile