"""
数据模型定义
所有模块共享的数据结构
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import pandas as pd


@dataclass
class StockBasic:
    """股票基础信息"""
    code: str           # 600001
    name: str           # 浦发银行
    market: str         # sh / sz
    list_date: date     # 上市日期


@dataclass
class MarketData:
    """行情数据"""
    code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float       # 成交量(股)
    amount: float       # 成交额(元)
    turnover_rate: float  # 换手率(%)
    is_st: bool = False
    is_suspended: bool = False


@dataclass
class FinancialData:
    """财务数据（单季度/年度）"""
    code: str
    report_date: date   # 报告期
    # 估值
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    pcf_ttm: Optional[float] = None
    # 市值
    total_mv: Optional[float] = None      # 总市值(亿)
    circ_mv: Optional[float] = None       # 流通市值(亿)
    # 盈利
    roe: Optional[float] = None           # 净资产收益率(%)
    roa: Optional[float] = None           # 总资产收益率(%)
    roic: Optional[float] = None          # 投入资本回报率(%)
    gross_margin: Optional[float] = None  # 毛利率(%)
    net_margin: Optional[float] = None    # 净利率(%)
    # 成长
    revenue_yoy: Optional[float] = None   # 营收同比(%)
    profit_yoy: Optional[float] = None    # 净利同比(%)
    # 股息
    dividend_yield: Optional[float] = None  # 股息率(%)
    # 估值扩展
    ev2ebitda: Optional[float] = None     # 企业价值倍数
    ev2sales: Optional[float] = None      # EV/Sales
    # 财务健康
    debt_to_assets: Optional[float] = None     # 资产负债率(%)
    current_ratio: Optional[float] = None      # 流动比率
    interest_coverage: Optional[float] = None   # 利息保障倍数
    # 现金流
    ocf_to_profit: Optional[float] = None       # 经营CF/营业利润
    sales_cash_to_revenue: Optional[float] = None  # 销售收现/营收


@dataclass
class FactorResult:
    """因子计算结果"""
    date: date
    factor_name: str
    values: pd.Series   # index=stock_code, value=factor_value
    category: str        # value/quality/growth/momentum/size/dividend/safety


@dataclass
class Portfolio:
    """持仓组合"""
    date: date
    strategy_name: str
    holdings: list[str]  # 持仓股票代码列表
    weights: Optional[dict[str, float]] = None  # 权重（默认等权）
