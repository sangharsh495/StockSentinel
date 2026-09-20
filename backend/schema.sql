-- ============================================================
-- StockSentinel Complete Database Schema (v1 + v2)
-- PostgreSQL on Neon.tech (Compatible with Free Tier & Production)
-- ============================================================

-- Enable trigram extension for high-performance fuzzy search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 1. Stocks Master Table (NSE + BSE + NYSE + NASDAQ)
CREATE TABLE IF NOT EXISTS stocks (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    name VARCHAR(200) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    market VARCHAR(5) NOT NULL,
    sector VARCHAR(100),
    industry VARCHAR(100),
    current_price DECIMAL(12,4),
    prev_close DECIMAL(12,4),
    day_high DECIMAL(12,4),
    day_low DECIMAL(12,4),
    open_price DECIMAL(12,4),
    volume BIGINT,
    market_cap BIGINT,
    change_pct DECIMAL(8,4),
    currency VARCHAR(3) DEFAULT 'INR',
    last_updated TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(symbol, exchange)
);

CREATE INDEX IF NOT EXISTS idx_stocks_symbol ON stocks(symbol);
CREATE INDEX IF NOT EXISTS idx_stocks_exchange ON stocks(exchange);
CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market);
CREATE INDEX IF NOT EXISTS idx_stocks_name_trgm ON stocks USING gin (LOWER(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_stocks_symbol_trgm ON stocks USING gin (LOWER(symbol) gin_trgm_ops);

-- 2. Dividend Calendar & History
CREATE TABLE IF NOT EXISTS dividends (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    company_name VARCHAR(200),
    dividend_type VARCHAR(20),
    amount DECIMAL(10,4),
    ex_date DATE,
    record_date DATE,
    payment_date DATE,
    status VARCHAR(20) DEFAULT 'upcoming',
    notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dividends_ex_date ON dividends(ex_date);
CREATE INDEX IF NOT EXISTS idx_dividends_status ON dividends(status);
CREATE INDEX IF NOT EXISTS idx_dividends_symbol ON dividends(symbol);

-- 3. IPO Pipeline & Tracking
CREATE TABLE IF NOT EXISTS ipos (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(200) NOT NULL,
    market VARCHAR(5) NOT NULL,
    exchange VARCHAR(10),
    price_band_low DECIMAL(10,2),
    price_band_high DECIMAL(10,2),
    lot_size INTEGER,
    issue_size VARCHAR(100),
    open_date DATE,
    close_date DATE,
    listing_date DATE,
    gmp DECIMAL(10,2),
    subscription_status JSONB,
    status VARCHAR(20) DEFAULT 'upcoming',
    notified BOOLEAN DEFAULT FALSE,
    source VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(company_name, market, open_date)
);

CREATE INDEX IF NOT EXISTS idx_ipos_status ON ipos(status);
CREATE INDEX IF NOT EXISTS idx_ipos_open_date ON ipos(open_date);
CREATE INDEX IF NOT EXISTS idx_ipos_market ON ipos(market);

-- 4. News Master Table + ML Impact Scoring
CREATE TABLE IF NOT EXISTS news (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    url VARCHAR(1000) UNIQUE,
    source VARCHAR(100) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    sentiment VARCHAR(10),
    sentiment_score DECIMAL(5,4),
    related_symbols TEXT[],
    category VARCHAR(50),
    summary TEXT,
    impact_score DECIMAL(5,4),
    affected_stocks JSONB DEFAULT '[]'::jsonb,
    dividend_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Upgrade migrations for existing news table
ALTER TABLE news ADD COLUMN IF NOT EXISTS impact_score DECIMAL(5,4);
ALTER TABLE news ADD COLUMN IF NOT EXISTS affected_stocks JSONB DEFAULT '[]'::jsonb;
ALTER TABLE news ADD COLUMN IF NOT EXISTS dividend_detected BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_sentiment ON news(sentiment);
CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);
CREATE INDEX IF NOT EXISTS idx_news_dividend ON news(dividend_detected) WHERE dividend_detected = TRUE;
CREATE INDEX IF NOT EXISTS idx_news_impact ON news(impact_score DESC NULLS LAST);

-- 5. News ↔ Stock Impact Junction Table
CREATE TABLE IF NOT EXISTS news_stock_impact (
    id SERIAL PRIMARY KEY,
    news_id INTEGER REFERENCES news(id) ON DELETE CASCADE,
    stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    impact_direction VARCHAR(10),  -- BULLISH / BEARISH / NEUTRAL
    impact_score DECIMAL(5,4),
    reason VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(news_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_nsi_news ON news_stock_impact(news_id);
CREATE INDEX IF NOT EXISTS idx_nsi_stock ON news_stock_impact(stock_id);
CREATE INDEX IF NOT EXISTS idx_nsi_symbol ON news_stock_impact(symbol);

-- 6. User Watchlist (Per Device)
CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(100) NOT NULL,
    stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(device_id, stock_id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_device ON watchlist(device_id);

-- 7. Push Notification Tokens
CREATE TABLE IF NOT EXISTS fcm_tokens (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(100) UNIQUE NOT NULL,
    fcm_token TEXT NOT NULL,
    platform VARCHAR(10) DEFAULT 'android',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 8. Scheduler Execution & Health Logs
CREATE TABLE IF NOT EXISTS job_runs (
    id SERIAL PRIMARY KEY,
    job_name VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    records_processed INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    finished_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_job_runs_name ON job_runs(job_name);
CREATE INDEX IF NOT EXISTS idx_job_runs_started ON job_runs(started_at DESC);

-- 9. Daily News Impact Ratings (1–10 Scale)
CREATE TABLE IF NOT EXISTS daily_news_ratings (
    id SERIAL PRIMARY KEY,
    news_id INTEGER REFERENCES news(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    url VARCHAR(1000),
    source VARCHAR(100),
    rating DECIMAL(3,1) NOT NULL,  -- 1.0 to 10.0
    impact_level VARCHAR(20) NOT NULL, -- CRITICAL, HIGH, MEDIUM, LOW
    headline_verdict VARCHAR(255),
    sentiment VARCHAR(10),
    related_symbols TEXT[],
    ranking_date DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dnr_date ON daily_news_ratings(ranking_date DESC);
CREATE INDEX IF NOT EXISTS idx_dnr_rating ON daily_news_ratings(rating DESC);

-- 10. AI-Powered IPO Deep-Dive Research Cache
CREATE TABLE IF NOT EXISTS ipo_research_reports (
    id SERIAL PRIMARY KEY,
    ipo_id INTEGER REFERENCES ipos(id) ON DELETE CASCADE,
    company_name VARCHAR(200) NOT NULL,
    symbol VARCHAR(20),
    market VARCHAR(5) NOT NULL,
    report JSONB NOT NULL,
    verdict VARCHAR(50),
    score DECIMAL(4,1),
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(company_name, market)
);

CREATE INDEX IF NOT EXISTS idx_irr_company ON ipo_research_reports(company_name);

-- 11. Multi-Factor Stock Screener ML Cache
CREATE TABLE IF NOT EXISTS stock_screener_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    composite_score DECIMAL(5,2) NOT NULL,
    research_grade VARCHAR(5) NOT NULL,
    action VARCHAR(20) NOT NULL,
    fundamental_score DECIMAL(5,2),
    technical_score DECIMAL(5,2),
    catalyst_score DECIMAL(5,2),
    dividend_score DECIMAL(5,2),
    key_reason VARCHAR(255),
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(symbol, exchange)
);

CREATE INDEX IF NOT EXISTS idx_ssc_score ON stock_screener_cache(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_ssc_grade ON stock_screener_cache(research_grade);
