"""
Persistent SQLite cache for Santiment historical data.

Two-tier caching:
  - SQLite: Persistent storage for historical timeseries (survives restarts)
  - In-memory: Fast reads for hot data with TTL expiry

Schema designed for maximum query flexibility:
  - Per-metric, per-slug daily timeseries
  - Metadata tracking (last pull, data range, point count)
  - Bulk insert/upsert for efficient backfills
"""

import sqlite3
import json
import time
import logging
import os
from typing import Optional, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Prefer /data/ (Railway Volume mount point) if it exists, otherwise fall back to local
_DEFAULT_DB_DIR = "/data" if os.path.isdir("/data") else "data"
DB_PATH = os.environ.get("SANTIMENT_DB_PATH", f"{_DEFAULT_DB_DIR}/santiment_cache.db")


class SantimentCache:
    """Persistent SQLite cache for Santiment data."""

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_dir()
        self._connect()
        self._create_tables()
        logger.info(f"SantimentCache initialized at {self._db_path} (exists: {os.path.exists(self._db_path)}, "
                     f"size: {os.path.getsize(self._db_path) / 1024 / 1024:.1f}MB)")

    def _ensure_dir(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=10000")
        self._conn.row_factory = sqlite3.Row

    def _create_tables(self):
        self._conn.executescript("""
            -- Core timeseries data: one row per metric/slug/date
            CREATE TABLE IF NOT EXISTS timeseries (
                metric TEXT NOT NULL,
                slug TEXT NOT NULL,
                dt TEXT NOT NULL,
                value REAL,
                interval TEXT DEFAULT '1d',
                updated_at REAL NOT NULL,
                PRIMARY KEY (metric, slug, dt, interval)
            );

            -- OHLCV price data
            CREATE TABLE IF NOT EXISTS ohlcv (
                slug TEXT NOT NULL,
                dt TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                marketcap REAL,
                interval TEXT DEFAULT '1d',
                updated_at REAL NOT NULL,
                PRIMARY KEY (slug, dt, interval)
            );

            -- Project fundamentals
            CREATE TABLE IF NOT EXISTS projects (
                slug TEXT PRIMARY KEY,
                name TEXT,
                ticker TEXT,
                description TEXT,
                website TEXT,
                marketcap_usd REAL,
                infrastructure TEXT,
                main_contract TEXT,
                total_supply REAL,
                dev_activity_30d REAL,
                dev_activity_90d REAL,
                available_metrics TEXT,  -- JSON array
                updated_at REAL NOT NULL
            );

            -- Track what we've already pulled (avoid re-pulling)
            CREATE TABLE IF NOT EXISTS pull_log (
                metric TEXT NOT NULL,
                slug TEXT NOT NULL,
                interval TEXT DEFAULT '1d',
                from_date TEXT NOT NULL,
                to_date TEXT NOT NULL,
                data_points INTEGER,
                pulled_at REAL NOT NULL,
                status TEXT DEFAULT 'success',
                error_message TEXT,
                PRIMARY KEY (metric, slug, interval, from_date, to_date)
            );

            -- Available metrics catalog
            CREATE TABLE IF NOT EXISTS metrics_catalog (
                metric TEXT PRIMARY KEY,
                min_interval TEXT,
                default_aggregation TEXT,
                data_type TEXT,
                is_accessible INTEGER,
                is_restricted INTEGER,
                available_slugs_count INTEGER,
                updated_at REAL NOT NULL
            );

            -- Available slugs per metric (many-to-many)
            CREATE TABLE IF NOT EXISTS metric_slugs (
                metric TEXT NOT NULL,
                slug TEXT NOT NULL,
                PRIMARY KEY (metric, slug)
            );

            -- Index for fast lookups
            CREATE INDEX IF NOT EXISTS idx_ts_slug ON timeseries(slug, metric);
            CREATE INDEX IF NOT EXISTS idx_ts_metric ON timeseries(metric, slug);
            CREATE INDEX IF NOT EXISTS idx_ts_dt ON timeseries(dt);
            CREATE INDEX IF NOT EXISTS idx_ohlcv_slug ON ohlcv(slug, dt);
            CREATE INDEX IF NOT EXISTS idx_pull_log_metric ON pull_log(metric, slug);
        """)
        self._conn.commit()

    # ================================================================
    # TIMESERIES OPERATIONS
    # ================================================================

    def store_timeseries(
        self,
        metric: str,
        slug: str,
        data: list[dict],
        interval: str = "1d",
    ) -> int:
        """
        Store timeseries data points. Upserts on conflict.
        Returns number of rows inserted/updated.
        """
        if not data:
            return 0

        now = time.time()
        rows = []
        for point in data:
            dt = point.get("datetime", point.get("d"))
            value = point.get("value", point.get("v"))
            if dt is not None and value is not None:
                rows.append((metric, slug, dt, value, interval, now))

        self._conn.executemany(
            """INSERT OR REPLACE INTO timeseries (metric, slug, dt, value, interval, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_timeseries(
        self,
        metric: str,
        slug: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        interval: str = "1d",
    ) -> list[dict]:
        """Read timeseries data from cache."""
        query = "SELECT dt, value FROM timeseries WHERE metric = ? AND slug = ? AND interval = ?"
        params: list[Any] = [metric, slug, interval]

        if from_date:
            query += " AND dt >= ?"
            params.append(from_date)
        if to_date:
            query += " AND dt <= ?"
            params.append(to_date)

        query += " ORDER BY dt ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [{"datetime": row["dt"], "value": row["value"]} for row in rows]

    def get_latest_values(self, metric: str, interval: str = "1d") -> dict:
        """
        Bulk fetch the latest 2 values for ALL slugs for a given metric.
        Returns {slug: {"latest": val, "prev": val}} — one query instead of N.
        """
        rows = self._conn.execute(
            """SELECT slug, dt, value FROM timeseries
               WHERE metric = ? AND interval = ?
               ORDER BY slug, dt DESC""",
            (metric, interval),
        ).fetchall()

        result = {}
        prev_slug = None
        count = 0
        for row in rows:
            s = row["slug"]
            if s != prev_slug:
                prev_slug = s
                count = 0
            count += 1
            if count == 1:
                result.setdefault(s, {})["latest"] = row["value"]
                result[s]["latest_dt"] = row["dt"]
            elif count == 2:
                result[s]["prev"] = row["value"]
            # skip rows beyond 2 per slug
        return result

    def get_timeseries_date_range(self, metric: str, slug: str, interval: str = "1d") -> Optional[dict]:
        """Get the earliest and latest date we have for a metric/slug."""
        row = self._conn.execute(
            """SELECT MIN(dt) as min_dt, MAX(dt) as max_dt, COUNT(*) as count
               FROM timeseries WHERE metric = ? AND slug = ? AND interval = ?""",
            (metric, slug, interval),
        ).fetchone()
        if row and row["count"] > 0:
            return {"min_date": row["min_dt"], "max_date": row["max_dt"], "count": row["count"]}
        return None

    # ================================================================
    # OHLCV OPERATIONS
    # ================================================================

    def store_ohlcv(self, slug: str, data: list[dict], interval: str = "1d") -> int:
        if not data:
            return 0
        now = time.time()
        rows = []
        for point in data:
            rows.append((
                slug,
                point.get("datetime"),
                point.get("openPriceUsd"),
                point.get("highPriceUsd"),
                point.get("lowPriceUsd"),
                point.get("closePriceUsd"),
                point.get("volume"),
                point.get("marketcap"),
                interval,
                now,
            ))
        self._conn.executemany(
            """INSERT OR REPLACE INTO ohlcv (slug, dt, open, high, low, close, volume, marketcap, interval, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_ohlcv(
        self,
        slug: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        interval: str = "1d",
    ) -> list[dict]:
        query = "SELECT * FROM ohlcv WHERE slug = ? AND interval = ?"
        params: list[Any] = [slug, interval]
        if from_date:
            query += " AND dt >= ?"
            params.append(from_date)
        if to_date:
            query += " AND dt <= ?"
            params.append(to_date)
        query += " ORDER BY dt ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # ================================================================
    # PROJECT OPERATIONS
    # ================================================================

    def store_projects(self, projects: list[dict]) -> int:
        if not projects:
            return 0
        now = time.time()
        rows = []
        for p in projects:
            rows.append((
                p.get("slug"),
                p.get("name"),
                p.get("ticker"),
                p.get("description", ""),
                p.get("websiteLink", ""),
                p.get("marketcapUsd"),
                p.get("infrastructure", ""),
                p.get("mainContractAddress", ""),
                p.get("totalSupply"),
                p.get("devActivity30"),
                p.get("devActivity90"),
                json.dumps(p.get("availableMetrics", [])),
                now,
            ))
        self._conn.executemany(
            """INSERT OR REPLACE INTO projects
               (slug, name, ticker, description, website, marketcap_usd,
                infrastructure, main_contract, total_supply,
                dev_activity_30d, dev_activity_90d, available_metrics, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_project(self, slug: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
        if row:
            d = dict(row)
            d["available_metrics"] = json.loads(d.get("available_metrics") or "[]")
            return d
        return None

    def get_all_projects(self, min_marketcap: Optional[float] = None) -> list[dict]:
        query = "SELECT * FROM projects"
        params: list[Any] = []
        if min_marketcap:
            query += " WHERE marketcap_usd >= ?"
            params.append(min_marketcap)
        query += " ORDER BY marketcap_usd DESC NULLS LAST"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # ================================================================
    # METRICS CATALOG
    # ================================================================

    def store_metrics_catalog(self, metrics: list[dict]) -> int:
        if not metrics:
            return 0
        now = time.time()
        rows = []
        for m in metrics:
            rows.append((
                m.get("metric"),
                m.get("min_interval"),
                m.get("default_aggregation"),
                m.get("data_type"),
                1 if m.get("is_accessible") else 0,
                1 if m.get("is_restricted") else 0,
                m.get("available_slugs_count", 0),
                now,
            ))
        self._conn.executemany(
            """INSERT OR REPLACE INTO metrics_catalog
               (metric, min_interval, default_aggregation, data_type,
                is_accessible, is_restricted, available_slugs_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def store_metric_slugs(self, metric: str, slugs: list[str]) -> int:
        if not slugs:
            return 0
        rows = [(metric, s) for s in slugs]
        self._conn.executemany(
            "INSERT OR IGNORE INTO metric_slugs (metric, slug) VALUES (?, ?)",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_metrics_for_slug(self, slug: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT metric FROM metric_slugs WHERE slug = ? ORDER BY metric",
            (slug,),
        ).fetchall()
        return [row["metric"] for row in rows]

    def get_slugs_for_metric(self, metric: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT slug FROM metric_slugs WHERE metric = ? ORDER BY slug",
            (metric,),
        ).fetchall()
        return [row["slug"] for row in rows]

    # ================================================================
    # PULL LOG: Track what we've already fetched
    # ================================================================

    def log_pull(
        self,
        metric: str,
        slug: str,
        from_date: str,
        to_date: str,
        data_points: int,
        interval: str = "1d",
        status: str = "success",
        error_message: Optional[str] = None,
    ):
        self._conn.execute(
            """INSERT OR REPLACE INTO pull_log
               (metric, slug, interval, from_date, to_date, data_points, pulled_at, status, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (metric, slug, interval, from_date, to_date, data_points, time.time(), status, error_message),
        )
        self._conn.commit()

    def was_pulled(self, metric: str, slug: str, from_date: str, to_date: str, interval: str = "1d") -> bool:
        """Check if we already successfully pulled this data range."""
        row = self._conn.execute(
            """SELECT 1 FROM pull_log
               WHERE metric = ? AND slug = ? AND interval = ?
               AND from_date <= ? AND to_date >= ? AND status = 'success'""",
            (metric, slug, interval, from_date, to_date),
        ).fetchone()
        return row is not None

    def get_pull_stats(self) -> dict:
        """Get overall pull statistics."""
        total = self._conn.execute("SELECT COUNT(*) as c FROM pull_log").fetchone()["c"]
        success = self._conn.execute("SELECT COUNT(*) as c FROM pull_log WHERE status = 'success'").fetchone()["c"]
        failed = self._conn.execute("SELECT COUNT(*) as c FROM pull_log WHERE status = 'error'").fetchone()["c"]
        total_points = self._conn.execute("SELECT SUM(data_points) as s FROM pull_log WHERE status = 'success'").fetchone()["s"] or 0
        ts_count = self._conn.execute("SELECT COUNT(*) as c FROM timeseries").fetchone()["c"]
        ohlcv_count = self._conn.execute("SELECT COUNT(*) as c FROM ohlcv").fetchone()["c"]
        project_count = self._conn.execute("SELECT COUNT(*) as c FROM projects").fetchone()["c"]
        metrics_count = self._conn.execute("SELECT COUNT(*) as c FROM metrics_catalog").fetchone()["c"]

        # DB file size
        db_size_mb = os.path.getsize(self._db_path) / (1024 * 1024) if os.path.exists(self._db_path) else 0

        return {
            "total_pulls": total,
            "successful_pulls": success,
            "failed_pulls": failed,
            "total_data_points_pulled": total_points,
            "timeseries_rows": ts_count,
            "ohlcv_rows": ohlcv_count,
            "projects_cached": project_count,
            "metrics_cataloged": metrics_count,
            "db_size_mb": round(db_size_mb, 2),
        }

    # ================================================================
    # UTILITY
    # ================================================================

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def vacuum(self):
        """Optimize database file size."""
        self._conn.execute("VACUUM")
