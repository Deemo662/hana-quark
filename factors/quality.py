"""
质量因子：ROE/ROA/ROIC/毛利率/净利率

书本依据：董鹏飞第10-11章
核心发现：ROE+PB双因子 > ROE多因子 > 任何单因子
"""

import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("quality_roe", "quality")
class ROEFactor(BaseFactor):
    """净资产收益率：越高越好。区分度极强，连续性好"""
    name = "净资产收益率(ROE)"
    category = "quality"
    book_chapter = "第10章"
    book_conclusion = "越高越好，阶梯形下降特征清晰。ROE+PB双因子最优分位年化12.8%"
    direction = "higher_better"
    book_best_quintile_return = 0.14
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        roe = data.financial.get("roe", pd.Series(dtype=float))
        if roe.empty:
            roe = data.indicators.get("roe", pd.Series(dtype=float))
        return roe


@register_factor("quality_roa", "quality")
class ROAFactor(BaseFactor):
    """总资产收益率：越高越好。不考量杠杆，更纯粹"""
    name = "总资产收益率(ROA)"
    category = "quality"
    book_chapter = "第10章"
    book_conclusion = "越高越好，不考量杠杆更纯粹"
    direction = "higher_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("roa", pd.Series(dtype=float))


@register_factor("quality_roic", "quality")
class ROICFactor(BaseFactor):
    """投入资本回报率：越高越好。张坤核心指标，TOP1策略五因子之一"""
    name = "投入资本回报率(ROIC)"
    category = "quality"
    book_chapter = "第10章"
    book_conclusion = "越高越好，张坤核心指标。TOP1策略（市值+毛利率+ROIC+波动率+PS）年化18.44%的关键组分"
    direction = "higher_better"
    book_best_quintile_return = 0.14
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("roic", pd.Series(dtype=float))


@register_factor("quality_gross_margin", "quality")
class GrossMarginFactor(BaseFactor):
    """毛利率：越高越好。上下游定价权最佳指标，区分度远优于净利率"""
    name = "毛利率"
    category = "quality"
    book_chapter = "第11章"
    book_conclusion = "上下游定价权最佳指标。各分位严格单调递减，极其有效。白酒毛利率均值61%"
    direction = "higher_better"
    book_best_quintile_return = 0.14
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("gross_margin", pd.Series(dtype=float))


@register_factor("quality_net_margin", "quality")
class NetMarginFactor(BaseFactor):
    """净利率：越高越好（但不如毛利率有效）"""
    name = "净利率"
    category = "quality"
    book_chapter = "第11章"
    book_conclusion = "不如毛利率有效，作者在多因子模型中选择毛利率而非净利率"
    direction = "higher_better"
    book_best_quintile_return = 0.12
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("net_margin", pd.Series(dtype=float))
