-- ============================================================
-- StockSentinel Database Schema
-- PostgreSQL on Neon.tech (Free Tier — 0.5GB)
-- ============================================================

-- 13,000+ stocks (NSE + BSE + NYSE + NASDAQ)
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

-- Dividend calendar
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

-- IPO pipeline
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

-- News + ML sentiment
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
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_sentiment ON news(sentiment);
CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);

-- Watchlist (per device)
CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(100) NOT NULL,
    stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(device_id, stock_id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_device ON watchlist(device_id);

-- FCM tokens for push notifications
CREATE TABLE IF NOT EXISTS fcm_tokens (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(100) UNIQUE NOT NULL,
    fcm_token TEXT NOT NULL,
    platform VARCHAR(10) DEFAULT 'android',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Job run log (track scheduler health)
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

-- Enable trigram extension for fuzzy search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
