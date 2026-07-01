"""
安全/危险信号因子
"""
import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("safety_ocf_to_profit", "safety")
class OCFToProfitFactor(BaseFactor):
    """经营活动现金流/营业利润：越高越好（利润含金量）"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("ocf_to_profit", pd.Series(dtype=float))


@register_factor("safety_sales_cash_to_revenue", "safety")
class SalesCashToRevenueFactor(BaseFactor):
    """销售收现/营业收入：越高越好（收入含金量）"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("sales_cash_to_revenue", pd.Series(dtype=float))


@register_factor("safety_interest_coverage", "safety")
class InterestCoverageFactor(BaseFactor):
    """利息保障倍数：越高越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("interest_coverage", pd.Series(dtype=float))


@register_factor("safety_debt_to_assets", "safety")
class DebtToAssetsFactor(BaseFactor):
    """资产负债率：越低越好（金融业除外）"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("debt_to_assets", pd.Series(dtype=float))


@register_factor("safety_equity2debt", "safety")
class EquityToDebtFactor(BaseFactor):
    """归属母公司股东权益/带息债务：越高越好"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("equity_to_debt", pd.Series(dtype=float))
