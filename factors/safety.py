"""
安全/危险信号因子

书本依据：董鹏飞第12章
核心发现：危险信号因子相互独立，不单独用于选股，但加入多因子后显著增强。
         5个排雷指标用于剔除劣质企业，而非寻找优质企业。
"""

import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("safety_ocf_to_profit", "safety")
class OCFToProfitFactor(BaseFactor):
    """经营活动现金流/营业利润：越高越好（利润含金量）"""
    name = "经营现金流/营业利润"
    category = "safety"
    book_chapter = "第12章"
    book_conclusion = "用于排雷。比值过低说明利润质量差，现金没有跟着利润一起增长"
    direction = "higher_better"
    book_best_quintile_return = 0.12
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("ocf_to_profit", pd.Series(dtype=float))


@register_factor("safety_sales_cash_to_revenue", "safety")
class SalesCashToRevenueFactor(BaseFactor):
    """销售收现/营业收入：越高越好（收入含金量）"""
    name = "销售收现/营业收入"
    category = "safety"
    book_chapter = "第12章"
    book_conclusion = "用于排雷。比值过低说明收入质量差，大量应收账款可能无法收回"
    direction = "higher_better"
    book_best_quintile_return = 0.12
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("sales_cash_to_revenue", pd.Series(dtype=float))


@register_factor("safety_interest_coverage", "safety")
class InterestCoverageFactor(BaseFactor):
    """利息保障倍数：越高越好"""
    name = "利息保障倍数"
    category = "safety"
    book_chapter = "第12章"
    book_conclusion = "用于排雷。倍数过低说明偿债压力大，财务风险高"
    direction = "higher_better"
    book_best_quintile_return = 0.12
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("interest_coverage", pd.Series(dtype=float))


@register_factor("safety_debt_to_assets", "safety")
class DebtToAssetsFactor(BaseFactor):
    """资产负债率：越低越好（金融业除外）"""
    name = "资产负债率"
    category = "safety"
    book_chapter = "第12章/第13章"
    book_conclusion = "用于排雷。过高意味着财务杠杆过大，熊市中风险加剧"
    direction = "lower_better"
    book_best_quintile_return = 0.12
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("debt_to_assets", pd.Series(dtype=float))


@register_factor("safety_equity2debt", "safety")
class EquityToDebtFactor(BaseFactor):
    """归属母公司股东权益/带息债务：越高越好"""
    name = "权益/带息债务"
    category = "safety"
    book_chapter = "第12章/第15章"
    book_conclusion = "TOP2五因子策略（EV/Sales+ROE+权益/带息债务+波动率+动量）年化17.26%"
    direction = "higher_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("equity_to_debt", pd.Series(dtype=float))
