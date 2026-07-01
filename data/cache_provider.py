"""
SQLite缓存数据源 — 实现DataProvider接口

【白话说明】
数据已经从AkShare拉到SQLite数据库里了。
这个文件让因子层可以像调用AkShare一样从SQLite读取数据。
速度极快（本地数据库 vs 网络请求），适合回测和每日信号生成。

【数据流】
AkShare(网络) → main.py拉取 → SQLite → CacheProvider → 因子层
"""

from datetime import date, datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np
import logging

from .provider import DataProvider
from .cache import DataCache

logger = logging.getLogger(__name__)


class CacheProvider(DataProvider):
    """
    从SQLite缓存读取数据的Provider
    
    实现DataProvider接口，数据来源是本地SQLite数据库。
    用于回测和每日信号生成（不需要反复从网络拉数据）。
    """
    
    def __init__(self, db_path: str = "data/cache/quant.db"):
        self.cache = DataCache(db_path)
    
    # ===================================================================
    # 股票列表
    # ===================================================================
    
    def get_stock_list(self, trade_date: Optional[date] = None) -> pd.DataFrame:
        """
        获取股票列表
        
        如果指定了trade_date，只返回该日期前已上市的股票。
        """
        df = self.cache.get_all_stocks(include_delisted=True)
        
        if df is None or len(df) == 0:
            logger.warning("数据库中没有股票列表")
            return pd.DataFrame()
        
        # 统一字段名
        df = df.rename(columns={
            'code': 'code',
            'name': 'name',
            'listed_date': 'list_date',
        })
        
        # 转换list_date为date类型
        if 'list_date' in df.columns:
            df['list_date'] = pd.to_datetime(df['list_date'], errors='coerce')
        
        # 如果指定了trade_date，过滤未上市的
        if trade_date is not None and 'list_date' in df.columns:
            df = df[df['list_date'].notna() & (df['list_date'] <= pd.Timestamp(trade_date))]
        
        # 设置code为index（因子层期望的格式）
        if 'code' in df.columns:
            df = df.set_index('code')
        
        return df
    
    # ===================================================================
    # 行情数据
    # ===================================================================
    
    def get_market_data(
        self, codes: list[str], start: date, end: date
    ) -> pd.DataFrame:
        """
        获取日线行情，返回 MultiIndex (code, date) 的DataFrame
        
        【重要】这是因子层计算动量/波动率的基础数据
        """
        start_str = start.strftime('%Y%m%d') if isinstance(start, date) else start
        end_str = end.strftime('%Y%m%d') if isinstance(end, date) else end
        
        frames = []
        for code in codes:
            df = self.cache.get_kline(code, start_str, end_str)
            if df is not None and len(df) > 0:
                frames.append(df)
        
        if not frames:
            logger.warning(f"未找到任何K线数据: {start_str} ~ {end_str}")
            return pd.DataFrame()
        
        # 合并所有股票的数据
        all_data = pd.concat(frames, ignore_index=True)
        
        # ---- 整理字段 ----
        # 计算换手率（如果数据源有成交量但没有换手率的话，这里填NaN）
        if 'turnover' in all_data.columns:
            all_data['turnover_rate'] = all_data['turnover']
        else:
            # AkShare的get_daily_kline可能没返回换手率
            # 注：AkShare stock_zh_a_hist 返回的列中包含 '换手率'
            all_data['turnover_rate'] = np.nan
        
        # 确保必要字段存在
        required_cols = ['code', 'trade_date', 'open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in all_data.columns:
                logger.warning(f"K线数据缺少字段: {col}")
                all_data[col] = np.nan
        
        # 添加amount（如果缺失）
        if 'amount' not in all_data.columns:
            all_data['amount'] = all_data['close'] * all_data['volume']
        
        # 转换日期
        all_data['date'] = pd.to_datetime(all_data['trade_date'], format='%Y%m%d')
        
        # 设置 MultiIndex: (code, date)
        result = all_data.set_index(['code', 'date'])
        
        # 只保留需要的列
        keep_cols = ['trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover_rate']
        result = result[[c for c in keep_cols if c in result.columns]]
        
        # 按索引排序
        result = result.sort_index()
        
        return result
    
    # ===================================================================
    # 日频估值指标
    # ===================================================================
    
    def get_daily_indicators(
        self, codes: list[str], trade_date: date
    ) -> pd.DataFrame:
        """
        获取某日的估值/财务快照指标
        
        【PIT关键】这里只使用 trade_date 之前已披露的财务数据。
        通过 get_latest_financial_before_date 实现。
        """
        date_str = trade_date.strftime('%Y%m%d') if isinstance(trade_date, date) else trade_date
        
        rows = []
        for code in codes:
            row = {'code': code}
            
            # ---- 从K线获取当日行情+估值（★PE/PB/PS/PCF已嵌入K线） ----
            kline = self.cache.get_kline(code, date_str, date_str)
            if kline is not None and len(kline) > 0:
                latest_k = kline.iloc[-1]
                row['close'] = latest_k.get('close', np.nan)
                row['is_suspended'] = latest_k.get('is_suspend', 0)
                row['is_st'] = latest_k.get('is_st', 0)
                # ★估值数据直接从K线取（每天都有）
                row['pe_ttm'] = self._safe_float(latest_k.get('pe_ttm'))
                row['pb'] = self._safe_float(latest_k.get('pb'))
                row['ps_ttm'] = self._safe_float(latest_k.get('ps_ttm'))
                row['pcf_ttm'] = self._safe_float(latest_k.get('pcf_ttm'))
                # 市值：用 close × volume/换手率 粗略估算（换手率=volume/流通股本，所以流通股本=volume/换手率）
                turnover = self._safe_float(latest_k.get('turnover'))
                vol = self._safe_float(latest_k.get('volume'))
                close_p = self._safe_float(latest_k.get('close'))
                if turnover and vol and close_p and turnover > 0:
                    # circ_mv ≈ close × volume / turnover_rate
                    # 这是粗略估计，更准确的需要从财务数据获取
                    row['circ_mv'] = close_p * vol / (turnover / 100)
                    row['total_mv'] = row['circ_mv']  # 近似
            
            # ---- ★PIT原则：获取该日期前已披露的最新财务数据 ----
            fin = self.cache.get_latest_financial_before_date(code, date_str)
            if fin is not None and len(fin) > 0:
                latest_f = fin.iloc[0]
                row['pe_ttm'] = self._safe_float(latest_f.get('pe_ttm'))
                row['pb'] = self._safe_float(latest_f.get('pb'))
                row['ps_ttm'] = self._safe_float(latest_f.get('ps_ttm'))
                row['pcf_ttm'] = self._safe_float(latest_f.get('pcf_ttm'))
                row['total_mv'] = self._safe_float(latest_f.get('total_market_cap'))
                row['circ_mv'] = self._safe_float(latest_f.get('float_market_cap'))
                row['ev2ebitda'] = self._safe_float(latest_f.get('ev_ebitda'))
                row['dividend_yield'] = self._safe_float(latest_f.get('dividend_yield'))
                row['roe'] = self._safe_float(latest_f.get('roe'))
                row['roa'] = self._safe_float(latest_f.get('roa'))
                row['roic'] = self._safe_float(latest_f.get('roic'))
                row['gross_margin'] = self._safe_float(latest_f.get('gross_margin'))
                row['net_margin'] = self._safe_float(latest_f.get('net_margin'))
                row['revenue_yoy'] = self._safe_float(latest_f.get('revenue_yoy'))
                row['profit_yoy'] = self._safe_float(latest_f.get('net_profit_yoy'))
                row['debt_to_assets'] = self._safe_float(latest_f.get('asset_liability_ratio'))
                row['ocf_to_profit'] = self._safe_float(latest_f.get('ocf_to_op'))
                row['sales_cash_to_revenue'] = self._safe_float(latest_f.get('sales_cash_to_revenue'))
                row['interest_coverage'] = self._safe_float(latest_f.get('interest_coverage'))
                row['ev2sales'] = self._safe_float(latest_f.get('ev2sales'))
                row['equity_to_debt'] = self._safe_float(latest_f.get('equity_to_debt'))
            
            rows.append(row)
        
        df = pd.DataFrame(rows)
        if 'code' in df.columns:
            df = df.set_index('code')
        
        return df
    
    # ===================================================================
    # 深度财务数据
    # ===================================================================
    
    def get_financial_data(
        self, codes: list[str], report_date: date
    ) -> pd.DataFrame:
        """
        获取指定报告期的财务数据
        
        与 get_daily_indicators 的区别：
        - daily_indicators: 返回"某交易日可用的最新快照"（PIT原则）
        - financial_data: 返回"指定报告期的原始财务数据"（用于深度分析）
        """
        date_str = report_date.strftime('%Y%m%d') if isinstance(report_date, date) else report_date
        
        rows = []
        for code in codes:
            fin = self.cache.get_financial(code, date_str)
            if fin is not None and len(fin) > 0:
                latest_f = fin.iloc[0]
                row = {'code': code}
                for col in ['roe', 'roa', 'roic', 'gross_margin', 'net_margin',
                            'revenue_yoy', 'profit_yoy', 'debt_to_assets',
                            'ocf_to_profit', 'sales_cash_to_revenue', 'interest_coverage',
                            'ev2sales', 'ev2ebitda', 'equity_to_debt',
                            'pe_ttm', 'pb', 'ps_ttm', 'pcf_ttm',
                            'total_mv', 'circ_mv', 'dividend_yield']:
                    if col in latest_f.index:
                        row[col] = self._safe_float(latest_f.get(col))
                rows.append(row)
        
        df = pd.DataFrame(rows)
        if 'code' in df.columns:
            df = df.set_index('code')
        
        return df
    
    def _safe_float(self, value) -> Optional[float]:
        """安全转float"""
        if value is None:
            return None
        try:
            f = float(value)
            if np.isnan(f) or np.isinf(f):
                return None
            return f
        except (ValueError, TypeError):
            return None
    
    def close(self):
        """关闭数据库连接"""
        self.cache.close()
