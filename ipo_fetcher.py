# ipo_fetcher.py (v3 — Upstox API primary, NSE fallback, unified schema)

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup
from typing import Dict, Optional


# =============================================================================
# NSE Data Fetcher
# =============================================================================

@st.cache_data(ttl=3600)
def fetch_all_ipo_data_separated() -> Dict[str, pd.DataFrame]:
    """
    Fetches Current, Past, and Upcoming IPOs directly from NSE endpoints.
    Cleans and formats them to the precise schema required.
    """
    print("Fetching new separated IPO data from NSE...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/"
    }

    endpoints = {
        "Current": "https://www.nseindia.com/api/ipo-current-issue",
        "Upcoming": "https://www.nseindia.com/api/all-upcoming-issues?category=ipo",
        "Past": "https://www.nseindia.com/api/public-past-issues"
    }

    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
    except Exception as e:
        print(f"NSE Session Error: {e}")
        return {}

    ipo_data_dict = {}
    for status, url in endpoints.items():
        try:
            resp = session.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data:
                ipo_data_dict[status] = pd.DataFrame(data)
        except Exception as e:
            print(f"⚠️ Failed to fetch {status} IPOs from NSE: {e}")
            ipo_data_dict[status] = pd.DataFrame()

    def _safe_select(df, desired_cols):
        return df[[col for col in desired_cols if col in df.columns]].copy()

    # ── Clean CURRENT IPOs ──────────────────────────────────────────────
    if 'Current' in ipo_data_dict and not ipo_data_dict['Current'].empty:
        df = ipo_data_dict['Current']
        # Extract UI columns before renaming
        df["_UI_Company_Name"] = df.get("companyName", "")
        df["_UI_Symbol"] = df.get("symbol", "")
        
        # Sort by start date descending
        if "issueStartDate" in df.columns:
            df["_sort_date"] = pd.to_datetime(df["issueStartDate"], errors="coerce")
            df = df.sort_values(by="_sort_date", ascending=False).drop(columns=["_sort_date"])
        
        # Format noOfSharesOffered
        if "noOfSharesOffered" in df.columns:
            # Convert scientific notation string to int, then format with commas
            df["noOfSharesOffered"] = pd.to_numeric(df["noOfSharesOffered"], errors="coerce").apply(lambda x: f"{int(x):,}" if pd.notnull(x) else "")

        # Rename columns
        rename_map = {
            "companyName": "Company Name",
            "symbol": "Symbol",
            "series": "Security type",
            "issuePrice": "issuePrice",
            "issueStartDate": "Issue Start Date",
            "issueEndDate": "Issue End Date",
            "status": "Status",
            "noOfSharesOffered": "No of Shares Offered"
        }
        df.rename(columns=rename_map, inplace=True)

        # Select and order columns
        desired_cols = ["Company Name", "Symbol", "Security type", "issuePrice", "Issue Start Date", "Issue End Date", "Status", "No of Shares Offered"]
        # Keep internal UI columns
        final_cols = [c for c in desired_cols if c in df.columns] + ["_UI_Company_Name", "_UI_Symbol"]
        ipo_data_dict['Current'] = df[[c for c in final_cols if c in df.columns]].copy()

    # ── Clean UPCOMING IPOs ─────────────────────────────────────────────
    if 'Upcoming' in ipo_data_dict and not ipo_data_dict['Upcoming'].empty:
        df = ipo_data_dict['Upcoming']
        df["_UI_Company_Name"] = df.get("companyName", "")
        df["_UI_Symbol"] = df.get("symbol", "")
        
        if "issueStartDate" in df.columns:
            df["_sort_date"] = pd.to_datetime(df["issueStartDate"], errors="coerce")
            df = df.sort_values(by="_sort_date", ascending=True).drop(columns=["_sort_date"])
            
        rename_map = {
            "companyName": "Company Name",
            "symbol": "Symbol",
            "series": "Security Type",
            "issuePrice": "Issue Price",
            "issueStartDate": "ISSUE START DATE",
            "issueEndDate": "ISSUE END DATE",
            "status": "STATUS",
            "issueSize": "ISSUE SIZE"
        }
        df.rename(columns=rename_map, inplace=True)
        
        desired_cols = ["Company Name", "Symbol", "Security Type", "Issue Price", "ISSUE START DATE", "ISSUE END DATE", "STATUS", "ISSUE SIZE"]
        final_cols = [c for c in desired_cols if c in df.columns] + ["_UI_Company_Name", "_UI_Symbol"]
        ipo_data_dict['Upcoming'] = df[[c for c in final_cols if c in df.columns]].copy()

    # ── Clean PAST IPOs ─────────────────────────────────────────────────
    if 'Past' in ipo_data_dict and not ipo_data_dict['Past'].empty:
        df = ipo_data_dict['Past']
        
        # Determine internal UI names before dropping anything
        name_col = None
        if 'companyName' in df.columns and 'company' in df.columns:
            df['_UI_Company_Name'] = df['company'].fillna(df['companyName'])
        elif 'company' in df.columns:
            df['_UI_Company_Name'] = df['company']
        elif 'companyName' in df.columns:
            df['_UI_Company_Name'] = df['companyName']
        else:
            df['_UI_Company_Name'] = ""

        df["_UI_Symbol"] = df.get("symbol", "")
        
        if "ipoStartDate" in df.columns:
            df["_sort_date"] = pd.to_datetime(df["ipoStartDate"], errors="coerce")
            df = df.sort_values(by="_sort_date", ascending=False).drop(columns=["_sort_date"])

        rename_map = {
            "company": "Company Name",
            "symbol": "Symbol",
            "securityType": "Security Type",
            "issuePrice": "Issue Price",
            "priceRange": "Price Range",
            "ipoStartDate": "IPO START DATE",
            "ipoEndDate": "IPO END DATE",
            "listingDate": "Listing Date"
        }
        df.rename(columns=rename_map, inplace=True)
        
        desired_cols = ["Company Name", "Symbol", "Security Type", "Issue Price", "Price Range", "IPO START DATE", "IPO END DATE", "Listing Date"]
        final_cols = [c for c in desired_cols if c in df.columns] + ["_UI_Company_Name", "_UI_Symbol"]
        ipo_data_dict['Past'] = df[[c for c in final_cols if c in df.columns]].copy()

    return ipo_data_dict





