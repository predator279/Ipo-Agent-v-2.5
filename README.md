<p align="center">
  <img src="https://img.shields.io/badge/Azure%20Functions-0062AD?style=for-the-badge&logo=microsoft-azure&logoColor=white" />
  <img src="https://img.shields.io/badge/GitHub%20Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/LangChain-🦜-1C3C3C?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Qdrant-Cloud-EB2A4E?style=for-the-badge&logo=qdrant&logoColor=white" />
  <img src="https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white" />
</p>

<h1 align="center">📈 IPO Analysis Agent</h1>

<p align="center">
  <strong>An end-to-end, production-grade Retrieval-Augmented Generation (RAG) platform designed to automate the analysis of Indian IPOs (Initial Public Offerings).</strong>
</p>

<p align="center">
  <a href="https://ipo.supreme.codes"><strong>Try the Live Website: ipo.supreme.codes</strong></a>
</p>

---

## 🚀 What is IPO Analysis Agent?

**IPO Analysis Agent** is an end-to-end, AI-powered platform that automates the entire IPO research workflow for Indian markets. Instead of manually reading 500+ page Red Herring Prospectuses (RHPs) and scouring news sites, this tool does it all:

1. **Fetches live IPO data** from NSE (Current, Upcoming & Past IPOs).
2. **Downloads & parses** the official RHP/DRHP documents directly from the **National Stock Exchange (NSE)** (with SEBI as a reliable fallback).
3. **Extracts 40+ structured parameters** (financials, valuation, risks, management, etc.) using parallel RAG queries.
4. **Runs multi-source sentiment analysis** aggregating Tavily, Reddit, and Google News.
5. **Provides SOU AI** — a conversational chatbot to ask any question about the prospectus. *(Etymology: "Sou" means an old coin in French, perfectly capturing my vision of a money-focused, highly efficient, and low-cost AI RAG system).*

I built this project to demonstrate a complete lifecycle of a complex AI application: from automated data ingestion and vector embeddings to a production-ready cloud deployment powered by **Microsoft Azure Functions** and orchestrated via **GitHub Actions**.

---

## 🎬 Demo

