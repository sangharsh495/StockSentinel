-- ============================================================
-- StockSentinel Database Schema v2 — Research & Intelligence Tables
-- ============================================================

-- Daily News Ratings (1–10 scale)
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

-- IPO Deep-Dive Research Cache
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

-- Stock Screener ML Cache
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
