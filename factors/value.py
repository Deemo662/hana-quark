"""
估值因子：PE/PB/PS/PCF/EV2EBITDA/EV2Sales/股息率

书本依据：董鹏飞第3-8章
"""

import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("value_pe_ttm", "value")
class PEFactor(BaseFactor):
    """市盈率TTM：越低越好。排除负PE（负PE仅5.72%年化）"""
    name = "市盈率(PE-TTM)"
    category = "value"
    book_chapter = "第3章"
    book_conclusion = "低PE优于高PE，最优分位12.57%，绝不买负PE"
    direction = "lower_better"
    book_best_quintile_return = 0.1257
    book_worst_quintile_return = 0.0672

    def compute(self, data: FactorData) -> pd.Series:
        pe = data.indicators.get("pe_ttm", pd.Series(dtype=float))
        return pe.where(pe > 0)  # 负PE设为NaN（策略铁律#1：绝不买负PE）


@register_factor("value_pb", "value")
class PBFactor(BaseFactor):
    """市净率：越低越好"""
    name = "市净率(PB)"
    category = "value"
    book_chapter = "第4章"
    book_conclusion = "低PB优于高PB，最优分位约13-14%"
    direction = "lower_better"
    book_best_quintile_return = 0.135
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("pb", pd.Series(dtype=float))


@register_factor("value_ps_ttm", "value")
class PSFactor(BaseFactor):
    """市销率TTM：越低越好"""
    name = "市销率(PS-TTM)"
    category = "value"
    book_chapter = "第6章"
    book_conclusion = "低PS表现更优，第2分位夏普比率最高"
    direction = "lower_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("ps_ttm", pd.Series(dtype=float))


@register_factor("value_pcf_ttm", "value")
class PCFFactor(BaseFactor):
    """市现率TTM：越低越好"""
    name = "市现率(PCF-TTM)"
    category = "value"
    book_chapter = "第7章"
    book_conclusion = "低市现率更好。经营现金流计算的有效性>自由现金流"
    direction = "lower_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("pcf_ttm", pd.Series(dtype=float))


@register_factor("value_ev2ebitda", "value")
class EV2EBITDAFactor(BaseFactor):
    """企业价值倍数：越低越好。格林布拉特神奇公式核心估值指标"""
    name = "企业价值倍数(EV/EBITDA)"
    category = "value"
    book_chapter = "第5章"
    book_conclusion = "越低越好，神奇公式核心指标"
    direction = "lower_better"
    book_best_quintile_return = 0.13
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("ev2ebitda", pd.Series(dtype=float)) \
            if "ev2ebitda" in data.financial.columns else data.indicators.get("ev2ebitda", pd.Series(dtype=float))


@register_factor("value_ev2sales", "value")
class EV2SalesFactor(BaseFactor):
    """EV/Sales：越低越好"""
    name = "企业价值/销售额(EV/Sales)"
    category = "value"
    book_chapter = "第5章/第15章"
    book_conclusion = "与毛利率组合使用效果极佳，严格单调递减"
    direction = "lower_better"
    book_best_quintile_return = 0.14
    book_worst_quintile_return = 0.07

    def compute(self, data: FactorData) -> pd.Series:
        return data.financial.get("ev2sales", pd.Series(dtype=float)) \
            if "ev2sales" in data.financial.columns else data.indicators.get("ev2sales", pd.Series(dtype=float))


@register_factor("dividend_yield", "dividend")
class DividendYieldFactor(BaseFactor):
    """股息率：越高越好。有分红远胜无分红（狗股策略有效）"""
    name = "股息率"
    category = "dividend"
    book_chapter = "第8章"
    book_conclusion = "有分红远胜无分红（11.77% vs 6.83%），狗股策略有效。但多因子中表现不如单因子"
    direction = "higher_better"
    book_best_quintile_return = 0.1469
    book_worst_quintile_return = 0.0683

    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("dividend_yield", pd.Series(dtype=float))
