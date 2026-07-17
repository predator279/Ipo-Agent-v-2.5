# document_processor.py  (v3 — smart TOC-based chunking, dual-pass, detailed progress)
#
# Key improvements over v2:
#   1. TOC detection: scans first 30 pages for section page numbers → skips 80% of useless pages
#   2. Dual-pass: Pass 1 = PyMuPDF (fast, 10s) on selected pages, detects table pages
#                 Pass 2 = pdfplumber ONLY on table-detected pages (~20-30% of selected pages)
#   3. Embedding batch size 256 (was 64) for faster ingest
#   4. Detailed progress bar with section names, page counts, pass labels
#   5. Still falls back to full-doc scan if TOC not found (≥3 sections)

import os
import re
import pdfplumber
import fitz  # PyMuPDF — fast text extraction
from typing import List, Optional
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ── tunables ─────────────────────────────────────────────────────────────────
NARRATIVE_CHUNK_SIZE    = 1000   # characters per narrative chunk
NARRATIVE_CHUNK_OVERLAP = 120
TABLE_MAX_ROWS_INLINE   = 60     # tables larger than this get truncated in the chunk

# Sections we want to prioritise (case-insensitive substring match on page text).
# Pages whose first 400 chars contain ANY of these are flagged as "important".
IMPORTANT_SECTION_HINTS = [
    "financial statements", "revenue", "profit", "ebitda", "balance sheet",
    "cash flow", "objects of the issue", "risk factors", "business overview",
    "industry overview", "key performance", "restated", "consolidated",
    "standalone", "utilisation of proceeds", "basis of allotment",
    "promoter", "management discussion", "litigation",
]

# Pages whose content is almost entirely boilerplate are SKIPPED.
SKIP_PAGE_HINTS = [
    "table of contents", "contents", "index", "this page is intentionally left blank",
    "disclaimer clause", "definition of technical", "abbreviations",
]

# TOC keywords → section tag mapping for smart page selection
TARGET_SECTIONS = {
    "business overview":       "business",
    "industry overview":       "industry",
    "our business":            "business",
    "risk factors":            "risks",
    "financial statements":    "financials",
    "restated financial":      "financials",
    "objects of the issue":    "objects",
    "utilisation of proceeds": "objects",
    "management discussion":   "mgmt",
    "basis of allotment":      "allotment",
    "promoters":               "promoters",
    "litigation":              "legal",
    "key performance":         "kpis",
}
# ─────────────────────────────────────────────────────────────────────────────


def _is_skip_page(text: str) -> bool:
    snippet = text[:600].lower()
    return any(hint in snippet for hint in SKIP_PAGE_HINTS)


def _is_important_page(text: str) -> bool:
    snippet = text[:400].lower()
    return any(hint in snippet for hint in IMPORTANT_SECTION_HINTS)


def _table_to_markdown(table: list) -> str:
    """Convert pdfplumber table (list-of-lists) to a compact markdown string."""
    if not table:
        return ""
    rows = []
    for i, row in enumerate(table):
        cleaned = [str(cell).strip() if cell is not None else "" for cell in row]
        rows.append("| " + " | ".join(cleaned) + " |")
        if i == 0:
            rows.append("|" + "|".join(["---"] * len(row)) + "|")
    return "\n".join(rows)


def _truncate_table_markdown(md: str, max_rows: int = TABLE_MAX_ROWS_INLINE) -> str:
    lines = md.split("\n")
    if len(lines) > max_rows + 2:
        kept = lines[: max_rows + 2]
        kept.append(f"... [{len(lines) - max_rows - 2} more rows truncated] ...")
        return "\n".join(kept)
    return md


# ── NEW: TOC detection ───────────────────────────────────────────────────────

def _detect_toc_sections(mupdf_pdf) -> dict:
    """
    Fast pass: scan first 30 pages for TOC-style lines like:
      "Risk Factors .............. 45"
    Returns: {section_tag: start_page_0indexed}
    Falls back to None (→ full scan) if <3 sections detected.
    """
    toc_pattern = re.compile(
        r'([A-Za-z ]{8,60})\s*[.·]{3,}\s*(\d{2,4})', re.IGNORECASE
    )
    section_pages = {}
    for pg_num in range(min(30, len(mupdf_pdf))):
        try:
            text = mupdf_pdf[pg_num].get_text("text")
        except Exception:
            continue
        for match in toc_pattern.finditer(text):
            title = match.group(1).strip().lower()
            try:
                page_num_from_toc = int(match.group(2))
            except ValueError:
                continue
            for keyword, tag in TARGET_SECTIONS.items():
                if keyword in title and tag not in section_pages:
                    section_pages[tag] = max(0, page_num_from_toc - 1)  # 0-indexed

    return section_pages if len(section_pages) >= 3 else None


