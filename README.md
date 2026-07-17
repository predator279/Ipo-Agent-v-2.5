<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Streamlit-1.30+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white" />
  <img src="https://img.shields.io/badge/LangChain-🦜-1C3C3C?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Groq-LLaMA_3.3_70B-F55036?style=for-the-badge" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" />
</p>

<h1 align="center">📈 IPO Analysis Agent</h1>

<p align="center">
  <strong>AI-powered Indian IPO research platform — from RHP download to investment-grade analysis in one click.</strong>
</p>

<p align="center">
  <em>Live NSE data • Automated RHP/DRHP extraction • Multi-source sentiment • Deep-dive RAG chatbot</em>
</p>

---

## 🎬 Demo

https://github.com/user-attachments/assets/0bf86099-331b-4f11-b2d5-f36b7cc8c502

---

## 🚀 What is IPO Analysis Agent?

**IPO Analysis Agent** is an end-to-end, AI-powered platform that automates the entire IPO research workflow for Indian markets. Instead of manually reading 500+ page Red Herring Prospectuses and scouring news sites, this tool does it all in under a minute:

1. **Fetches live IPO data** from NSE (Current, Upcoming & Past IPOs)
2. **Downloads & parses** the official RHP/DRHP documents from SEBI & ipopremium.in
3. **Extracts 40+ structured parameters** (financials, valuation, risks, management, etc.) using parallel RAG queries
4. **Runs multi-source sentiment analysis** aggregating Tavily, Reddit, and Google News
5. **Provides a conversational chatbot** to ask any question about the prospectus

---

## ✨ Features

### 🏦 Live IPO Market Dashboard
- Real-time data from **NSE India APIs**
- Separate views for **Current**, **Upcoming**, and **Past** IPOs
- Subscription status, price bands, and listing details

### 📊 Comprehensive Analysis Dashboard
| Section | What's Extracted |
|---------|-----------------|
| **Basic Info** | Issue size, price band, market cap, lot size, face value, exchange |
| **Business Overview** | Business model, revenue streams, competitive moat, TAM/SAM, geographic presence |
| **Financials (3-Year)** | Revenue, EBITDA, PAT, margins, EPS, cash flow — with interactive Plotly charts |
| **Balance Sheet** | Total assets/liabilities, net worth, D/E ratio, current ratio, working capital |
| **Return Ratios** | ROE, ROCE, ROA |
| **Valuation** | P/E, P/B, EV/EBITDA + peer comparison table |
| **Objects of Issue** | Fund utilization breakdown with donut chart |
| **Management** | Key management personnel, promoters, litigations |
| **Risk Factors** | Top 8-10 risk factors extracted and summarised |
| **Sector KPIs** | Auto-detected sector-specific metrics (Tech → ARR/MRR, BFSI → NPA/CASA, etc.) |

### 📡 Multi-Source Sentiment Analysis
- **Tavily Search API** — high-quality financial news with full content
- **Reddit** — retail investor discussions from r/IndiaInvestments, r/IndianStockMarket
- **Google News RSS** — mainstream media headlines
- **Grey Market Premium (GMP)** — auto-extracted from sources
- Sentiment gauge (0-5 scale) with positives/negatives breakdown

### 💬 Deep-Dive RAG Chatbot
- **Hybrid retrieval**: BM25 (keyword) + ChromaDB (semantic) with Ensemble Retriever
- **MMR diversity** to avoid redundant chunks
- **Table-aware**: reads markdown tables and extracts exact numbers
- **History-aware**: maintains conversational context across questions
- Quick-question buttons for common queries

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                 │
│  ┌──────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ Live IPO │  │ Analysis         │  │ Chat (RAG)    │  │
│  │ Market   │  │ Dashboard        │  │ Deep-Dive     │  │
│  └────┬─────┘  └────────┬─────────┘  └───────┬───────┘  │
│       │                 │                     │          │
├───────┼─────────────────┼─────────────────────┼──────────┤
│       ▼                 ▼                     ▼          │
│  ipo_fetcher.py   ipo_extractor.py     chatbot_agent.py  │
│  (NSE API)        (Parallel RAG        (Hybrid BM25 +    │
│                    Extraction)          Semantic RAG)     │
│                         │                     │          │
│                         ▼                     ▼          │
│               sentiment_agent.py       document_processor│
│               (Tavily + Reddit +       (pdfplumber +     │
│                Google News)             PyMuPDF)         │
│                                               │          │
│                                               ▼          │
│                                        rhp_agent.py      │
│                                        (SEBI + ipopremium│
│                                         PDF downloader)  │
│                                               │          │
│                                               ▼          │
│                                        ChromaDB          │
│                                        (Vector Store)    │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
IPO-Analysis-Agent/
├── app.py                  # Main Streamlit application (v3 — full dashboard)
├── chatbot_agent.py        # Hybrid RAG chain (BM25 + semantic + MMR)
├── ipo_extractor.py        # Parallel structured data extraction (40+ fields)
├── ipo_fetcher.py          # Live NSE India API integration
├── sentiment_agent.py      # Multi-source sentiment (Tavily, Reddit, Google News)
├── rhp_agent.py            # RHP/DRHP downloader (SEBI + ipopremium.in)
├── document_processor.py   # PDF parser (pdfplumber + PyMuPDF, table-aware)
├── master_agent.py         # LangChain tool-calling agent orchestrator
├── agents/
│   ├── __init__.py
│   └── tools.py            # Shared LLM factory (Groq / OpenRouter / HuggingFace)
├── .streamlit/
│   └── secrets.toml        # API keys (not committed)
├── ipo_vectorstores/       # Cached ChromaDB vector stores (auto-generated)
├── ipo_analysis_cache/     # Cached extraction results (auto-generated)
├── SEBI_RHPs/              # Downloaded SEBI documents (auto-generated)
└── README.md
```

---

## ⚡ Quick Start

### Prerequisites

- **Python 3.10+**
- **Groq API Key** (free at [console.groq.com](https://console.groq.com)) — *required*
- **Tavily API Key** (free 1000/mo at [app.tavily.com](https://app.tavily.com)) — *optional, improves sentiment*

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/ipo-analysis-agent.git
cd ipo-analysis-agent
```

