"""
动量/波动率因子
"""
import numpy as np
import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("momentum_3m", "momentum")
class Momentum3MFactor(BaseFactor):
    """3个月价格动量"""
    def compute(self, data: FactorData) -> pd.Series:
        return self._momentum(data.market, 60)


@register_factor("momentum_6m", "momentum")
class Momentum6MFactor(BaseFactor):
    """6个月价格动量"""
    def compute(self, data: FactorData) -> pd.Series:
        return self._momentum(data.market, 120)


@register_factor("momentum_12m", "momentum")
class Momentum12MFactor(BaseFactor):
    """12个月价格动量"""
    def compute(self, data: FactorData) -> pd.Series:
        return self._momentum(data.market, 250)


@register_factor("momentum_volatility_6m", "momentum")
class Volatility6MFactor(BaseFactor):
    """6个月波动率：越低越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return self._volatility(data.market, 120)


@register_factor("momentum_volatility_12m", "momentum")
class Volatility12MFactor(BaseFactor):
    """12个月波动率"""
    def compute(self, data: FactorData) -> pd.Series:
        return self._volatility(data.market, 250)


# ---- 辅助函数（静态，放在类外最安全）----

def _momentum(market: pd.DataFrame, days: int) -> pd.Series:
    result = {}
    if market.empty:
        return pd.Series(dtype=float)
    codes = market.index.get_level_values(0).unique()
    for code in codes:
        df = market.loc[code]
        if len(df) < days:
            continue
        s = df.sort_index()
        result[code] = (s["close"].iloc[-1] - s["close"].iloc[-days]) / s["close"].iloc[-days]
    return pd.Series(result)


def _volatility(market: pd.DataFrame, days: int) -> pd.Series:
    result = {}
    if market.empty:
        return pd.Series(dtype=float)
    codes = market.index.get_level_values(0).unique()
    for code in codes:
        df = market.loc[code]
        if len(df) < days:
            continue
        s = df.sort_index()
        rets = s["close"].pct_change().dropna().tail(days)
        result[code] = rets.std() * np.sqrt(252)
    return pd.Series(result)


# 将辅助函数绑定到基类上
BaseFactor._momentum = staticmethod(_momentum)
BaseFactor._volatility = staticmethod(_volatility)
