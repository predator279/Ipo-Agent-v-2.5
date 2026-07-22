# sentiment_agent.py  (v2 — Tavily + Reddit + Google News + structured output)
#
# Sources (in priority order):
#   1. Tavily Search API  — best quality, real-time web results with full content
#   2. Reddit via PRAW    — retail investor community discussion
#   3. Google News RSS    — mainstream financial media headlines
#
# Output schema:
# {
#   "score": 3.8,                    # 0.0 (very negative) → 5.0 (very positive)
#   "sentiment_label": "Positive",   # Very Negative / Negative / Neutral / Positive / Very Positive
#   "gmp": "₹45 (~12%)",             # Grey Market Premium if found
#   "subscription_estimate": "...",  # QIB/HNI/Retail estimates from news
#   "summary": ["bullet1", ...],     # 4-6 key sentiment drivers
#   "positives": ["..."],            # Bull case points
#   "negatives": ["..."],            # Bear case / concern points
#   "sources_used": ["Tavily", "Reddit", "Google News"],
#   "articles": [                    # Top cited articles
#       {"title": "...", "url": "...", "source": "..."}
#   ]
# }

import os
import json
import re
import urllib.parse
from typing import List, Dict, Any, Optional

import feedparser
import praw
import requests
from bs4 import BeautifulSoup


# ── Reddit config (loaded from .streamlit/secrets.toml or environment) ────────
# Reddit requires a unique user-agent in the format: platform:app_id:version (by username)
# Stale/generic agents like 'script' or 'IPO_Analyzer/v2.0' are rejected with 401.
# Steps to fix a 401: go to https://www.reddit.com/prefs/apps and regenerate your app secret.

