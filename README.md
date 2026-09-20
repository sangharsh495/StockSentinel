# 🛡️ StockSentinel — AI Equity Research & Market Intelligence Platform

> **Grade-1 Secured, Institutional-Grade Market Research & Intelligence Engine**  
> Designed for serious investors and analysts seeking real-time catalyst discovery, multi-factor stock screening, monthly dividend tracking, IPO viability analysis, and 1–10 rated news impact scores.

---

## 📑 Table of Contents
1. [Architecture Overview](#-architecture-overview)
2. [Folder Organization](#-folder-organization)
3. [Grade-1 Security Standards](#-grade-1-security-standards)
4. [Cryptographic Integrity Seal](#-cryptographic-integrity-seal)
5. [Configuration & What You Need to Add](#-configuration--what-you-need-to-add)
6. [Quickstart Guide](#-quickstart-guide)

---

## 🏛️ Architecture Overview

```
                        ┌───────────────────────────────────────────────┐
                        │      StockSentinel Android App (Native Java)   │
                        │  - Research Screener (A+ to D Ratings)        │
                        │  - Weekly Movers Radar                        │
                        │  - Dividend Calendar (Monthly Navigator)      │
                        │  - IPO Deep-Dive Reports                      │
                        │  - Top 10 Daily News (1–10 Impact Rated)      │
                        │  - Institutional Equity Research Detail       │
                        └───────────────────────┬───────────────────────┘
                                                │ REST API (HTTPS / TLS 1.3)
                                                ▼
                        ┌───────────────────────────────────────────────┐
                        │         FastAPI Backend Intelligence Engine    │
                        │  - Live Quote Streamer (yfinance + in-memory) │
                        │  - Multi-Factor Screener ML Engine            │
                        │  - Gemini 2.5 Flash / Groq Llama-3 AI Engine  │
                        │  - Monthly Dividend Yield & Rating Engine     │
                        │  - IPO Research & Valuation Engine            │
                        │  - Daily News Impact Ranker (1–10 Scale)      │
                        │  - OWASP Security Headers & Rate Limiter      │
                        └───────────────────────┬───────────────────────┘
                                                │
                                                ▼
                        ┌───────────────────────────────────────────────┐
                        │       Neon.tech Serverless PostgreSQL         │
                        │  - 13,000+ Stocks Master Table                │
                        │  - Trigram Fuzzy Search Extension             │
                        │  - Daily News Ratings & Impact Junctions      │
                        │  - IPO Deep-Dive Research Cache               │
                        │  - Multi-Factor Screener Cache                │
                        └───────────────────────────────────────────────┘
```

---

## 📂 Folder Organization

The repository has been structured cleanly into uniform, standardized modules:

```
StockSentinel/
├── .gitignore                       # Master root gitignore (macOS, Python, Android, Secrets)
├── README.md                        # Complete platform documentation & setup guide
├── CHECKSUMS.sha256                 # Cryptographic SHA-256 seal manifest of all source files
├── PROJECT_INTEGRITY_SEAL.json      # Structured JSON integrity manifest with Master Root Hash
│
├── scripts/                         # Project maintenance & security integrity tools
│   ├── seal_project.py              # Computes SHA-256 digests and locks repository state
│   └── verify_integrity.py          # Validates workspace against cryptographic seal
│
├── backend/                         # High-performance FastAPI backend
│   ├── .env                         # Environment credentials (DO NOT COMMIT)
│   ├── .env.example                 # Documented template for all configuration keys
│   ├── .gitignore                   # Python & virtual environment ignore rules
│   ├── Dockerfile                   # Production container definition
│   ├── requirements.txt             # Python dependencies (FastAPI, Groq, Gemini, yfinance, etc.)
│   ├── schema.sql                   # Baseline database schema (v1)
│   ├── schema_v2.sql                # Research tables migration (Daily ratings, IPO cache, Screener)
│   ├── schema_complete.sql          # Unified full database schema (v1 + v2)
│   └── app/
│       ├── config.py                # Centralized settings & environment loader
│       ├── database.py              # Async PostgreSQL connection pool (asyncpg)
│       ├── main.py                  # API entrypoint & middleware configuration
│       ├── security.py              # OWASP security headers & Token Bucket rate limiter
│       ├── api/                     # REST API endpoints
│       │   ├── analyst.py           # Screener, Dividend calendar, IPO reports, Daily news rating
│       │   ├── stocks.py            # Live quotes, indices streaming, stock profiles
│       │   ├── news.py              # RSS feeds, sentiment analysis, impact junction
│       │   ├── dividends.py         # Dividend announcements
│       │   ├── ipos.py              # Upcoming & active IPO tracker
│       │   └── watchlist.py         # Device-level watchlist management
│       ├── ml/                      # Machine learning & AI research engines
│       │   ├── ai_analyst.py        # Institutional Equity Research Generator (Thesis, Scorecard)
│       │   ├── stock_screener.py    # 4-Pillar Composite Screener (Score 0-100, Grades A+ to D)
│       │   ├── live_quote_service.py# Real-time streaming quote engine with cache & DB sync
│       │   ├── dividend_tracker.py  # Monthly dividend calendar & 1-5 star consistency engine
│       │   ├── ipo_researcher.py    # AI prospectus analyzer & investment verdict
│       │   ├── news_ranker.py       # Daily 1-10 impact rating & catalyst badge generator
│       │   ├── weekly_movers.py     # High-conviction catalyst detector
│       │   └── chart_service.py     # Lightweight candlestick & sparkline data generator
│       ├── notifications/           # Firebase Cloud Messaging push notifications
│       ├── scheduler/               # APScheduler background tasks & self-ping keep-alive
│       └── scrapers/                # NSE/BSE announcements & Moneycontrol scrapers
│
└── android/                         # Native Android client (Java 17, Material Design 3)
    ├── .gitignore                   # Android build, gradle & keystore ignore rules
    ├── build.gradle                 # Project build configuration
    ├── settings.gradle              # Module includes & repository definitions
    └── app/
        ├── build.gradle             # App dependencies (Retrofit, OkHttp, Material, MPAndroidChart)
        └── src/main/
            ├── AndroidManifest.xml  # Permissions, exported safety, Network Security Config
            ├── res/
            │   ├── xml/
            │   │   └── network_security_config.xml # Strict TLS 1.3/1.2; cleartext blocked
            │   ├── layout/          # Premium dark-mode layouts for all research features
            │   └── values/          # Color tokens, styles, dark theme
            └── java/com/stocksentinel/
                ├── data/api/        # Retrofit API clients & models
                └── ui/              # User interface fragments & activities
                    ├── home/        # Weekly Movers Radar & AI Top 10 Research Picks
                    ├── stocks/      # Research Screener (Filters: All, Top AI, Catalysts, Dividends)
                    ├── stockdetail/ # Institutional Equity Research Report UI
                    ├── dividends/   # Monthly Dividend Calendar (Prev/Next navigation, Yield %, Stars)
                    ├── ipos/        # IPO tracker & AI Deep-Dive Report Activity
                    └── news/        # Daily Top 10 Ranked News (1–10 Impact score, Verdict badges)
```

---

## 🔐 Grade-1 Security Standards

StockSentinel complies with modern Grade-1 enterprise application security:

1. **Cryptographic Integrity Sealing**: Every source file has a verified SHA-256 fingerprint checked against a Master Root Hash.
2. **Strict Network Security**:
   - `network_security_config.xml` strictly blocks all unencrypted cleartext HTTP traffic.
   - Enforces TLS 1.3 / TLS 1.2 for all outbound API communication.
3. **OWASP API Protection**:
   - `Content-Security-Policy`: Restricts scripts, objects, and framing (`frame-ancestors 'none'`).
   - `X-Frame-Options: DENY`: Complete clickjacking prevention.
   - `X-Content-Type-Options: nosniff`: Prevents MIME-confusion attacks.
   - `Strict-Transport-Security (HSTS)`: Forces HTTPS for 1 year with subdomains and preload.
   - `Referrer-Policy: strict-origin-when-cross-origin`.
4. **Token Bucket Rate Limiting**: In-memory token bucket middleware (120 requests/min per IP) preventing DDoS and scraping abuse.
5. **Android Hardening**:
   - `android:allowBackup="false"` (prevents ADB physical extraction of cached tokens).
   - Internal activities marked with `android:exported="false"` to block unauthorized inter-process intents.

---

## 🔏 Cryptographic Integrity Seal

To ensure that the codebase is completely untampered, genuine, and authentic, the repository includes a cryptographic seal:

### To Verify Project Integrity:
```bash
python3 scripts/verify_integrity.py
```
*Expected Output:*
```
🔒 StockSentinel Grade-1 Cryptographic Integrity Verification
✅ Verified Matching: [All Files]
🎉 STATUS: 100% INTEGRITY VERIFIED (Grade-1 Secured & Untampered)
```

### To Re-Seal After Authorized Modifications:
```bash
python3 scripts/seal_project.py
```

---

## 🔑 Configuration & What You Need to Add

To run StockSentinel with all capabilities, configure `backend/.env`.

### 1. What You Already Have Configured ✅
- **`DATABASE_URL`**: Connected to Neon Serverless PostgreSQL.
- **`GEMINI_API_KEY`**: Configured (Google Gemini AI Studio).
- **`GROQ_API_KEY`**: Configured (Groq Cloud Llama-3 API).
- **`DEBUG=true`**: Enabled for development.

### 2. What You Can Optionally Add 🛠️

| Key | Description | How to Obtain / Configure | Status |
|---|---|---|---|
| `FINNHUB_API_KEY` | US market live quotes & news fallback | Get a free key at [finnhub.io](https://finnhub.io/) (1-min signup). Paste key directly. | **Optional** (Indian market uses yfinance automatically) |
| `FIREBASE_CREDENTIALS` | Server-side push notification trigger | Download service account JSON from Firebase Console ➔ Project Settings ➔ Service Accounts. Place at `backend/firebase-credentials.json` or paste base64. | **Optional** (Needed only for mobile push alerts) |
| `RENDER_EXTERNAL_URL` | Self-ping keep-alive URL | Your deployed URL (e.g. `https://stocksentinel-api.onrender.com`). Prevents free instance from sleeping. | **Optional** (Needed when deploying to Render) |
| `google-services.json` | Android Firebase client config | Download from Firebase Console ➔ Add Android App ➔ place in `android/app/google-services.json`. | **Optional** (Needed only if using FCM on Android) |

---

## 🚀 Quickstart Guide

### 1. Apply Database Migration
Ensure all tables (including v2 research tables) are created in your PostgreSQL database:
```bash
cd backend
# Run via psql:
psql "$DATABASE_URL" -f schema_v2.sql
# Or run schema_complete.sql for a fresh database:
# psql "$DATABASE_URL" -f schema_complete.sql
```

### 2. Start the Backend API
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
API Documentation will be live at: `http://localhost:8000/docs`

### 3. Build & Run Android App
Open the `android/` folder in **Android Studio** or run via command line:
```bash
cd android
./gradlew compileDebugJavaWithJavac
```
Connect your physical device or emulator and run `Run 'app'`.

---

*StockSentinel — Engineered for Precision Market Intelligence.*
