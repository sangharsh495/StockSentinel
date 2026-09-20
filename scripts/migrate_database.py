#!/usr/bin/env python3
"""
StockSentinel Database Auto-Migrator
Safely updates the live PostgreSQL database schema on Neon.tech:
- Adds missing columns to existing tables
- Creates new intelligence tables (daily_news_ratings, ipo_research_reports, stock_screener_cache, news_stock_impact)
- Builds high-performance indexes
"""

import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import asyncpg

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "backend" / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

MIGRATION_STEPS = [
    # 1. Trigram extension
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",

    # 2. Add any missing columns to 'news'
    "ALTER TABLE news ADD COLUMN IF NOT EXISTS impact_score DECIMAL(5,4);",
    "ALTER TABLE news ADD COLUMN IF NOT EXISTS affected_stocks JSONB DEFAULT '[]'::jsonb;",
    "ALTER TABLE news ADD COLUMN IF NOT EXISTS dividend_detected BOOLEAN DEFAULT FALSE;",

    # 3. News indexes
    "CREATE INDEX IF NOT EXISTS idx_news_dividend ON news(dividend_detected) WHERE dividend_detected = TRUE;",
    "CREATE INDEX IF NOT EXISTS idx_news_impact ON news(impact_score DESC NULLS LAST);",

    # 4. news_stock_impact table
    """
    CREATE TABLE IF NOT EXISTS news_stock_impact (
        id SERIAL PRIMARY KEY,
        news_id INTEGER REFERENCES news(id) ON DELETE CASCADE,
        stock_id INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
        symbol VARCHAR(20) NOT NULL,
        impact_direction VARCHAR(10),
        impact_score DECIMAL(5,4),
        reason VARCHAR(200),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE(news_id, symbol)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_nsi_news ON news_stock_impact(news_id);",
    "CREATE INDEX IF NOT EXISTS idx_nsi_stock ON news_stock_impact(stock_id);",
    "CREATE INDEX IF NOT EXISTS idx_nsi_symbol ON news_stock_impact(symbol);",

    # 5. daily_news_ratings table
    """
    CREATE TABLE IF NOT EXISTS daily_news_ratings (
        id SERIAL PRIMARY KEY,
        news_id INTEGER REFERENCES news(id) ON DELETE CASCADE,
        title VARCHAR(500) NOT NULL,
        url VARCHAR(1000),
        source VARCHAR(100),
        rating DECIMAL(3,1) NOT NULL,
        impact_level VARCHAR(20) NOT NULL,
        headline_verdict VARCHAR(255),
        sentiment VARCHAR(10),
        related_symbols TEXT[],
        ranking_date DATE NOT NULL DEFAULT CURRENT_DATE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_dnr_date ON daily_news_ratings(ranking_date DESC);",
    "CREATE INDEX IF NOT EXISTS idx_dnr_rating ON daily_news_ratings(rating DESC);",

    # 6. ipo_research_reports table
    """
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
    """,
    "CREATE INDEX IF NOT EXISTS idx_irr_company ON ipo_research_reports(company_name);",

    # 7. stock_screener_cache table
    """
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
    """,
    "CREATE INDEX IF NOT EXISTS idx_ssc_score ON stock_screener_cache(composite_score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_ssc_grade ON stock_screener_cache(research_grade);"
]


async def run_migration():
    if not DATABASE_URL:
        print("❌ DATABASE_URL is not set in backend/.env")
        sys.exit(1)

    print("=" * 60)
    print("🚀 StockSentinel Live Database Auto-Migration")
    print("=" * 60)
    print(f"Connecting to: {DATABASE_URL.split('@')[-1]}")

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        print(f"Executing {len(MIGRATION_STEPS)} migration statements...")
        for i, step in enumerate(MIGRATION_STEPS, 1):
            stmt_summary = step.strip().split("\n")[0][:50]
            print(f"  [{i}/{len(MIGRATION_STEPS)}] {stmt_summary}...")
            await conn.execute(step)

        # Verify all tables in public schema
        rows = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [r["table_name"] for r in rows]
        print("\n✅ Migration successfully applied to live Neon database!")
        print(f"Total Tables in Live Database: {len(tables)}")
        for t in tables:
            print(f"  ✓ {t}")

        # Check existing row counts
        print("\n📊 Current Database Statistics:")
        for t in tables:
            try:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {t}")
                print(f"  - {t:22}: {count:,} rows")
            except Exception:
                pass

    finally:
        await conn.close()
    print("\n🎉 LIVE DATABASE IS FULLY UP TO DATE & READY!")


if __name__ == "__main__":
    asyncio.run(run_migration())
