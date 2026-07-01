"""
因子层：基类 + 注册中心
每个因子是独立模块，通过 @register_factor 装饰器注册
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import Callable, Optional
import pandas as pd

# 全局因子注册表
FACTOR_REGISTRY: dict[str, "BaseFactor"] = {}


def register_factor(name: str, category: str):
    """因子注册装饰器"""
    def decorator(cls):
        cls.name = name
        cls.category = category
        FACTOR_REGISTRY[name] = cls
        return cls
    return decorator


def get_factor(name: str) -> Optional["BaseFactor"]:
    """获取因子实例"""
    cls = FACTOR_REGISTRY.get(name)
    if cls is None:
        return None
    return cls()


class FactorData:
    """
    因子计算所需的数据容器
    解耦因子与数据源：因子只接收此结构，不直接调数据API
    """
    def __init__(
        self,
        trade_date: date,
        market_data: pd.DataFrame,    # 行情数据(需含 close, volume, turnover_rate等)
        daily_indicators: pd.DataFrame,  # 日频估值指标(PE/PB/PS/市值等)
        financial_data: pd.DataFrame,    # 财务数据(ROE/ROIC/毛利率等)
    ):
        self.trade_date = trade_date
        self.market = market_data
        self.indicators = daily_indicators
        self.financial = financial_data
        self._codes = market_data.index.tolist() if not market_data.empty else []

    @property
    def codes(self) -> list[str]:
        return self._codes


class BaseFactor(ABC):
    """
    因子基类
    
    【书本元数据字段】（第1重防线）
    每个因子必须填写以下字段，用于：
    1. 自动验证因子方向是否与书本一致
    2. 回测结果交叉验证
    3. 防止AI幻觉——没有书本依据的因子禁止加入策略
    """
    name: str = ""                          # 因子中文名
    category: str = ""                      # 类别：value/quality/growth/momentum/size/safety/dividend
    book_chapter: str = ""                  # ★书本章节，如 "第3章"
    book_conclusion: str = ""               # ★书本核心结论，如 "低PE优于高PE，最优分位12.57%"
    direction: str = ""                     # ★方向：higher_better / lower_better / middle_better
    book_best_quintile_return: float = 0.0  # ★书本最优分位年化收益率（用于交叉验证）
    book_worst_quintile_return: float = 0.0 # ★书本最差分位年化收益率

    @abstractmethod
    def compute(self, data: FactorData) -> pd.Series:
        """
        计算因子值
        返回: pd.Series, index=stock_code, values=因子原始值
        """
        ...

    def validate_metadata(self) -> list[str]:
        """
        自检：元数据是否完整
        
        Returns:
            缺失字段列表，空列表=通过
        """
        missing = []
        if not self.name: missing.append("name")
        if not self.category: missing.append("category")
        if not self.book_chapter: missing.append("book_chapter")
        if not self.book_conclusion: missing.append("book_conclusion")
        if not self.direction: missing.append("direction")
        if self.direction not in ('higher_better', 'lower_better', 'middle_better'):
            missing.append(f"direction值无效: {self.direction}")
        return missing

    def winsorize(self, series: pd.Series, pct: float = 0.01) -> pd.Series:
        """去极值：将超过百分位阈值的值截断"""
        lower = series.quantile(pct)
        upper = series.quantile(1 - pct)
        return series.clip(lower, upper)

    def standardize(self, series: pd.Series) -> pd.Series:
        """Z-score标准化"""
        return (series - series.mean()) / series.std()
