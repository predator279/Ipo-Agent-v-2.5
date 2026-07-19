# rhp_agent.py  (v2 — robust large-file download with resume + retry)
#
# Changes vs v1:
#   • download_pdf() now streams into a temp file, then renames — so a failed
#     download never leaves a corrupt partial file that looks "already exists".
#   • Chunk size raised from 8 KB → 512 KB (much faster on large PDFs).
#   • Per-chunk timeout via a read-timeout tuple (connect=15, read=60).
#   • IncompleteRead / ChunkedEncodingError are caught and retried up to 3×,
#     using HTTP Range requests to resume from where the download broke.
#   • Content-Length check: if the saved file is smaller than the server says,
#     we re-download automatically.
#   • ipopremium.in: switched from GET-JSON (405) to HTML scrape of the page.
#   • SEBI: connection timeout raised to 60 s, read timeout 120 s.

import os
import re
import json
import time
import zipfile
import requests
import pdfplumber

from bs4 import BeautifulSoup
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from rapidfuzz import process, fuzz
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate

from agents.tools import get_llm, invoke_model

# ── constants ────────────────────────────────────────────────────────────────
IPOPREMIUM_LIST_URL = "https://www.ipopremium.in"  # HTML page, not JSON API
DOWNLOAD_CHUNK_SIZE = 512 * 1024  # 512 KB per chunk
DOWNLOAD_MAX_RETRIES = 4
DOWNLOAD_BACKOFF = 3  # seconds between retry attempts
SEBI_CONNECT_TIMEOUT = 15
SEBI_READ_TIMEOUT = 180  # large PDFs can be slow


# ─────────────────────────────────────────────────────────────────────────────


# ==============================================================================
# HELPER — build a resilient requests.Session
# ==============================================================================
def _make_session(max_retries: int = 4, backoff: float = 1.5) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ==============================================================================
# HELPER — robust streaming download with resume
# ==============================================================================
def _download_file_robust(
        url: str,
        dest_path: str,
        session: Optional[requests.Session] = None,
        headers: Optional[dict] = None,
) -> bool:
    """
    Downloads `url` to `dest_path`.
    - Streams in 512 KB chunks.
    - On IncompleteRead / ChunkedEncodingError, resumes from the byte offset
      already written (HTTP Range request) up to DOWNLOAD_MAX_RETRIES times.
    - Writes to a .tmp file first; renames to dest_path only on success.
    - Returns True on success, False on permanent failure.
    """
    if session is None:
        session = _make_session()
    if headers is None:
        headers = dict(_DEFAULT_HEADERS)

    tmp_path = dest_path + ".tmp"
    bytes_written = 0

    # If a previous partial download exists, try to resume from it
    if os.path.exists(tmp_path):
        bytes_written = os.path.getsize(tmp_path)
        print(f"   ↻ Resuming partial download from byte {bytes_written:,}")

    for attempt in range(1, DOWNLOAD_MAX_RETRIES + 1):
        try:
            req_headers = dict(headers)
            if bytes_written > 0:
                req_headers["Range"] = f"bytes={bytes_written}-"

            with session.get(
                    url,
                    headers=req_headers,
                    stream=True,
                    timeout=(SEBI_CONNECT_TIMEOUT, SEBI_READ_TIMEOUT),
            ) as resp:
                # 206 = partial content (resume), 200 = full content
                if resp.status_code not in (200, 206):
                    print(f"   ✗ HTTP {resp.status_code} for {url}")
                    return False

                # If server doesn't support range, restart from scratch
                if resp.status_code == 200 and bytes_written > 0:
                    bytes_written = 0

                content_type = resp.headers.get("Content-Type", "")
                if "pdf" not in content_type and "octet-stream" not in content_type:
                    # Some SEBI PDFs are served as application/octet-stream
                    print(f"   ⚠️  Unexpected Content-Type '{content_type}' — trying anyway.")

                server_total = resp.headers.get("Content-Length") or \
                               resp.headers.get("Content-Range", "").split("/")[-1]
                try:
                    server_total = int(server_total)
                except (ValueError, TypeError):
                    server_total = None

                mode = "ab" if bytes_written > 0 else "wb"
                with open(tmp_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            bytes_written += len(chunk)

            # Verify size
            actual_size = os.path.getsize(tmp_path)
            if server_total and actual_size < server_total:
                raise requests.exceptions.ChunkedEncodingError(
                    f"Incomplete: got {actual_size:,} of {server_total:,} bytes"
                )

            # Success — promote tmp → final
            os.replace(tmp_path, dest_path)
            print(f"   ✅ Saved {actual_size / 1_048_576:.1f} MB → {dest_path}")
            return True

        except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
        ) as exc:
            print(f"   ⚠️  Attempt {attempt}/{DOWNLOAD_MAX_RETRIES} failed: {exc}")
            if attempt < DOWNLOAD_MAX_RETRIES:
                wait = DOWNLOAD_BACKOFF * attempt
                print(f"   ⏳ Retrying in {wait}s…")
                time.sleep(wait)
            else:
                print(f"   ❌ All {DOWNLOAD_MAX_RETRIES} attempts failed for {url}")
                # Clean up corrupt tmp
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                return False

    return False


