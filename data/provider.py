"""
数据源抽象基类 — 解耦因子层与具体数据源

【白话说明】
因子层不需要知道数据是从AkShare拉的还是从SQLite读的，
它只需要知道"给我行情数据"和"给我财务数据"就行。
这个抽象基类定义了这两个需求的"合同"。
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional
import pandas as pd


class DataProvider(ABC):
    """
    数据源接口：所有数据源（AkShare/SQLite/Mock）必须实现
    
    设计原则：
    - get_market_data: 获取行情数据（OHLCV），返回 MultiIndex (code, date) 的DataFrame
    - get_daily_indicators: 获取日频估值/财务快照指标（PE/PB/PS/市值等）
    - get_financial_data: 获取深度财报数据（ROE/ROIC/毛利率/现金流等）
    """

    @abstractmethod
    def get_stock_list(self, trade_date: Optional[date] = None) -> pd.DataFrame:
        """
        获取A股全量股票列表（含上市日期）
        
        Returns:
            DataFrame, index=code, columns含 name, list_date, is_st
        """
        ...

    @abstractmethod
    def get_market_data(
        self, codes: list[str], start: date, end: date
    ) -> pd.DataFrame:
        """
        获取日线行情
        
        Returns:
            DataFrame with MultiIndex (code, date)
            columns: open, high, low, close, volume, amount, turnover_rate
        """
        ...

    @abstractmethod
    def get_daily_indicators(
        self, codes: list[str], trade_date: date
    ) -> pd.DataFrame:
        """
        获取日频估值/财务快照指标
        
        Returns:
            DataFrame, index=code
            columns: pe_ttm, pb, ps_ttm, pcf_ttm, total_mv, circ_mv,
                     ev2ebitda, dividend_yield, is_st, is_suspended, ...
        """
        ...

    @abstractmethod
    def get_financial_data(
        self, codes: list[str], report_date: date
    ) -> pd.DataFrame:
        """
        获取深度财报数据
        
        Returns:
            DataFrame, index=code
            columns: roe, roa, roic, gross_margin, net_margin,
                     revenue_yoy, profit_yoy, debt_to_assets,
                     ocf_to_profit, sales_cash_to_revenue, interest_coverage, ...
        """
        ...
