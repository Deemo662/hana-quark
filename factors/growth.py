"""
成长因子：营收增速、净利润增速、营业利润增速

书本依据：董鹏飞第9章
核心结论：中等偏上的成长性最好，最高和最低分组都差。
         警惕"资本瘾君子"——高成长+低资本回报的陷阱。
         增长率延续性差，今年高增长不代表明年。
"""

import pandas as pd
import numpy as np
from .base import BaseFactor, FactorData, register_factor


@register_factor("growth_revenue_yoy", "growth")
class RevenueYoYFactor(BaseFactor):
    """营业收入同比增长率：中等偏上最优"""
    name = "营业收入同比增速"
    category = "growth"
    book_chapter = "第9章"
    book_conclusion = "中等偏上最优，最高和最低分组都差。警惕资本瘾君子"
    direction = "higher_better"  # 注意：书上说有上限效应（极端高增长反而差）
    book_best_quintile_return = 0.11
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        if 'revenue_yoy' in data.financial.columns:
            return data.financial['revenue_yoy']
        if 'revenue_yoy' in data.indicators.columns:
            return data.indicators['revenue_yoy']
        return pd.Series(dtype=float)


@register_factor("growth_profit_yoy", "growth")
class ProfitYoYFactor(BaseFactor):
    """净利润同比增长率：中等偏上最优"""
    name = "净利润同比增速"
    category = "growth"
    book_chapter = "第9章"
    book_conclusion = "中等偏上最优。增长率延续性差"
    direction = "higher_better"
    book_best_quintile_return = 0.11
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        if 'profit_yoy' in data.financial.columns:
            return data.financial['profit_yoy']
        if 'profit_yoy' in data.indicators.columns:
            return data.indicators['profit_yoy']
        if 'net_profit_yoy' in data.financial.columns:
            return data.financial['net_profit_yoy']
        return pd.Series(dtype=float)


@register_factor("growth_op_profit_yoy", "growth")
class OpProfitYoYFactor(BaseFactor):
    """营业利润同比增长率：中等偏上最优"""
    name = "营业利润同比增速"
    category = "growth"
    book_chapter = "第9章"
    book_conclusion = "中等偏上最优。与净利润增速高度相关"
    direction = "higher_better"
    book_best_quintile_return = 0.11
    book_worst_quintile_return = 0.06

    def compute(self, data: FactorData) -> pd.Series:
        if 'op_profit_yoy' in data.financial.columns:
            return data.financial['op_profit_yoy']
        if 'revenue_yoy' in data.financial.columns:
            return data.financial['revenue_yoy']  # 降级：用营收增速近似
        return pd.Series(dtype=float)