**Live Deployment**: [https://ipo.supreme.codes](https://ipo.supreme.codes)

https://github.com/user-attachments/assets/0bf86099-331b-4f11-b2d5-f36b7cc8c502

---

## ✨ Features

### 🏦 Live IPO Market Dashboard
- Real-time data from **NSE India**.
- Separate views for **Current**, **Upcoming**, and **Past** IPOs.
- Subscription status, price bands, and listing details.

### 📊 Comprehensive Analysis Dashboard
- **Basic Info**: Issue size, price band, market cap, lot size, face value.
- **Financials (3-Year)**: Revenue, EBITDA, PAT, margins, EPS — with interactive Plotly charts.
- **Return Ratios & Valuation**: ROE, ROCE, ROA, P/E, P/B, EV/EBITDA + peer comparison table.
- **Risk Factors & Management**: Top 8-10 risk factors summarized, key personnel, and litigations.

### 💬 Deep-Dive RAG Chatbot: SOU AI
- **Hybrid Retrieval**: BM25 (keyword) + ChromaDB/Qdrant (semantic) search.
- **Table-Aware Parsing**: Accurately reads markdown tables from PDFs and extracts exact numbers.
- **History-Aware**: Maintains conversational context across follow-up questions.

---

## 🏗️ Architecture (Azure & GitHub Powered)

This is a fully scalable, cloud-native architecture deployed on **Microsoft Azure** with CI/CD handled by **GitHub Actions**:

```text
┌─────────────────────────────────────────────────────────────┐
│                   Static Frontend (HTML/JS)                 │
│                 Hosted on Live Web Server                   │
└──────┬───────────────────────────────────────────────┬──────┘
       │ HTTP GET /ipos                                │ HTTP POST /chat
       ▼                                               ▼
┌─────────────────────────────────────────────────────────────┐
│                Azure Function App (Backend)                 │
│  (Deployed automatically via GitHub Actions: deploy-backend)│
│                                                             │
│  ┌──────────────────┐               ┌────────────────────┐  │
│  │ Profile Fetcher  │               │ SOU AI Engine      │  │
│  └────────┬─────────┘               └─────────┬──────────┘  │
└───────────┼───────────────────────────────────┼─────────────┘
            │                                   │
            ▼                                   ▼
┌───────────────────────┐            ┌────────────────────────┐
│      Supabase         │            │      Qdrant Cloud      │
│ (PostgreSQL Cache)    │            │     (Vector Store)     │
│ Cached IPO Profiles   │            │ RHP Document Embeddings│
└───────────────────────┘            └────────────────────────┘
            ▲                                   ▲
            │                                   │
┌───────────┴───────────────────────────────────┴─────────────┐
│                 Nightly Precache Script                     │
│ (ipo_fetcher.py -> rhp_agent.py -> ipo_extractor.py)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 How It Works (and Engineering Tradeoffs)

1. **Document Acquisition**: The system identifies new IPOs and downloads their RHPs primarily from the **NSE**, utilizing **SEBI** as a fallback.
2. **Parsing & Chunking**: Heavy 500+ page PDFs are parsed using `pdfplumber` (for complex tables) and `PyMuPDF` (for fast text).
3. **Parallel RAG Extraction**: 11 parallel RAG queries target specific data categories (financials, risks) to build a structured JSON profile.
4. **Caching & Vector Storage**: The JSON profile is stored in **Supabase** for instant retrieval, and the text chunks are embedded and stored in **Qdrant Cloud** for SOU AI.

> **💡 Engineering Tradeoff: Data Quality vs. CI/CD Automation**  
> Initially, the data ingestion pipeline was meant to run entirely via automated **GitHub Actions**. However, the official National Stock Exchange (NSE) endpoints utilize a Strict Web Application Firewall (WAF) that actively blocks known datacenter IPs (like GitHub Actions runners). 
> 
> *The Decision*: I chose **Data Quality & Reliability** over full automation. Rather than scraping unreliable third-party aggregators to bypass the firewall, I utilize a manually triggered nightly precache script from a clean residential IP. This ensures I get the most accurate, official data directly from the source, pushing updates to Supabase and Qdrant for the Azure frontend to seamlessly consume.

---

## 📁 Project Structure

```text
IPO-Analysis-Agent/
├── api/                    # Azure Function App Backend (Production API)
│   ├── function_app.py     # HTTP triggers and RAG chatbot endpoint
│   └── requirements.txt    
├── static/                 # Production Static Frontend (HTML/JS/CSS)
├── .github/workflows/      # CI/CD (deploy-backend, deploy-frontend)
├── ipo_extractor.py        # Parallel structured data extraction
├── ipo_fetcher.py          # NSE API integration
├── document_processor.py   # PDF parser (pdfplumber + PyMuPDF)
├── chatbot_agent.py        # LangChain setup (SOU AI)
├── rhp_agent.py            # RHP downloader (NSE & SEBI)
├── app.py                  # Local Streamlit UI (for local prototyping & debugging)
└── README.md
```

---

## ⚡ Quick Start (Local Run)

You can run this entire architecture on your local machine! To protect the live infrastructure and avoid hitting rate limits, the repository requires you to configure your own free-tier databases and API keys.

### Prerequisites
- Python 3.10+
- A free **Groq**, **Gemini**, or **Mistral** API Key
- A free **Supabase** Project (PostgreSQL)
- A free **Qdrant Cloud** Cluster

### 1. Clone & Install
```bash
git clone https://github.com/your-username/ipo-analysis-agent.git
cd ipo-analysis-agent
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
```

### 2. Configure Your Environment
Create a `.env` file (copy from `.env.example`) and add your own credentials:
```ini
GROQ_API_KEY="your_groq_key"
GEMINI_API_KEY="your_gemini_key"
MISTRAL_API_KEY="your_mistral_key"
SUPABASE_URL="your_supabase_url"
SUPABASE_KEY="your_supabase_key"
QDRANT_URL="your_qdrant_url"
QDRANT_API_KEY="your_qdrant_key"
```

### 3. Run the Precache Script
To fetch data from the NSE and load it into your own Supabase and Qdrant databases:
```bash
# Extract data, download RHPs, and push embeddings
python ipo_extractor.py
```

### 4. Start the Application
You can run the full backend locally using Azure Functions Core Tools:
```bash
cd api
func start
```
Alternatively, for a quick UI test without Azure, run the local Streamlit dashboard:
```bash
streamlit run app.py
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Cloud Hosting** | Microsoft Azure Function Apps |
| **Automation** | GitHub Actions |
| **Frontend** | HTML/JS/CSS (Production) + Streamlit (Local) |
| **LLM Inference** | Groq (LLaMA 3.3 70B), Google Gemini, Mistral |
| **Vector DB** | Qdrant Cloud |
| **SQL Database** | Supabase (PostgreSQL) |
| **Orchestration** | LangChain |

---

## 📋 Supported LLM Providers

| Provider | Model | Usage |
|----------|-------|-----------|
| **Groq** *(Fastest)* | LLaMA 3.3 70B | Great for parallel extraction and sentiment. |
| **Gemini** | Gemini 2.0 Flash | Excellent context window for heavy RAG chat (SOU AI). |
| **Mistral** | Mistral 7B | Reliable alternative for structured extraction tasks. |

---

## 🤝 Contributing

Contributions are highly welcome! I am actively looking for help in the following areas:

- [ ] **Automated Data Ingestion**: Finding reliable ways to bypass the NSE firewall (e.g., residential proxies) so the precache script can return to a fully automated GitHub Action.
- [ ] **RAG Latency**: Optimizing the semantic search and LLM inference time.
- [ ] **UI/UX**: Enhancing the static frontend dashboard.
- [ ] **New Data Sources**: Integrating BSE data or additional sentiment streams.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## ⚠️ Disclaimer

This tool is for **educational and portfolio demonstration purposes only**. It does not constitute financial advice. Always perform your own due diligence before making investment decisions. The accuracy of extracted data depends on the quality of the source documents and LLM outputs.

---

## 📜 License

This project is licensed under the **MIT License**.
