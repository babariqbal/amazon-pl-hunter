"""
SQLite storage layer for product hunter results.
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

CACHE_TTL_HOURS = 48

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
        CREATE TABLE IF NOT EXISTS users (
            phone       TEXT PRIMARY KEY,
            name        TEXT,
            state       TEXT,
            created_at  TEXT,
            updated_at  TEXT
        );

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
        # Replace any prior analysis for this ASIN so cache is always the latest
        c.execute("DELETE FROM analysis WHERE asin = ?", (asin,))
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


# ── User helpers ──────────────────────────────────────────────────────────────

def get_user(phone: str) -> dict | None:
    """Return user row or None if not found."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_user(phone: str, name: str):
    """Create or update user record and clear pending state."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO users (phone, name, state, created_at, updated_at)
        VALUES (?, ?, NULL, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            name       = excluded.name,
            state      = NULL,
            updated_at = excluded.updated_at
    """, (phone, name, now, now))
    conn.commit()
    conn.close()


def set_user_state(phone: str, state: str | None):
    """Create a stub user row (no name yet) or update just the state field."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO users (phone, name, state, created_at, updated_at)
        VALUES (?, NULL, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            state      = excluded.state,
            updated_at = excluded.updated_at
    """, (phone, state, now, now))
    conn.commit()
    conn.close()


# ── Cache helpers ──────────────────────────────────────────────────────────────

def get_cached_product(asin: str, max_age_hours: int = CACHE_TTL_HOURS) -> dict | None:
    """Return enriched product dict if it was scraped within max_age_hours, else None."""
    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        "SELECT raw_json FROM products WHERE asin = ? AND scraped_at >= datetime('now', ?)",
        (asin, f"-{max_age_hours} hours"),
    ).fetchone()
    conn.close()
    if row and row["raw_json"]:
        product = json.loads(row["raw_json"])
        # Only use cached data when the page was fully enriched (has BSR field)
        if product.get("bsr") is not None:
            return product
    return None


def get_cached_analysis(asin: str, max_age_hours: int = CACHE_TTL_HOURS) -> dict | None:
    """Return analysis dict if it was run within max_age_hours, else None."""
    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        """SELECT * FROM analysis WHERE asin = ?
           AND analyzed_at >= datetime('now', ?)
           ORDER BY analyzed_at DESC LIMIT 1""",
        (asin, f"-{max_age_hours} hours"),
    ).fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    for field in ("pain_points", "diff_ideas", "red_flags"):
        r[field] = json.loads(r.get(field) or "[]")
    return r


def clear_asin_cache(asin: str):
    """Delete all product and analysis records for an ASIN."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM analysis WHERE asin = ?", (asin,))
    c.execute("DELETE FROM products WHERE asin = ?", (asin,))
    conn.commit()
    conn.close()


def clear_all_cache() -> dict:
    """Delete all products and analyses from the cache."""
    conn = get_connection()
    c = conn.cursor()
    analyses = c.execute("SELECT COUNT(*) FROM analysis").fetchone()[0]
    products = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    c.execute("DELETE FROM analysis")
    c.execute("DELETE FROM products")
    conn.commit()
    conn.close()
    return {"products": products, "analyses": analyses}


def clear_keyword_cache(keyword: str) -> list:
    """Delete products (and their analyses) that were scraped under a given keyword."""
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute("SELECT asin FROM products WHERE keyword = ?", (keyword,)).fetchall()
    asins = [r["asin"] for r in rows]
    for asin in asins:
        c.execute("DELETE FROM analysis WHERE asin = ?", (asin,))
    c.execute("DELETE FROM products WHERE keyword = ?", (keyword,))
    conn.commit()
    conn.close()
    return asins
