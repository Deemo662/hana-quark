"""
质量因子：ROE/ROA/ROIC/毛利率/净利率
"""
import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("quality_roe", "quality")
class ROEFactor(BaseFactor):
    """净资产收益率：越高越好"""
    def compute(self, data: FactorData) -> pd.Series:
        roe = data.financial.get("roe", pd.Series(dtype=float))
        if roe.empty:
            roe = data.indicators.get("roe", pd.Series(dtype=float))
        return roe


@register_factor("quality_roa", "quality")
class ROAFactor(BaseFactor):
    """总资产收益率：越高越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("roa", pd.Series(dtype=float))


@register_factor("quality_roic", "quality")
class ROICFactor(BaseFactor):
    """投入资本回报率：越高越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("roic", pd.Series(dtype=float))


@register_factor("quality_gross_margin", "quality")
class GrossMarginFactor(BaseFactor):
    """毛利率：越高越好（上下游地位指标）"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("gross_margin", pd.Series(dtype=float))


@register_factor("quality_net_margin", "quality")
class NetMarginFactor(BaseFactor):
    """净利率：越高越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("net_margin", pd.Series(dtype=float))
