"""
SQLite本地缓存

【白话说明】
从网上拉数据很慢（5000只股票×10年=几百万条），所以拉下来后存到本地SQLite。
以后每次只需要拉今天新增的几条数据（增量更新），不用重复拉历史数据。

【数据库表结构】
- stock_info:     股票基本信息（代码、名称、上市日期、行业）
- daily_kline:    日K线数据（所有股票的所有交易日）
- financial_data: 财务数据（每只股票每个报告期）
- trade_calendar: 交易日历
- data_log:       数据更新日志（记录每次拉取的时间和数据范围）
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime


class DataCache:
    """
    SQLite本地缓存
    
    负责：建表、写入、查询、增量更新管理
    """
    
    def __init__(self, db_path: str = "data/cache/quant.db"):
        """
        初始化缓存
        
        Args:
            db_path: SQLite数据库文件路径
        """
        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
    
    def _create_tables(self):
        """
        创建数据库表（如果不存在）
        
        【设计说明】
        每张表都有 created_at 和 updated_at 字段，
        用于追踪数据新鲜度和增量更新。
        """
        cursor = self.conn.cursor()
        
        # ---- 股票基本信息表 ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_info (
                code TEXT PRIMARY KEY,           -- 股票代码，如 '000001'
                name TEXT NOT NULL,              -- 股票名称，如 '平安银行'
                listed_date TEXT,                -- 上市日期 'YYYYMMDD'
                delisted_date TEXT,              -- 退市日期（NULL表示未退市）
                industry TEXT,                   -- 申万行业
                exchange TEXT,                   -- 交易所 'SH'/'SZ'/'BJ'
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        # ---- 日K线数据表 ----
        # 【重要】所有成分股的所有交易日都在这一张表里
        # 约 5000只 × 250天/年 × 15年 = 1875万行
        # SQLite单表千万级查询性能OK（有索引），过亿再考虑分表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_kline (
                code TEXT NOT NULL,              -- 股票代码
                trade_date TEXT NOT NULL,        -- 交易日期 'YYYYMMDD'
                open REAL,                       -- 开盘价（后复权）
                high REAL,                       -- 最高价（后复权）
                low REAL,                        -- 最低价（后复权）
                close REAL,                      -- 收盘价（后复权）
                pre_close REAL,                  -- 前收盘价（后复权）
                volume REAL,                     -- 成交量（股）
                amount REAL,                     -- 成交额（元）
                turnover REAL,                   -- 换手率（%）
                is_st INTEGER DEFAULT 0,         -- 当日是否ST
                is_suspend INTEGER DEFAULT 0,    -- 当日是否停牌（1=停牌）
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (code, trade_date)
            )
        """)
        
        # 索引：按股票代码查、按日期查、按代码+日期范围查
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_kline_code 
            ON daily_kline(code)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_kline_date 
            ON daily_kline(trade_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_kline_code_date 
            ON daily_kline(code, trade_date)
        """)
        
        # ---- 财务数据表 ----
        # 每只股票每个报告期一行
        # 【PIT关键】包含 disclosure_date 字段
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS financial_data (
                code TEXT NOT NULL,              -- 股票代码
                report_date TEXT NOT NULL,       -- 报告期 '20231231'
                disclosure_date TEXT,            -- ★实际披露日期 '20240425'（PIT必需）
                
                -- 估值指标
                pe_ttm REAL,                     -- 市盈率(TTM)
                pb REAL,                         -- 市净率
                ps_ttm REAL,                     -- 市销率(TTM)
                pcf_ttm REAL,                    -- 市现率(TTM，经营现金流)
                dividend_yield REAL,             -- 股息率
                ev_ebitda REAL,                  -- 企业价值倍数
                
                -- 质量指标
                roe REAL,                        -- 净资产收益率
                roa REAL,                        -- 总资产收益率
                roic REAL,                       -- 投入资本回报率
                gross_margin REAL,               -- 毛利率
                net_margin REAL,                 -- 净利率
                
                -- 成长指标
                revenue_yoy REAL,                -- 营业收入同比增速
                net_profit_yoy REAL,             -- 净利润同比增速
                op_profit_yoy REAL,              -- 营业利润同比增速
                
                -- 规模
                total_market_cap REAL,           -- 总市值
                float_market_cap REAL,           -- 流通市值
                
                -- 排雷指标
                ocf_to_op REAL,                  -- 经营活动现金流/营业利润
                sales_cash_to_revenue REAL,      -- 销售收到的现金/营业收入
                op_to_total_profit REAL,         -- 营业利润/利润总额
                interest_coverage REAL,          -- 利息保障倍数
                
                -- 其他
                total_assets REAL,
                total_liabilities REAL,
                asset_liability_ratio REAL,      -- 资产负债率
                ev2sales REAL,                   -- 企业价值/销售额
                equity_to_debt REAL,             -- 归属母公司权益/带息债务
                
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (code, report_date)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fin_code 
            ON financial_data(code)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fin_report_date 
            ON financial_data(report_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fin_disc_date 
            ON financial_data(disclosure_date)
        """)
        
        # ---- 交易日历表 ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_calendar (
                trade_date TEXT PRIMARY KEY,     -- 日期 'YYYYMMDD'
                is_open INTEGER DEFAULT 1        -- 1=交易日，0=非交易日
            )
        """)
        
        # ---- 数据更新日志表 ----
        # 记录每次数据拉取的时间、范围、状态
        # 增量更新的依据
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_type TEXT NOT NULL,          -- 'kline' / 'financial' / 'stock_info'
                start_date TEXT,                  -- 拉取起始日期
                end_date TEXT,                    -- 拉取结束日期
                record_count INTEGER,             -- 拉取到的记录数
                status TEXT DEFAULT 'success',    -- 'success' / 'partial' / 'failed'
                error_msg TEXT,                   -- 错误信息
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        self.conn.commit()
    
    # ========== 写入方法 ==========
    
    def save_stock_info(self, df: pd.DataFrame) -> int:
        """
        保存股票基本信息
        
        【白话】把股票列表写入数据库。已存在的更新，不存在的插入。
        """
        df = df.copy()
        df['updated_at'] = datetime.now().isoformat()
        
        # 使用 REPLACE 实现"存在则更新，不存在则插入"
        df.to_sql('stock_info', self.conn, if_exists='replace', index=False)
        return len(df)
    
    def save_daily_kline(self, df: pd.DataFrame) -> int:
        """
        保存日K线数据（增量追加）
        
        【白话】把新拉取的K线数据追加到数据库。
        如果某条记录（code+trade_date）已存在，跳过不覆盖。
        """
        required_cols = ['code', 'trade_date', 'open', 'high', 'low', 'close', 'volume']
        df = df[required_cols + [c for c in df.columns if c not in required_cols]]
        
        # 使用 INSERT OR IGNORE 跳过重复数据
        df.to_sql('daily_kline', self.conn, if_exists='append', index=False,
                  method='multi', chunksize=5000)
        return len(df)
    
    def save_financial_data(self, df: pd.DataFrame) -> int:
        """
        保存财务数据（增量追加）
        """
        df.to_sql('financial_data', self.conn, if_exists='append', index=False,
                  method='multi', chunksize=1000)
        return len(df)
    
    def save_trade_calendar(self, df: pd.DataFrame) -> int:
        """保存交易日历"""
        df.to_sql('trade_calendar', self.conn, if_exists='replace', index=False)
        return len(df)
    
    def log_update(self, data_type: str, start_date: str, end_date: str, 
                   record_count: int, status: str = 'success', error_msg: str = None):
        """记录数据更新日志"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO data_log (data_type, start_date, end_date, record_count, status, error_msg)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data_type, start_date, end_date, record_count, status, error_msg))
        self.conn.commit()
    
    # ========== 查询方法 ==========
    
    def get_all_stocks(self, include_delisted: bool = True) -> pd.DataFrame:
        """
        获取全部股票列表
        
        【重要】include_delisted=True 表示包含已退市股票——避免幸存者偏差
        """
        query = "SELECT * FROM stock_info"
        if not include_delisted:
            query += " WHERE delisted_date IS NULL"
        return pd.read_sql(query, self.conn)
    
    def get_kline(self, code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        查询某只股票的日K线
        
        Args:
            code: 股票代码
            start_date: 起始日期（可选）
            end_date: 结束日期（可选）
        """
        query = "SELECT * FROM daily_kline WHERE code = ?"
        params = [code]
        
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        
        query += " ORDER BY trade_date ASC"
        return pd.read_sql(query, self.conn, params=params)
    
    def get_all_kline_on_date(self, trade_date: str) -> pd.DataFrame:
        """
        查询某一天所有股票的K线数据
        
        【用途】月度调仓日需要获取全市场数据来算因子
        """
        return pd.read_sql(
            "SELECT * FROM daily_kline WHERE trade_date = ?",
            self.conn, params=[trade_date]
        )
    
    def get_kline_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        查询日期范围内所有股票的K线
        
        【用途】回测时需要全量数据
        """
        return pd.read_sql(
            "SELECT * FROM daily_kline WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date, code",
            self.conn, params=[start_date, end_date]
        )
    
    def get_financial(self, code: str, report_date: str = None) -> pd.DataFrame:
        """查询某只股票的财务数据"""
        query = "SELECT * FROM financial_data WHERE code = ?"
        params = [code]
        if report_date:
            query += " AND report_date = ?"
            params.append(report_date)
        query += " ORDER BY report_date DESC"
        return pd.read_sql(query, self.conn, params=params)
    
    def get_latest_financial_before_date(self, code: str, before_date: str) -> pd.DataFrame:
        """
        【PIT关键方法】
        查询在某日期之前已披露的最新财务数据
        
        【白话】这是PIT原则的SQL实现——
        "在2024年3月31日调仓时，我只用3月31日之前已经披露的财报"
        
        Args:
            code: 股票代码
            before_date: 调仓日期
            
        Returns:
            该日期前最新披露的一份财报数据
        """
        query = """
            SELECT * FROM financial_data 
            WHERE code = ? 
              AND disclosure_date IS NOT NULL 
              AND disclosure_date <= ?
            ORDER BY report_date DESC 
            LIMIT 1
        """
        return pd.read_sql(query, self.conn, params=[code, before_date])
    
    def get_trade_dates(self, start_date: str, end_date: str) -> pd.DataFrame:
        """查询交易日历"""
        return pd.read_sql(
            "SELECT trade_date FROM trade_calendar WHERE is_open = 1 AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
            self.conn, params=[start_date, end_date]
        )
    
    def get_latest_date(self, data_type: str) -> str:
        """
        查询某类数据的最新日期
        
        【用途】增量更新时用——"上次拉到2024-06-28，今天从2024-06-29开始拉"
        """
        table_map = {
            'kline': ('daily_kline', 'trade_date'),
            'financial': ('financial_data', 'report_date'),
        }
        
        if data_type not in table_map:
            return None
        
        table, col = table_map[data_type]
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT MAX({col}) FROM {table}")
        result = cursor.fetchone()
        return result[0] if result else None
    
    def get_data_log(self, data_type: str = None, limit: int = 20) -> pd.DataFrame:
        """查看数据更新日志"""
        query = "SELECT * FROM data_log"
        params = []
        if data_type:
            query += " WHERE data_type = ?"
            params.append(data_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return pd.read_sql(query, self.conn, params=params)
    
    def get_table_stats(self) -> dict:
        """
        获取数据库统计信息
        
        【用途】数据质量报告——各表有多少条记录、覆盖什么日期范围
        """
        cursor = self.conn.cursor()
        stats = {}
        
        tables = ['stock_info', 'daily_kline', 'financial_data', 'trade_calendar']
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[f'{table}_rows'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT MIN(trade_date), MAX(trade_date) FROM daily_kline")
        min_d, max_d = cursor.fetchone()
        stats['kline_date_range'] = f"{min_d} ~ {max_d}"
        
        cursor.execute("SELECT COUNT(DISTINCT code) FROM daily_kline")
        stats['kline_stock_count'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT MIN(report_date), MAX(report_date) FROM financial_data")
        min_r, max_r = cursor.fetchone()
        stats['financial_date_range'] = f"{min_r} ~ {max_r}"
        
        return stats
    
    def close(self):
        """关闭数据库连接"""
        self.conn.close()