def _get_secret(key: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then os.environ, then default."""
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val and val not in ("your_reddit_client_id", "your_reddit_client_secret", ""):
            return val
    except Exception:
        pass
    return os.getenv(key, default)


REDDIT_CLIENT_ID     = _get_secret("REDDIT_CLIENT_ID",     "")
REDDIT_CLIENT_SECRET = _get_secret("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = _get_secret(
    "REDDIT_USER_AGENT",
    "windows:ipo-research-agent:v2.1 (by /u/your_reddit_username)"
)

# ── Tavily config ─────────────────────────────────────────────────────────────
# Users can set TAVILY_API_KEY in environment or Streamlit secrets.
# Free tier: 1000 searches/month. https://app.tavily.com
TAVILY_API_KEY = _get_secret("TAVILY_API_KEY", "")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# ── sentiment label mapping ───────────────────────────────────────────────────
def _score_to_label(score: float) -> str:
    if score >= 4.2:   return "Very Positive 🚀"
    if score >= 3.4:   return "Positive 📈"
    if score >= 2.6:   return "Neutral ➡️"
    if score >= 1.8:   return "Negative 📉"
    return "Very Negative ⚠️"


# ==============================================================================
# SOURCE 1 — Tavily (best quality)
# ==============================================================================

def _fetch_tavily(ipo_name: str, max_results: int = 8) -> List[Dict]:
    """
    Uses Tavily Search API to find high-quality, recent articles about the IPO.
    Returns a list of {source, title, url, content} dicts.
    """
    api_key = TAVILY_API_KEY or os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        print("   ⚠️  No TAVILY_API_KEY set — skipping Tavily.")
        return []

    results = []
    queries = [
        f"{ipo_name} IPO review analysis 2025",
        f"{ipo_name} IPO GMP grey market premium subscription",
        f"{ipo_name} IPO allotment listing date investor opinion",
    ]

    for query in queries:
        try:
            resp = requests.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key":              api_key,
                    "query":                query,
                    "search_depth":         "advanced",
                    "include_answer":       False,
                    "include_raw_content":  False,
                    "max_results":          max_results // len(queries) + 1,
                    "include_domains":      [
                        "moneycontrol.com", "economictimes.indiatimes.com",
                        "livemint.com", "businessstandard.com", "zerodha.com",
                        "chittorgarh.com", "ipowatch.in", "investorgain.com",
                        "equitybulls.com", "reddit.com", "valuepickr.com",
                    ],
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("results", []):
                results.append({
                    "source":  "Tavily/" + (item.get("url", "").split("/")[2] if item.get("url") else "web"),
                    "title":   item.get("title", ""),
                    "url":     item.get("url", ""),
                    "content": item.get("content", "")[:800],  # cap per article
                })
        except Exception as exc:
            print(f"   ⚠️  Tavily query failed: {exc}")

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for r in results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique.append(r)

    print(f"   ✅ Tavily: {len(unique)} articles found.")
    return unique[:max_results]


# ==============================================================================
# SOURCE 2 — Reddit
# ==============================================================================

def _fetch_reddit(ipo_name: str, limit_posts: int = 15, limit_comments: int = 3) -> List[Dict]:
    """Fetch recent Reddit discussions about the IPO."""
    # Re-read credentials at call time so they pick up any late-loaded secrets
    client_id     = _get_secret("REDDIT_CLIENT_ID",     REDDIT_CLIENT_ID)
    client_secret = _get_secret("REDDIT_CLIENT_SECRET", REDDIT_CLIENT_SECRET)
    user_agent    = _get_secret("REDDIT_USER_AGENT",    REDDIT_USER_AGENT)

    if not client_id or not client_secret:
        print("   ⚠️  Reddit credentials not set in secrets.toml. "
              "Add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET. Skipping Reddit.")
        return []

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        records = []
        query = f"{ipo_name} IPO" if "ipo" not in ipo_name.lower() else ipo_name
        # Search focused subreddits first, then all
        subreddits = ["IndiaInvestments+DalalStreetTalks+IndianStockMarket+all"]
        for sub in subreddits:
            for submission in reddit.subreddit(sub).search(query, sort="new", limit=limit_posts):
                submission.comments.replace_more(limit=0)
                comments_text = " | ".join(
                    c.body for i, c in enumerate(submission.comments.list())
                    if i < limit_comments and hasattr(c, "body") and len(c.body) > 20
                )
                records.append({
                    "source":  f"Reddit/r/{submission.subreddit.display_name}",
                    "title":   submission.title,
                    "url":     f"https://reddit.com{submission.permalink}",
                    "content": f"{submission.title}. {getattr(submission, 'selftext', '')[:300]} | Comments: {comments_text}",
                })
        print(f"   ✅ Reddit: {len(records)} posts found.")
        return records[:limit_posts]
    except Exception as exc:
        print(f"   ⚠️  Reddit fetch failed: {exc}")
        return []


# ==============================================================================
# SOURCE 3 — Google News RSS
# ==============================================================================

def _fetch_google_news(ipo_name: str, limit: int = 10) -> List[Dict]:
    """Fetch Google News RSS headlines about the IPO."""
    try:
        query   = urllib.parse.quote(f"{ipo_name} IPO")
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        feed    = feedparser.parse(rss_url)
        results = []
        for entry in feed.entries[:limit]:
            summary = BeautifulSoup(getattr(entry, "summary", ""), "html.parser").get_text(" ", strip=True)
            results.append({
                "source":  "Google News",
                "title":   getattr(entry, "title", ""),
                "url":     getattr(entry, "link", ""),
                "content": f"{getattr(entry, 'title', '')}. {summary}",
            })
        print(f"   ✅ Google News: {len(results)} articles found.")
        return results
    except Exception as exc:
        print(f"   ⚠️  Google News fetch failed: {exc}")
        return []


# ==============================================================================
# GMP extraction helpers
# ==============================================================================

def _scrape_gmp_investorgain(ipo_name: str) -> Optional[str]:
    """
    Scrapes live GMP data from investorgain.com — the most reliable source
    for Indian IPO grey market premiums.

    Returns a string like "₹45 (~12%)" or None if not found.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": "https://www.investorgain.com/",
        }
        resp = requests.get(
            "https://www.investorgain.com/report/live-ipo-gmp/331/",
            headers=headers, timeout=12
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # The page has a table — search for the IPO name (partial match)
        name_lower = ipo_name.lower().split()[0]  # use first word to be fuzzy
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            row_text = cells[0].get_text(" ", strip=True).lower()
            if name_lower not in row_text:
                continue

            # columns: Company | Price | GMP | Est Listing | ...
            gmp_text = cells[2].get_text(" ", strip=True).strip()
            price_text = cells[1].get_text(" ", strip=True).strip()

            if gmp_text and gmp_text not in ("-", "0", "N/A", ""):
                # Try to compute percentage
                try:
                    gmp_val   = float(re.sub(r"[^\d.\-]", "", gmp_text))
                    price_val = float(re.sub(r"[^\d.]", "", price_text))
                    if price_val > 0:
                        pct = round(gmp_val / price_val * 100, 1)
                        return f"₹{gmp_val:g} ({pct:+.1f}%)"
                except Exception:
                    pass
                return f"₹{gmp_text}"

        print(f"   ⚠️  InvestorGain: '{ipo_name}' not found in GMP table.")
        return None

    except Exception as exc:
        print(f"   ⚠️  InvestorGain GMP scrape failed: {exc}")
        return None


def _extract_gmp_from_text(all_text: str, ipo_name: str) -> Optional[str]:
    """
    Fallback: tries to pull Grey Market Premium from aggregated source text.
    Patterns: "GMP ₹45", "grey market premium of ₹45", "GMP: +45"
    """
    patterns = [
        r"GMP[:\s]+[₹+]?\s*(\d+[\.,]?\d*)\s*(?:rupees?|rs\.?)?(?:\s*\(([^)]+)\))?",
        r"grey\s+market\s+premium[:\s]+[₹+]?\s*(\d+[\.,]?\d*)",
        r"trading at[:\s]+[₹+]?\s*(\d+[\.,]?\d*)\s+(?:premium|above)",
    ]
    for pat in patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            val = m.group(1).replace(",", "")
            pct = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            return f"₹{val}" + (f" ({pct})" if pct else "")
    return None


# ==============================================================================
# LLM sentiment analysis
# ==============================================================================

def _run_llm_analysis(
    ipo_name: str,
    snippets: List[Dict],
    llm,
) -> Dict[str, Any]:
    """
    Sends all collected snippets to the LLM for structured sentiment analysis.
    """
    from agents.tools import invoke_model

    # Build context — weight Tavily content higher (more complete)
    tavily_items  = [s for s in snippets if "Tavily" in s.get("source", "")]
    other_items   = [s for s in snippets if "Tavily" not in s.get("source", "")]

    # Tavily gets up to 12 items, others up to 8
    selected = tavily_items[:12] + other_items[:8]

    all_text = "\n\n".join([
        f"[{s['source']}] {s['title']}\n{s['content']}"
        for s in selected
    ])

    gmp = _extract_gmp_from_text(all_text, ipo_name)

    system_prompt = """You are a precise Indian IPO sentiment analyst.
Analyze the provided news and forum snippets about an IPO.
Return ONLY a valid JSON object — no markdown, no commentary.

JSON Schema:
{
  "score": <float 0.0-5.0>,
  "sentiment_label": "<Very Negative|Negative|Neutral|Positive|Very Positive>",
  "gmp": "<GMP value if found in text, else null>",
  "subscription_estimate": {
    "total": "<overall subscription times (e.g. 147x) or null>",
    "qib": "<QIB times or null>",
    "nii": "<NII times or null>",
    "retail": "<Retail times or null>"
  },
  "summary": ["<key point 1>", "<key point 2>", "<3-5 total bullets>"],
  "positives": ["<bull case point>", "..."],
  "negatives": ["<concern>", "..."]
}

Scoring guide:
0.0-1.0: Very Negative (fraud alerts, massive losses, strong avoid)
1.0-2.0: Negative (overvalued, poor financials, red flags)
2.0-3.0: Neutral (mixed, wait and watch)
3.0-4.0: Positive (good fundamentals, reasonable valuation, recommend)
4.0-5.0: Very Positive (exceptional growth, strong demand, high GMP)"""

    user_prompt = f"Analyze sentiment for '{ipo_name}' IPO:\n\n{all_text[:4000]}"

    try:
        response = invoke_model(llm, [("system", system_prompt), ("user", user_prompt)])
    except Exception as e:
        print(f"⚠️ Primary LLM failed ({e}). Falling back to Mistral...")
        import time
        from agents.tools import get_llm
        time.sleep(1.5)  # Respect Mistral's 1 request per second limit
        fallback_llm = get_llm(model_name="mistral-small-latest") # Force Mistral
        response = invoke_model(fallback_llm, [("system", system_prompt), ("user", user_prompt)])

    # Parse JSON robustly
    try:
        start = response.find("{")
        end   = response.rfind("}") + 1
        if start != -1 and end > start:
            result = json.loads(response[start:end])
        else:
            raise ValueError("No JSON found")
    except Exception:
        result = {
            "score": 2.5,
            "sentiment_label": "Neutral",
            "summary": [response[:500]],
            "positives": [],
            "negatives": [],
        }

    # Override GMP with regex-extracted value if LLM missed it
    if gmp and not result.get("gmp"):
        result["gmp"] = gmp

    # Add sentiment label if LLM returned score but no label
    if "score" in result and "sentiment_label" not in result:
        result["sentiment_label"] = _score_to_label(result["score"])

    return result


# ==============================================================================
# MAIN PUBLIC FUNCTION
# ==============================================================================

def analyze_sentiment(ipo_name: str) -> Dict[str, Any]:
    """
    Multi-source IPO sentiment analysis.
    Fetches from Tavily + Reddit + Google News, then uses LLM for structured output.

    Returns:
        {
            "score": float,
            "sentiment_label": str,
            "gmp": str | None,
            "subscription_estimate": str | None,
            "summary": [str, ...],
            "positives": [str, ...],
            "negatives": [str, ...],
            "sources_used": [str, ...],
            "articles": [{"title", "url", "source"}, ...]
        }
    """
    from agents.tools import get_llm

    print(f"\n🔍 [Sentiment Agent] Analyzing: {ipo_name}")
    all_snippets = []
    sources_used = []

    # ── fetch GMP directly from InvestorGain (most reliable) ──────────────
    print("→ Scraping GMP from InvestorGain…")
    direct_gmp = _scrape_gmp_investorgain(ipo_name)
    if direct_gmp:
        print(f"   ✅ InvestorGain GMP: {direct_gmp}")
    else:
        print("   ⚠️  InvestorGain: No GMP found (IPO may not have opened yet).")

    # ── fetch from all sources ────────────────────────────────────────────────
    print("→ Tavily…")
    tavily_data = _fetch_tavily(ipo_name)
    if tavily_data:
        all_snippets.extend(tavily_data)
        sources_used.append("Tavily")

    print("→ Reddit…")
    reddit_data = _fetch_reddit(ipo_name)
    if reddit_data:
        all_snippets.extend(reddit_data)
        sources_used.append("Reddit")

    print("→ Google News…")
    news_data = _fetch_google_news(ipo_name)
    if news_data:
        all_snippets.extend(news_data)
        sources_used.append("Google News")

    if not all_snippets:
        return {
            "score": 2.5,
            "sentiment_label": "Neutral ➡️",
            "gmp": None,
            "subscription_estimate": None,
            "summary": ["No market data found for this IPO yet."],
            "positives": [],
            "negatives": [],
            "sources_used": [],
            "articles": [],
        }

    # ── LLM analysis ─────────────────────────────────────────────────────────
    print("→ Running LLM sentiment analysis…")
    llm = get_llm(purpose="sentiment", temperature=0)
    result = _run_llm_analysis(ipo_name, all_snippets, llm)

    # ── GMP: prefer the direct InvestorGain scrape over LLM inference ────────
    if direct_gmp:
        result["gmp"] = direct_gmp  # authoritative value wins
    elif not result.get("gmp"):
        result["gmp"] = None        # ensure key always exists

    # ── attach metadata ───────────────────────────────────────────────────────
    result["sources_used"] = sources_used
    result["articles"] = [
        {"title": s["title"], "url": s.get("url", ""), "source": s["source"]}
        for s in all_snippets
        if s.get("title") and s.get("url")
    ][:10]

    # Normalise label with emoji
    if "sentiment_label" in result:
        label = result["sentiment_label"].replace(" 🚀", "").replace(" 📈", "").replace(" ➡️", "").replace(" 📉", "").replace(" ⚠️", "")
        result["sentiment_label"] = _score_to_label(result.get("score", 2.5))

    print(f"✅ [Sentiment Agent] Score: {result.get('score')} | {result.get('sentiment_label')}")
    return result