"""
模拟盘跟踪系统 — 数据库层

表结构：
  signals      每日选股快照（策略×日期×排名×股票代码）
  holdings     每日持仓快照（策略×日期×持仓股票×成本价）
  performance  每日策略绩效（总资产×收益率）
  benchmarks   基准指数行情（沪深300日线）
  reports      定期评估报告
"""
import sqlite3
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import pandas as pd


DB_PATH = Path(__file__).parent.parent / "data" / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    rank INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    score REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    weight REAL,
    entry_date TEXT,
    entry_price REAL,
    shares INTEGER DEFAULT 100,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    total_value REAL,
    daily_return REAL,
    cumulative_return REAL,
    cash REAL DEFAULT 100000,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    index_code TEXT NOT NULL DEFAULT '000300',
    close REAL,
    daily_return REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    report_type TEXT NOT NULL,
    strategy TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    content TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(trade_date, strategy);
CREATE INDEX IF NOT EXISTS idx_holdings_date ON holdings(trade_date, strategy);
CREATE INDEX IF NOT EXISTS idx_performance_date ON performance(trade_date, strategy);
CREATE INDEX IF NOT EXISTS idx_benchmarks_date ON benchmarks(trade_date);
"""


def get_db() -> sqlite3.Connection:
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ===== 写入操作 =====

def save_signals(trade_date: date, strategy: str, signals: pd.DataFrame):
    """保存每日选股快照"""
    conn = get_db()
    rows = []
    for _, row in signals.iterrows():
        rows.append((
            trade_date.isoformat(),
            strategy,
            int(row.get("rank", 0)),
            row["code"],
            row.get("name", ""),
            float(row.get("score", 0)),
        ))
    conn.executemany(
        "INSERT INTO signals (trade_date, strategy, rank, code, name, score) VALUES (?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_holdings(trade_date: date, strategy: str, holdings: list[dict]):
    """保存每日持仓"""
    conn = get_db()
    rows = []
    for h in holdings:
        rows.append((
            trade_date.isoformat(),
            strategy,
            h["code"],
            h.get("name", ""),
            h.get("weight", 0),
            h.get("entry_date", trade_date.isoformat()),
            h.get("entry_price", 0),
        ))
    conn.executemany(
        "INSERT INTO holdings (trade_date, strategy, code, name, weight, entry_date, entry_price) VALUES (?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_performance(trade_date: date, strategy: str, total_value: float,
                     daily_return: float, cumulative_return: float):
    """记录每日绩效"""
    conn = get_db()
    conn.execute(
        "INSERT INTO performance (trade_date, strategy, total_value, daily_return, cumulative_return) VALUES (?,?,?,?,?)",
        (trade_date.isoformat(), strategy, total_value, daily_return, cumulative_return)
    )
    conn.commit()
    conn.close()


def save_benchmark(trade_date: date, index_code: str, close: float, daily_return: float):
    """记录基准指数"""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO benchmarks (trade_date, index_code, close, daily_return) VALUES (?,?,?,?)",
        (trade_date.isoformat(), index_code, close, daily_return)
    )
    conn.commit()
    conn.close()


def save_report(report_date: date, report_type: str, strategy: str,
                period_start: date, period_end: date, content: str):
    """保存评估报告"""
    conn = get_db()
    conn.execute(
        "INSERT INTO reports (report_date, report_type, strategy, period_start, period_end, content) VALUES (?,?,?,?,?,?)",
        (report_date.isoformat(), report_type, strategy,
         period_start.isoformat(), period_end.isoformat(), content)
    )
    conn.commit()
    conn.close()


# ===== 查询操作 =====

def get_latest_signals(strategy: str, limit: int = 20) -> pd.DataFrame:
    """获取最近一次选股结果"""
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT * FROM signals
        WHERE strategy = ? AND trade_date = (SELECT MAX(trade_date) FROM signals WHERE strategy = ?)
        ORDER BY rank
        LIMIT ?
    """, conn, params=(strategy, strategy, limit))
    conn.close()
    return df


def get_holdings_history(strategy: str, days: int = 30) -> pd.DataFrame:
    """获取持仓历史"""
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT * FROM holdings
        WHERE strategy = ?
        ORDER BY trade_date DESC
        LIMIT ?
    """, conn, params=(strategy, days))
    conn.close()
    return df


def get_performance_summary(strategy: str, days: int = 90) -> pd.DataFrame:
    """获取绩效摘要"""
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT p.trade_date, p.strategy, p.total_value, p.daily_return, p.cumulative_return,
               b.close as benchmark_close, b.daily_return as benchmark_return
        FROM performance p
        LEFT JOIN benchmarks b ON p.trade_date = b.trade_date
        WHERE p.strategy = ?
        ORDER BY p.trade_date DESC
        LIMIT ?
    """, conn, params=(strategy, days))
    conn.close()
    return df


def get_benchmark_history(days: int = 90) -> pd.DataFrame:
    """获取基准指数历史"""
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT * FROM benchmarks
        ORDER BY trade_date DESC
        LIMIT ?
    """, conn, params=(days,))
    conn.close()
    return df


def get_recent_reports(strategy: str, report_type: str, limit: int = 5) -> pd.DataFrame:
    """获取最近的评估报告"""
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT * FROM reports
        WHERE strategy = ? AND report_type = ?
        ORDER BY report_date DESC
        LIMIT ?
    """, conn, params=(strategy, report_type, limit))
    conn.close()
    return df