def _get_pages_to_process(mupdf_pdf, toc_sections: dict) -> set:
    """
    Build set of page indices to process, based on TOC detection.
    Each section gets ±20 page buffer to catch overflow.
    Falls back to all pages if toc_sections is None.
    """
    if not toc_sections:
        return set(range(len(mupdf_pdf)))  # fallback: full document

    pages = set()
    section_starts = sorted(toc_sections.values())
    for i, start in enumerate(section_starts):
        end = section_starts[i + 1] if i + 1 < len(section_starts) else len(mupdf_pdf)
        for p in range(max(0, start - 5), min(len(mupdf_pdf), end + 20)):
            pages.add(p)
    return pages


def _page_likely_has_table(raw_text: str) -> bool:
    """
    Heuristic: does this page likely have a structured financial table?
    Checks for multiple numbers on a line or heavy spacing (column alignment).
    """
    lines = raw_text.split('\n')
    tabular_lines = sum(
        1 for line in lines
        if len(re.findall(r'\b\d[\d,.-]+\b', line)) >= 3   # 3+ numbers on one line
        or line.count('  ') >= 4                             # multiple double-spaces
    )
    return tabular_lines >= 3


# ── Main processing function (v3) ────────────────────────────────────────────

def process_pdf_with_pdfplumber(
    pdf_path: str,
    progress_callback=None,   # optional callable(fraction, message)
    max_pages: int = 0,       # 0 = no limit
) -> List[Document]:
    """
    Dual-pass approach for fast chunking of large RHP/DRHP PDFs:
      Pass 1: PyMuPDF scans TOC-selected pages (~10 sec), detects table pages
      Pass 2: pdfplumber runs ONLY on table-detected pages (~20-30% of selected)
    Returns a flat list of LangChain Document objects ready for embedding.
    """
    print(f"\n📄 Opening PDF: {pdf_path}")
    docs: List[Document] = []

    try:
        mupdf_pdf = fitz.open(pdf_path)
    except Exception as e:
        print(f"❌ Failed to open PDF with PyMuPDF: {e}")
        return []

    total_pages = len(mupdf_pdf)

    # ── TOC scan ──────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.02, f"📋 Scanning table of contents ({total_pages} pages)…")

    toc_sections = _detect_toc_sections(mupdf_pdf)
    pages_to_process = _get_pages_to_process(mupdf_pdf, toc_sections)

    # Apply max_pages cap if set
    if max_pages and max_pages < total_pages:
        pages_to_process = {p for p in pages_to_process if p < max_pages}

    if toc_sections:
        section_names = list(toc_sections.keys())
        if progress_callback:
            progress_callback(
                0.05,
                f"✅ Found {len(toc_sections)} sections "
                f"({len(pages_to_process)}/{total_pages} pages selected): "
                f"{', '.join(section_names)}"
            )
        print(f"✅ TOC detected — {len(toc_sections)} sections, "
              f"{len(pages_to_process)}/{total_pages} pages will be processed.")
    else:
        if progress_callback:
            progress_callback(
                0.05,
                f"⚠️ TOC not detected — full scan mode ({total_pages} pages)"
            )
        print(f"⚠️ TOC not detected — processing all {total_pages} pages.")

    # ── Pass 1: PyMuPDF fast text + table detection ───────────────────────────
    page_data = {}  # {page_num: {text: str, has_table: bool, important: bool}}
    sorted_pages = sorted(pages_to_process)
    n = len(sorted_pages)

    for i, page_num in enumerate(sorted_pages):
        if progress_callback and (i % 50 == 0 or i == n - 1):
            frac = 0.05 + (i / max(n, 1)) * 0.25  # 5% → 30%
            progress_callback(
                frac,
                f"🔍 Pass 1/2 — Scanning page {page_num + 1}/{total_pages} "
                f"({i + 1}/{n} selected pages)…"
            )
        try:
            raw_text = mupdf_pdf[page_num].get_text("text")
        except Exception:
            raw_text = ""

        if _is_skip_page(raw_text):
            continue

        page_data[page_num] = {
            "text":      raw_text,
            "has_table": _page_likely_has_table(raw_text),
            "important": _is_important_page(raw_text),
        }

    table_pages = [p for p, d in page_data.items() if d["has_table"]]
    if progress_callback:
        progress_callback(
            0.30,
            f"📊 Pass 1 complete — {len(table_pages)} table pages found "
            f"out of {len(page_data)} text pages"
        )
    print(f"✅ Pass 1 complete — {len(table_pages)} table pages out of {len(page_data)} text pages.")

    # ── Pass 2: pdfplumber on table pages only ────────────────────────────────
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=NARRATIVE_CHUNK_SIZE,
        chunk_overlap=NARRATIVE_CHUNK_OVERLAP,
    )

    if table_pages:
        try:
            plumber_pdf = pdfplumber.open(pdf_path)
            for j, page_num in enumerate(table_pages):
                if progress_callback and (j % 20 == 0 or j == len(table_pages) - 1):
                    frac = 0.30 + (j / max(len(table_pages), 1)) * 0.35  # 30% → 65%
                    progress_callback(
                        frac,
                        f"📋 Pass 2/2 — Extracting tables: page {page_num + 1} "
                        f"({j + 1}/{len(table_pages)} table pages)…"
                    )
                try:
                    pl_page = plumber_pdf.pages[page_num]
                    tables = pl_page.extract_tables()
                    for tbl in (tables or []):
                        md = _table_to_markdown(tbl)
                        if len(md.strip()) < 20:
                            continue
                        docs.append(Document(
                            page_content=f"[TABLE — page {page_num + 1}]\n"
                                         f"{_truncate_table_markdown(md)}",
                            metadata={
                                "page":      page_num + 1,
                                "type":      "table",
                                "important": page_data[page_num]["important"],
                                "source":    os.path.basename(pdf_path),
                            }
                        ))
                except Exception:
                    pass
            plumber_pdf.close()
        except Exception as e:
            print(f"⚠️ pdfplumber pass failed: {e}")

    # ── Narrative text chunks from all selected pages ─────────────────────────
    total_text_pages = len(page_data)
    for k, (page_num, data) in enumerate(page_data.items()):
        if progress_callback and (k % 50 == 0 or k == total_text_pages - 1):
            frac = 0.65 + (k / max(total_text_pages, 1)) * 0.15  # 65% → 80%
            progress_callback(
                frac,
                f"✍️ Chunking text — page {page_num + 1} ({k + 1}/{total_text_pages})…"
            )
        narrative = data["text"]
        narrative = re.sub(r"\n{3,}", "\n\n", narrative).strip()
        if len(narrative) > 80:
            chunks = text_splitter.create_documents(
                [narrative],
                metadatas=[{
                    "page":      page_num + 1,
                    "type":      "text",
                    "important": data["important"],
                    "source":    os.path.basename(pdf_path),
                }]
            )
            docs.extend(chunks)

    mupdf_pdf.close()

    table_count = sum(1 for d in docs if d.metadata.get("type") == "table")
    text_count  = sum(1 for d in docs if d.metadata.get("type") == "text")
    if progress_callback:
        progress_callback(0.80, f"✅ Parsing complete — {len(docs)} total chunks "
                                f"({table_count} tables, {text_count} text)")
    print(f"\n✅ Parsing complete:\n"
          f"   Table chunks: {table_count}\n"
          f"   Text chunks:  {text_count}\n"
          f"   Total docs:   {len(docs)}")
    return docs


# ── Backwards-compatible alias so chatbot_agent.py import doesn't break ──────
def process_pdf_with_unstructured(pdf_path: str) -> List[Document]:
    """
    Drop-in replacement for the old unstructured-based processor.
    chatbot_agent.py calls this name; we just forward to the new implementation.
    """
    return process_pdf_with_pdfplumber(pdf_path)


# ── Optional: on-demand LLM summarisation of a single table chunk ─────────────
def summarize_table_chunk(table_markdown: str, llm) -> str:
    """
    Call this at query time (not ingest time) when you want a richer
    interpretation of a specific table chunk retrieved by the RAG chain.
    """
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    prompt = ChatPromptTemplate.from_template(
        "You are an expert financial analyst. "
        "Provide a concise, data-rich summary of the following table. "
        "Extract key figures, trends, and important labels. "
        "Do not merely describe the table — summarise its core insight.\n\n"
        "Table:\n{table_markdown}"
    )
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"table_markdown": table_markdown})