# ==============================================================================
# NSE IPO Detail + RHP URL helpers
# ==============================================================================

def fetch_nse_ipo_detail(symbol: str, series: str = "EQ") -> dict:
    """
    Calls: https://www.nseindia.com/api/ipo-detail?symbol=SYMBOL&series=EQ
    Returns the full issueInfo dict including RHP zip URL, or empty dict on failure.
    Requires an NSE session cookie (established via homepage visit).
    """
    if not symbol:
        return {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
    url = (
        f"https://www.nseindia.com/api/ipo-detail"
        f"?symbol={symbol}&series={series}"
    )
    session = requests.Session()
    try:
        # Establish NSE session cookie by visiting the homepage first
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[ipo_fetcher] fetch_nse_ipo_detail({symbol}) failed: {exc}")
        return {}


def get_rhp_url_from_nse(symbol: str) -> str:
    """
    Returns the NSE archives zip URL for a symbol's RHP, or None.
    Strategy:
      1. Direct URL check (no auth needed):
         https://nsearchives.nseindia.com/content/ipo/RHP_{SYMBOL}.zip
      2. Fallback to /api/ipo-detail → parse issueInfo.dataList for RHP link.
    """
    if not symbol:
        return None

    # Try 1: Direct URL (no session needed — just a HEAD check)
    direct_url = (
        f"https://nsearchives.nseindia.com/content/ipo/RHP_{symbol}.zip"
    )
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.nseindia.com/",
        }
        resp = requests.head(direct_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            print(f"[ipo_fetcher] Direct NSE zip URL confirmed: {direct_url}")
            return direct_url
    except Exception:
        pass

    # Try 2: /api/ipo-detail (needs NSE session)
    detail = fetch_nse_ipo_detail(symbol)
    for item in detail.get("issueInfo", {}).get("dataList", []):
        title = item.get("title", "").lower()
        if "herring" in title or "rhp" in title:
            link = item.get("value", "")
            if link:
                print(f"[ipo_fetcher] Found RHP link via NSE detail API: {link}")
                return link

    return None