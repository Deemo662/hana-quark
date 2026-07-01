"""
估值因子：PE/PB/PS/PCF/EV2EBITDA/EV2Sales/股息率
"""
import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("value_pe_ttm", "value")
class PEFactor(BaseFactor):
    """市盈率TTM：越低越好。排除负PE"""
    def compute(self, data: FactorData) -> pd.Series:
        pe = data.indicators.get("pe_ttm", pd.Series(dtype=float))
        return pe.where(pe > 0)  # 负值设为NaN


@register_factor("value_pb", "value")
class PBFactor(BaseFactor):
    """市净率：越低越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("pb", pd.Series(dtype=float))


@register_factor("value_ps_ttm", "value")
class PSFactor(BaseFactor):
    """市销率TTM：越低越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("ps_ttm", pd.Series(dtype=float))


@register_factor("value_pcf_ttm", "value")
class PCFFactor(BaseFactor):
    """市现率TTM：越低越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("pcf_ttm", pd.Series(dtype=float))


@register_factor("value_ev2ebitda", "value")
class EV2EBITDAFactor(BaseFactor):
    """企业价值倍数：越低越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("ev2ebitda", pd.Series(dtype=float)) \
            if "ev2ebitda" in data.financial.columns else data.indicators.get("ev2ebitda", pd.Series(dtype=float))


@register_factor("value_ev2sales", "value")
class EV2SalesFactor(BaseFactor):
    """EV/Sales：越低越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("ev2sales", pd.Series(dtype=float)) \
            if "ev2sales" in data.financial.columns else data.indicators.get("ev2sales", pd.Series(dtype=float))


@register_factor("dividend_yield", "dividend")
class DividendYieldFactor(BaseFactor):
    """股息率：越高越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("dividend_yield", pd.Series(dtype=float))
