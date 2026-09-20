-- ============================================================
-- StockSentinel Phase 1 Schema — Buffett Upgrade
-- Fundamental Data, Technical Indicators, Valuation Framework
-- ============================================================

-- 12. Stock Financials (Quarterly + Annual P&L, Balance Sheet, Cash Flow)
CREATE TABLE IF NOT EXISTS stock_financials (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    period_type VARCHAR(10) NOT NULL,  -- 'annual' or 'quarterly'
    period_end DATE NOT NULL,

    -- Income Statement
    revenue BIGINT,
    net_income BIGINT,
    ebitda BIGINT,
    operating_income BIGINT,
    interest_expense BIGINT,
    eps DECIMAL(10,2),

    -- Balance Sheet
    total_assets BIGINT,
    total_debt BIGINT,
    total_equity BIGINT,
    cash_and_equivalents BIGINT,
    current_assets BIGINT,
    current_liabilities BIGINT,

    -- Cash Flow
    operating_cash_flow BIGINT,
    free_cash_flow BIGINT,
    capex BIGINT,

    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(symbol, exchange, period_type, period_end)
);

CREATE INDEX IF NOT EXISTS idx_sf_symbol ON stock_financials(symbol);
CREATE INDEX IF NOT EXISTS idx_sf_period ON stock_financials(period_type, period_end DESC);

-- 13. Stock Ratios (Cached Computed Financial Ratios)
CREATE TABLE IF NOT EXISTS stock_ratios (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(10) NOT NULL,

    -- Valuation
    pe_ratio DECIMAL(10,2),
    pb_ratio DECIMAL(10,2),
    peg_ratio DECIMAL(10,2),
    ev_ebitda DECIMAL(10,2),
    forward_pe DECIMAL(10,2),

    -- Profitability
    roe_pct DECIMAL(8,2),
    roce_pct DECIMAL(8,2),
    net_margin_pct DECIMAL(8,2),
    operating_margin_pct DECIMAL(8,2),

    -- Leverage
    debt_to_equity DECIMAL(8,2),
    current_ratio DECIMAL(8,2),
    interest_coverage DECIMAL(10,2),

    -- Cash Flow
    fcf_yield_pct DECIMAL(8,2),

    -- Growth
    revenue_cagr_3y DECIMAL(8,2),
    profit_cagr_3y DECIMAL(8,2),

    -- Meta from yfinance info
    beta DECIMAL(6,3),
    book_value DECIMAL(12,2),
    fifty_two_week_high DECIMAL(12,4),
    fifty_two_week_low DECIMAL(12,4),
    dividend_yield_pct DECIMAL(6,2),
    shares_outstanding BIGINT,

    -- Grades
    overall_financial_grade VARCHAR(5),  -- A+ to D

    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(symbol, exchange)
);

CREATE INDEX IF NOT EXISTS idx_sr_symbol ON stock_ratios(symbol);
CREATE INDEX IF NOT EXISTS idx_sr_grade ON stock_ratios(overall_financial_grade);

-- 14. Price History (Daily OHLCV for top stocks)
CREATE TABLE IF NOT EXISTS price_history (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    open_price DECIMAL(12,4),
    high_price DECIMAL(12,4),
    low_price DECIMAL(12,4),
    close_price DECIMAL(12,4),
    volume BIGINT,
    UNIQUE(symbol, exchange, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_ph_symbol_date ON price_history(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_ph_exchange ON price_history(exchange);
