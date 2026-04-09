from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

from config import DATABASE_URL


@contextmanager
def get_conn() -> Iterator[PGConnection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required. This Railway-safe build only supports PostgreSQL.")

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor, sslmode="require")
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sales_history (
    id BIGSERIAL PRIMARY KEY,
    shop_id TEXT NOT NULL,
    sale_date DATE NOT NULL,
    sku_id TEXT NOT NULL,
    sku_name TEXT NOT NULL,
    units_sold INTEGER NOT NULL DEFAULT 0,
    revenue NUMERIC(14,2) NOT NULL DEFAULT 0,
    returns INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (shop_id, sale_date, sku_id)
);

CREATE TABLE IF NOT EXISTS low_stock_notified (
    shop_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    notified_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (shop_id, sku_id)
);

CREATE TABLE IF NOT EXISTS seen_reviews (
    shop_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    rating INTEGER,
    created_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (shop_id, review_id)
);

CREATE TABLE IF NOT EXISTS stock_levels (
    shop_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    sku_name TEXT NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (shop_id, sku_id)
);

CREATE INDEX IF NOT EXISTS idx_sales_history_shop_date ON sales_history (shop_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_history_date ON sales_history (sale_date);
CREATE INDEX IF NOT EXISTS idx_stock_levels_shop_stock ON stock_levels (shop_id, stock);
"""

TRIGGER_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'set_sales_history_updated_at'
    ) THEN
        CREATE OR REPLACE FUNCTION update_timestamp_column()
        RETURNS TRIGGER AS $fn$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $fn$ language 'plpgsql';

        CREATE TRIGGER set_sales_history_updated_at
        BEFORE UPDATE ON sales_history
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp_column();
    END IF;
END
$$;
"""


def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            cur.execute(TRIGGER_SQL)


def execute(query: str, params: tuple[Any, ...] | list[Any] | None = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)


def executemany(query: str, seq_of_params: list[tuple[Any, ...]]) -> None:
    if not seq_of_params:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, query, seq_of_params, page_size=200)


def fetchall(query: str, params: tuple[Any, ...] | list[Any] | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def fetchone(query: str, params: tuple[Any, ...] | list[Any] | None = None) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()