# ==============================================================================
# SOURCE 1 — ipopremium.in  (HTML scrape, not JSON API)
# ==============================================================================
def _fetch_ipopremium_names() -> list:
    """
    Scrapes IPO names from the ipopremium.in homepage table.
    The old JSON API endpoint returns 405; the HTML page is public.
    """
    try:
        session = _make_session()
        resp = session.get(
            IPOPREMIUM_LIST_URL,
            headers=_DEFAULT_HEADERS,
            timeout=(10, 20),
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        names = []
        for tag in soup.find_all(["td", "a", "span", "div"]):
            text = tag.get_text(strip=True)
            # Heuristic: IPO names tend to be 3-60 chars, contain "Limited" / "Ltd" often
            if 5 < len(text) < 80 and not text.isdigit():
                names.append(text)
        # Deduplicate while preserving order
        return list(dict.fromkeys(names))
    except Exception as exc:
        print(f"⚠️ [RHP Agent] ipopremium.in scrape failed: {exc}")
        return []


def _try_ipopremium_download(ipo_name: str, dest_folder: str) -> Optional[str]:
    """
    Tries to download an RHP/DRHP PDF from ipopremium's asset CDN.
    Returns local file path on success, None otherwise.
    """
    names = _fetch_ipopremium_names()
    if not names:
        return None

    match_result = process.extractOne(ipo_name, names, scorer=fuzz.QRatio)
    if not match_result or match_result[1] < 80:
        print(
            f"   No strong match on ipopremium.in for '{ipo_name}' (best score: {match_result[1] if match_result else 'N/A'})")
        return None

    best_match = match_result[0]
    print(f"   ipopremium match: '{best_match}' (score={match_result[1]})")

    # Asset URLs use a 4-digit numeric code embedded in the name
    code_match = re.search(r"(\d{4,})", best_match)
    if not code_match:
        return None
    code = code_match.group(1)

    os.makedirs(dest_folder, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", ipo_name)

    session = _make_session()
    for doc_type in ["rhp", "drhp"]:
        url = f"https://assets.ipopremium.in/images/ipo/{code}_{doc_type}.pdf"
        dest = os.path.join(dest_folder, f"{safe_name}_{doc_type}.pdf")
        print(f"   Trying: {url}")
        if _download_file_robust(url, dest, session=session):
            return dest

    return None


# ==============================================================================
# SOURCE 2 — SEBI scraper  (fallback)
# ==============================================================================
class SEBIScraper:
    BASE = "https://www.sebi.gov.in"
    SEARCH_URL = BASE + "/sebiweb/home/HomeAction.do"

    def __init__(self, folder: str = "SEBI_RHPs"):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.session = _make_session(max_retries=3, backoff=2)

    def _safe_filename(self, name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]", "_", name)

    def search_company(self, company_name: str) -> list:
        params = {
            "doListing": "yes", "sid": "3", "ssid": "15",
            "smid": "11", "search": company_name,
        }
        r = self.session.get(
            self.SEARCH_URL, params=params,
            headers=_DEFAULT_HEADERS,
            timeout=(SEBI_CONNECT_TIMEOUT, SEBI_READ_TIMEOUT),
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/filings/public-issues/" in href:
                results.append(urljoin(self.BASE, href))
        return list(dict.fromkeys(results))

    def extract_pdfs(self, filing_url: str) -> list:
        r = self.session.get(
            filing_url, headers=_DEFAULT_HEADERS,
            timeout=(SEBI_CONNECT_TIMEOUT, SEBI_READ_TIMEOUT),
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        pdfs = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf") or "attachdocs" in href or "file=" in href:
                candidate = urljoin(self.BASE, href)
                parsed = urlparse(candidate)
                qs = parse_qs(parsed.query)
                pdfs.append(unquote(qs["file"][0]) if "file" in qs else candidate)
        for tag in soup.find_all(["iframe", "embed"], src=True):
            src = tag["src"]
            if "file=" in src:
                candidate = urljoin(self.BASE, src)
                qs = parse_qs(urlparse(candidate).query)
                pdfs.append(unquote(qs["file"][0]) if "file" in qs else candidate)
        return list(dict.fromkeys(pdfs))

    def download_all(self, company_name: str) -> list:
        filings = self.search_company(company_name)
        if not filings:
            print(f"   ❌ No SEBI filings found for '{company_name}'")
            return []

        results = []
        for filing_url in filings:
            print(f"   Filing page: {filing_url}")
            pdf_urls = self.extract_pdfs(filing_url)
            for pdf_url in pdf_urls:
                # Resolve final URL
                parsed = urlparse(pdf_url)
                qs = parse_qs(parsed.query)
                resolved_url = unquote(qs["file"][0]) if "file" in qs else pdf_url

                filename = os.path.basename(urlparse(resolved_url).path)
                safe_name = self._safe_filename(f"{company_name.replace(' ', '_')}__{filename}")
                dest_path = os.path.join(self.folder, safe_name)

                if os.path.exists(dest_path):
                    size_mb = os.path.getsize(dest_path) / 1_048_576
                    print(f"   ℹ️  Already exists ({size_mb:.1f} MB): {dest_path}")
                    results.append({"local_path": dest_path})
                    continue

                print(f"   Downloading: {resolved_url}")
                success = _download_file_robust(
                    resolved_url, dest_path, session=self.session
                )
                if success:
                    results.append({
                        "company": company_name,
                        "filing_url": filing_url,
                        "pdf_url": resolved_url,
                        "local_path": dest_path,
                    })
                # Continue trying other PDFs even if one fails
        return results


# ==============================================================================
# HELPERS — file size and document type filtering
# ==============================================================================

# Minimum file size to be considered a real RHP/DRHP (not a cover page / addendum)
MIN_REAL_DOC_BYTES = 2 * 1024 * 1024  # 2 MB

# Keywords in the SEBI filing page URL that indicate it's a full prospectus.
# We prefer these over amendment/addendum pages.
PREFERRED_URL_KEYWORDS = ["rhp", "drhp", "red-herring", "prospectus"]
SKIP_URL_KEYWORDS = ["addendum", "amendment", "corrigendum", "errata", "notice"]


def _score_filing_url(url: str) -> int:
    """
    Returns a priority score for a SEBI filing URL.
    Higher = more likely to be the main RHP/DRHP we want.
    """
    url_lower = url.lower()
    if any(kw in url_lower for kw in SKIP_URL_KEYWORDS):
        return 0
    if any(kw in url_lower for kw in PREFERRED_URL_KEYWORDS):
        return 2
    return 1  # unknown — neutral


def _filter_and_sort_results(results: list) -> list:
    """
    Given a list of {local_path, ...} dicts, remove tiny files (addenda / cover pages)
    and sort by file size descending so the largest (most complete) doc comes first.
    """
    valid = []
    for r in results:
        path = r.get("local_path", "")
        if not os.path.exists(path):
            continue
        size = os.path.getsize(path)
        if size < MIN_REAL_DOC_BYTES:
            print(f"   ⚠️  Skipping small file ({size / 1024:.0f} KB) — likely addendum: {path}")
            continue
        r["_size"] = size
        valid.append(r)
    # Largest files first (full RHP > DRHP > everything else)
    valid.sort(key=lambda x: x["_size"], reverse=True)
    return valid


# ==============================================================================
# PUBLIC API — find and download ALL PDFs, return list of paths
# ==============================================================================
# ==============================================================================
# NSE ZIP — new primary download source
# ==============================================================================

def _extract_zip_pdfs(zip_path: str, dest_folder: str) -> list:
    """
    Extracts a downloaded NSE RHP zip and returns a list of dicts for all PDFs found.
    Skips tiny files (<2MB). Returns list sorted by 'rhp' in filename first, then largest-first.
    """
    extracted = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            for name in z.namelist():
                if name.lower().endswith('.pdf'):
                    out_path = os.path.join(dest_folder, os.path.basename(name))
                    z.extract(name, dest_folder)
                    # Handle nested dirs in zip
                    actual_out = os.path.join(dest_folder, name)
                    if os.path.exists(actual_out) and actual_out != out_path:
                        os.makedirs(os.path.dirname(out_path), exist_ok=True)
                        os.replace(actual_out, out_path)
                    if os.path.exists(out_path):
                        size = os.path.getsize(out_path)
                        if size >= MIN_REAL_DOC_BYTES:
                            extracted.append({"local_path": out_path, "_size": size, "_basename": os.path.basename(out_path).lower()})
    except Exception as exc:
        print(f"   ⚠️  Zip extraction error: {exc}")
        
    # Sort by: contains 'rhp' (True first, so 0, else 1), then by size (largest first)
    return sorted(extracted, key=lambda x: (0 if 'rhp' in x.get("_basename", "") else 1, -x["_size"]))


def _try_nse_zip_download(symbol: str, dest_folder: str) -> Optional[str]:
    """
    Tries to download the NSE RHP zip for a symbol and extracts the main PDF.
    URL pattern: https://nsearchives.nseindia.com/content/ipo/RHP_{SYMBOL}.zip
    Returns local PDF path on success, None on failure.
    """
    if not symbol:
        return None

    zip_url = (
        f"https://nsearchives.nseindia.com/content/ipo/RHP_{symbol}.zip"
    )
    os.makedirs(dest_folder, exist_ok=True)
    zip_path = os.path.join(dest_folder, f"RHP_{symbol}.zip")

    session = _make_session()
    headers = {**_DEFAULT_HEADERS, "Referer": "https://www.nseindia.com/"}
    print(f"   Trying NSE archives zip: {zip_url}")
    success = _download_file_robust(zip_url, zip_path, session=session, headers=headers)
    if not success:
        return None

    pdfs = _extract_zip_pdfs(zip_path, dest_folder)
    if pdfs:
        print(f"   ✅ NSE zip extracted: {pdfs[0]['local_path']} "
              f"({pdfs[0]['_size'] / 1_048_576:.1f} MB)")
        return pdfs[0]["local_path"]
    return None


# ==============================================================================
# PUBLIC API — find and download ALL PDFs, return list of paths
# ==============================================================================
def find_and_download_pdf(ipo_name: str, symbol: str = "") -> Optional[str]:
    """
    Backwards-compatible single-path wrapper around find_and_download_all_pdfs().
    Returns the path of the LARGEST downloaded PDF (most likely the full RHP),
    or None if nothing was found.
    """
    paths = find_and_download_all_pdfs(ipo_name, symbol=symbol)
    return paths[0] if paths else None


def find_and_download_all_pdfs(
    ipo_name: str,
    symbol: str = "",
    rhp_url: str = "",       # pre-fetched direct RHP link (e.g. from Upstox)
) -> list:
    """
    Downloads ALL relevant RHP/DRHP PDFs for an IPO.
    Waterfall order (per approved plan):
      Source 1: Upstox direct RHP link (if pre-fetched by ipo_fetcher)
      Source 2: NSE Archives zip (direct URL, no auth)
      Source 3: NSE /api/ipo-detail (session-cookie based)
      Source 4: SEBI scraper (fallback for older IPOs)
    Returns a list of local file paths sorted largest-first.
    """
    print(f"\n--- [RHP Agent] Finding all PDFs for '{ipo_name}' ---")
    collected = []
    dest_folder = "IPO_Documents"
    os.makedirs(dest_folder, exist_ok=True)

    # Derive symbol from ipo_name if not passed (uppercase, no spaces)
    if not symbol:
        # Crude heuristic: take first word uppercased
        symbol = ipo_name.split()[0].upper() if ipo_name else ""

    # ── Source 1: Upstox direct RHP link ─────────────────────────────────
    if rhp_url:
        print(f"→ Trying Upstox direct RHP link: {rhp_url[:80]}…")
        ext = os.path.splitext(rhp_url.split("?")[0])[-1].lower()
        if ext in (".zip", ".pdf") or not ext:
            session = _make_session()
            headers = {**_DEFAULT_HEADERS, "Referer": "https://www.upstox.com/"}
            if ext == ".zip" or "zip" in rhp_url.lower():
                zip_path = os.path.join(dest_folder, f"Upstox_{symbol}.zip")
                ok = _download_file_robust(rhp_url, zip_path, session=session, headers=headers)
                if ok:
                    pdfs = _extract_zip_pdfs(zip_path, dest_folder)
                    collected.extend(pdfs)
            else:
                dest = os.path.join(dest_folder, f"Upstox_{symbol}_RHP.pdf")
                ok = _download_file_robust(rhp_url, dest, session=session, headers=headers)
                if ok and os.path.exists(dest):
                    size = os.path.getsize(dest)
                    if size >= MIN_REAL_DOC_BYTES:
                        collected.append({"local_path": dest, "_size": size})
                        print(f"   ✅ Upstox direct: {dest} ({size / 1_048_576:.1f} MB)")
        if collected:
            pass  # skip remaining sources if we already have the doc
    else:
        print("   No Upstox RHP URL available.")

    # ── Source 2: NSE archives direct zip ────────────────────────────────
    if not collected:
        print("→ Trying NSE archives zip (source 2)…")
        nse_pdf = _try_nse_zip_download(symbol, dest_folder)
        if nse_pdf and os.path.exists(nse_pdf):
            size = os.path.getsize(nse_pdf)
            collected.append({"local_path": nse_pdf, "_size": size})
            print(f"   ✅ NSE zip: {nse_pdf} ({size / 1_048_576:.1f} MB)")
        else:
            print("   No NSE zip found.")

    # ── Source 3: NSE /api/ipo-detail link ───────────────────────────────
    if not collected:
        print("→ Trying NSE /api/ipo-detail (source 3)…")
        try:
            from ipo_fetcher import fetch_nse_ipo_detail
            detail = fetch_nse_ipo_detail(symbol)
            for item in detail.get("issueInfo", {}).get("dataList", []):
                title = item.get("title", "").lower()
                if "herring" in title or "rhp" in title:
                    link = item.get("value", "")
                    if link and link.endswith(".zip"):
                        zip_path = os.path.join(dest_folder, f"NSE_detail_{symbol}.zip")
                        session = _make_session()
                        headers = {**_DEFAULT_HEADERS, "Referer": "https://www.nseindia.com/"}
                        ok = _download_file_robust(link, zip_path, session=session, headers=headers)
                        if ok:
                            pdfs = _extract_zip_pdfs(zip_path, dest_folder)
                            for p in pdfs:
                                collected.append(p)
                    elif link and link.endswith(".pdf"):
                        dest = os.path.join(dest_folder, f"NSE_detail_{symbol}.pdf")
                        session = _make_session()
                        headers = {**_DEFAULT_HEADERS, "Referer": "https://www.nseindia.com/"}
                        ok = _download_file_robust(link, dest, session=session, headers=headers)
                        if ok:
                            size = os.path.getsize(dest)
                            if size >= MIN_REAL_DOC_BYTES:
                                collected.append({"local_path": dest, "_size": size})
        except Exception as exc:
            print(f"   ⚠️  NSE detail API failed: {exc}")

    # ── Source 4: SEBI scraper ────────────────────────────────────────────
    if not collected:
        print("-> Trying SEBI scraper...")
        try:
            scraper = SEBIScraper(folder="SEBI_RHPs")
            filings = scraper.search_company(ipo_name)
            filings.sort(key=_score_filing_url, reverse=True)

            for filing_url in filings:
                print(f"   Filing page: {filing_url}")
                pdf_urls = scraper.extract_pdfs(filing_url)
                for pdf_url in pdf_urls:
                    parsed = urlparse(pdf_url)
                    qs = parse_qs(parsed.query)
                    resolved = unquote(qs["file"][0]) if "file" in qs else pdf_url
                    filename = os.path.basename(urlparse(resolved).path)
                    safe_name = scraper._safe_filename(
                        f"{ipo_name.replace(' ', '_')}__{filename}"
                    )
                    dest_path = os.path.join(scraper.folder, safe_name)

                    if os.path.exists(dest_path):
                        size = os.path.getsize(dest_path)
                        print(f"   ℹ️  Already exists ({size / 1_048_576:.1f} MB): {dest_path}")
                    else:
                        print(f"   Downloading: {resolved}")
                        ok = _download_file_robust(resolved, dest_path, session=scraper.session)
                        if not ok:
                            continue
                        size = os.path.getsize(dest_path)

                    if size < MIN_REAL_DOC_BYTES:
                        print(f"   ⚠️  Too small ({size / 1024:.0f} KB) — likely addendum, skipping.")
                        continue

                    collected.append({"local_path": dest_path, "_size": size})

        except Exception as exc:
            print(f"   \u274c SEBI scraper exception: {exc}")

    # ── Source 4: ipopremium.in (last resort) ────────────────────────────
    if not collected:
        print("\u2192 Trying ipopremium.in (last resort)...")
        path = _try_ipopremium_download(ipo_name, dest_folder=dest_folder)
        if path and os.path.exists(path):
            size = os.path.getsize(path)
            if size >= MIN_REAL_DOC_BYTES:
                collected.append({"local_path": path, "_size": size})
                print(f"   \u2705 ipopremium: {path} ({size / 1_048_576:.1f} MB)")
            else:
                print(f"   \u26a0️  ipopremium file too small ({size / 1024:.0f} KB), ignoring.")

    # Deduplicate by path, sort largest first
    seen = set()
    final = []
    for r in sorted(collected, key=lambda x: x.get("_size", 0), reverse=True):
        p = r["local_path"]
        if p not in seen:
            seen.add(p)
            final.append(p)

    if final:
        print(f"\n\u2705 [RHP Agent] {len(final)} usable document(s) found:")
        for p in final:
            mb = os.path.getsize(p) / 1_048_576
            print(f"   {mb:.1f} MB  {p}")
    else:
        print("\u274c [RHP Agent] No usable documents found.")

    return final



# ==============================================================================
# OPTIONAL — LLM analysis of the downloaded RHP (unchanged from v1)
# ==============================================================================
def analyze_rhp(ipo_name: str, symbol: str = "") -> dict | None:
    """
    Finds the RHP PDF, extracts pages, runs OCR, and extracts standard JSON.
    Returns the parsed dictionary.
    """
    local_path = find_and_download_pdf(ipo_name, symbol=symbol)
    if not local_path:
        print("❌ [RHP Agent] No document found for analysis.")
        return None

    try:
        print("[RHP Agent] Loading PDF for analysis…")
        loader = PyPDFLoader(local_path)
        documents = loader.load()
        full_text = "\n\n".join([doc.page_content for doc in documents])
        splitter = RecursiveCharacterTextSplitter(chunk_size=5000, chunk_overlap=300)
        chunks = splitter.split_text(full_text)

        llm = get_llm(temperature=0.1)
        prompt = ChatPromptTemplate.from_template(
            """You are an expert financial analyst. Analyse the RHP text and return ONLY valid JSON.

JSON Schema:
{{
    "company_overview": "<business summary>",
    "financial_summary": {{
        "revenue_fy_latest": "<value>",
        "profit_after_tax_fy_latest": "<value>",
        "key_financial_trends": "<text>"
    }},
    "risk_factors": ["<risk1>", "<risk2>", "<risk3>"]
}}

CONTEXT:
---
{context}
---"""
        )

        partials = []
        for i, chunk in enumerate(chunks[:10]):
            print(f"[RHP Agent] Processing chunk {i + 1}/{min(len(chunks), 10)}…")
            res = invoke_model(llm, prompt | llm, context=chunk)
            partials.append(res)

        merge_prompt = ChatPromptTemplate.from_template(
            "Merge these partial analyses into one consistent JSON summary "
            "(company_overview, financial_summary, risk_factors):\n{partials}"
        )
        merged = invoke_model(llm, merge_prompt | llm, partials="\n".join(partials))
        try:
            data = json.loads(
                str(merged).strip().replace("```json", "").replace("```", "")
            )
        except Exception:
            data = {"error": "Invalid JSON", "raw_output": str(merged)}

        results_folder = "analysis_results"
        os.makedirs(results_folder, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", ipo_name)
        file_path = os.path.join(results_folder, f"{safe_name}_rhp_analysis.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"✅ [RHP Agent] Analysis saved to {file_path}")
        return data

    except Exception as exc:
        print(f"❌ [RHP Agent] Analysis failed: {exc}")
        return None