### 2. Create Virtual Environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install streamlit langchain langchain-groq langchain-chroma langchain-huggingface langchain-community
pip install chromadb sentence-transformers plotly pandas
pip install pdfplumber PyMuPDF praw feedparser beautifulsoup4 rapidfuzz requests
```

### 4. Configure API Keys

Create `.streamlit/secrets.toml`:

```toml
GROQ_API_KEY = "gsk_your_key_here"
TAVILY_API_KEY = "tvly-your_key_here"       # Optional
```

Or enter them directly in the app sidebar.

### 5. Run the App

```bash
streamlit run app.py
```

The app will open at `http://localhost:8501` 🎉

---

## 🔧 How It Works

### Step 1: Document Acquisition
The **RHP Agent** (`rhp_agent.py`) searches for the company's prospectus across:
- **ipopremium.in** — fuzzy name matching + CDN download
- **SEBI** — official filings scraper with robust retry/resume logic

Downloads are streamed with **resume support** (HTTP Range requests) for large 25+ MB PDFs.

### Step 2: Smart Document Processing
The **Document Processor** (`document_processor.py`) uses a dual-engine approach:
- **pdfplumber** — extracts tables as clean markdown
- **PyMuPDF** — fast text extraction for narrative content
- Boilerplate pages (TOC, disclaimers) are auto-skipped
- Important sections (financials, risks) are flagged for retrieval boosting

### Step 3: Parallel Structured Extraction
The **IPO Extractor** (`ipo_extractor.py`) fires **11 parallel RAG queries** against the vectorstore, each targeting a specific data category (basic info, financials, risks, etc.). Results are merged into a structured `IPOProfile` dataclass with 40+ fields.

### Step 4: Multi-Source Sentiment
The **Sentiment Agent** (`sentiment_agent.py`) aggregates market buzz from 3 sources, then runs LLM analysis to produce a structured sentiment score (0-5), GMP estimates, and bull/bear case points.

### Step 5: Interactive Analysis
Everything is rendered in a **dark-themed Streamlit dashboard** with:
- Interactive **Plotly charts** (Revenue/PAT bars, Margin trends, Objects of Issue donut)
- Sentiment **gauge visualisation**
- **Conversational RAG chatbot** for deep-dive questions

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Streamlit, Plotly |
| **LLM** | Groq (LLaMA 3.3 70B Versatile) |
| **Embeddings** | HuggingFace `all-MiniLM-L6-v2` |
| **Vector DB** | ChromaDB |
| **Retrieval** | LangChain (Hybrid BM25 + Semantic + MMR) |
| **PDF Parsing** | pdfplumber + PyMuPDF |
| **Sentiment Data** | Tavily API, Reddit (PRAW), Google News RSS |
| **Document Source** | SEBI, ipopremium.in |
| **Market Data** | NSE India APIs |

---

## 📋 Supported LLM Providers

| Provider | Model | How to Use |
|----------|-------|-----------|
| **Groq** *(recommended)* | LLaMA 3.3 70B | Set `GROQ_API_KEY` |
| **HuggingFace** | Mistral 7B Instruct | Set `HUGGINGFACEHUB_API_TOKEN` |
| **OpenRouter** | Any model | Set `OPENROUTER_API_KEY` |

---

## 🤝 Contributing

Contributions are welcome! Here are some ideas:

- [ ] Add more data sources (BSE, Moneycontrol scraper)
- [ ] Historical IPO performance tracking
- [ ] Subscription status live tracker
- [ ] PDF upload support (for unlisted/pre-filing companies)
- [ ] Deploy to Streamlit Cloud

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📜 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## ⚠️ Disclaimer

This tool is for **educational and research purposes only**. It does not constitute financial advice. Always do your own due diligence before making investment decisions. The accuracy of extracted data depends on the quality of the source documents and LLM outputs.

---

<p align="center">
  <strong>Built with ❤️ for the Indian investor community</strong>
</p>

<p align="center">
  <a href="#-demo">Demo</a> •
  <a href="#-features">Features</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-contributing">Contributing</a>
</p>
