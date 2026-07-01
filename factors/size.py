"""
市值因子
"""
import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("size_market_cap", "size")
class MarketCapFactor(BaseFactor):
    """市值因子：越小越好（A股规模效应显著）"""

    def compute(self, data: FactorData) -> pd.Series:
        df = data.indicators
        if "circ_mv" in df.columns:
            return df["circ_mv"]
        if "total_mv" in df.columns:
            return df["total_mv"]
        raise KeyError("市值数据缺失")
