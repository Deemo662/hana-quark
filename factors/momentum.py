"""
动量/波动率因子

书本依据：董鹏飞第14章
核心发现：高动量+低波动=最优。6月波动率+1月动量组合极其有效。
         ROE+6月波动率双因子年化16.90%（TOP3策略）
"""

import numpy as np
import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("momentum_3m", "momentum")
class Momentum3MFactor(BaseFactor):
    """3个月价格动量：越高越好"""
    name = "3个月价格动量"
    category = "momentum"
    book_chapter = "第14章"
    book_conclusion = "越高越好。中期动量在A股有效"
    direction = "higher_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return self._momentum(data.market, 60)


@register_factor("momentum_6m", "momentum")
class Momentum6MFactor(BaseFactor):
    """6个月价格动量：越高越好"""
    name = "6个月价格动量"
    category = "momentum"
    book_chapter = "第14章"
    book_conclusion = "越高越好。A股中期动量效应显著"
    direction = "higher_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return self._momentum(data.market, 120)


@register_factor("momentum_12m", "momentum")
class Momentum12MFactor(BaseFactor):
    """12个月价格动量：越高越好"""
    name = "12个月价格动量"
    category = "momentum"
    book_chapter = "第14章"
    book_conclusion = "越高越好。长期动量在A股有效"
    direction = "higher_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return self._momentum(data.market, 250)


@register_factor("momentum_volatility_6m", "momentum")
class Volatility6MFactor(BaseFactor):
    """6个月波动率：越低越好。全书TOP3双因子模型的核心"""
    name = "6个月波动率"
    category = "momentum"
    book_chapter = "第14章"
    book_conclusion = "越低越好。低波动异象在A股极强。ROE+6月波动率年化16.90%"
    direction = "lower_better"
    book_best_quintile_return = 0.15
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        return self._volatility(data.market, 120)


@register_factor("momentum_volatility_12m", "momentum")
class Volatility12MFactor(BaseFactor):
    """12个月波动率：越低越好"""
    name = "12个月波动率"
    category = "momentum"
    book_chapter = "第14章"
    book_conclusion = "越低越好，但6个月波动率更有效"
    direction = "lower_better"
    book_best_quintile_return = 0.14
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        return self._volatility(data.market, 250)


# ---- 辅助函数（静态方法） ----

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


BaseFactor._momentum = staticmethod(_momentum)
BaseFactor._volatility = staticmethod(_volatility)
