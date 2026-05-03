"""
SQLite storage layer for product hunter results.
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

DB_PATH = "data/products.db"


def get_connection():
    Path(os.path.dirname(DB_PATH)).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            asin            TEXT UNIQUE,
            keyword         TEXT,
            title           TEXT,
            price           REAL,
            rating          REAL,
            review_count    INTEGER,
            bsr             INTEGER,
            category        TEXT,
            weight_lbs      REAL,
            monthly_revenue REAL,
            passed_filter   INTEGER DEFAULT 0,
            scraped_at      TEXT,
            raw_json        TEXT
        );

        CREATE TABLE IF NOT EXISTS analysis (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            asin            TEXT,
            score           REAL,
            margin_pct      REAL,
            net_profit      REAL,
            pain_points     TEXT,
            diff_ideas      TEXT,
            red_flags       TEXT,
            product_brief   TEXT,
            analyzed_at     TEXT,
            FOREIGN KEY(asin) REFERENCES products(asin)
        );

        CREATE TABLE IF NOT EXISTS runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT,
            finished_at TEXT,
            keywords    TEXT,
            found       INTEGER DEFAULT 0,
            passed      INTEGER DEFAULT 0,
            winners     INTEGER DEFAULT 0
        );
    """)

    conn.commit()
    conn.close()
    print("[DB] Initialized database.")


def save_product(product: dict):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT OR REPLACE INTO products
            (asin, keyword, title, price, rating, review_count, bsr,
             category, weight_lbs, monthly_revenue, passed_filter, scraped_at, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            product.get("asin"),
            product.get("keyword"),
            product.get("title"),
            product.get("price"),
            product.get("rating"),
            product.get("review_count"),
            product.get("bsr"),
            product.get("category"),
            product.get("weight_lbs"),
            product.get("monthly_revenue"),
            int(product.get("passed_filter", False)),
            datetime.utcnow().isoformat(),
            json.dumps(product),
        ))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving product {product.get('asin')}: {e}")
    finally:
        conn.close()


def save_analysis(asin: str, result: dict):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO analysis
            (asin, score, margin_pct, net_profit, pain_points, diff_ideas,
             red_flags, product_brief, analyzed_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            asin,
            result.get("score"),
            result.get("margin_pct"),
            result.get("net_profit"),
            json.dumps(result.get("pain_points", [])),
            json.dumps(result.get("diff_ideas", [])),
            json.dumps(result.get("red_flags", [])),
            result.get("product_brief", ""),
            datetime.utcnow().isoformat(),
        ))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving analysis for {asin}: {e}")
    finally:
        conn.close()


def get_passed_products():
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM products WHERE passed_filter = 1 ORDER BY scraped_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_winners(min_score: float = 7.0):
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute("""
        SELECT p.*, a.score, a.margin_pct, a.net_profit,
               a.pain_points, a.diff_ideas, a.product_brief
        FROM products p
        JOIN analysis a ON p.asin = a.asin
        WHERE a.score >= ?
        ORDER BY a.score DESC
    """, (min_score,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_run(started_at, finished_at, keywords, found, passed, winners):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO runs (started_at, finished_at, keywords, found, passed, winners)
        VALUES (?,?,?,?,?,?)
    """, (started_at, finished_at, json.dumps(keywords), found, passed, winners))
    conn.commit()
    conn.close()
