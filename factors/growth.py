"""
成长因子：营收增速、净利润增速、营业利润增速

【书本参考】第9章：成长性
【核心结论】中等偏上的成长性最好，最高和最低分组都差。
  警惕"资本瘾君子"——高成长+低资本回报的陷阱。

【验证规则】
- 分位数收益率呈"倒U形"：中等分位最优，两端较差
- 增长率延续性差，今年高增长不代表明年
"""

import pandas as pd
import numpy as np
from .base import BaseFactor, FactorData, register_factor


@register_factor("growth_revenue_yoy", "growth")
class RevenueYoYFactor(BaseFactor):
    """
    营业收入同比增长率
    
    书本结论：中等偏上最优
    方向：越高越好（但极端高分位表现反而回落）
    """
    name = "营收同比增速"
    book_chapter = "第9章"
    direction = "higher_better"  # 注意：有上限效应
    
    def compute(self, data: FactorData) -> pd.Series:
        # 优先从 financial_data 取
        if 'revenue_yoy' in data.financial.columns:
            return data.financial['revenue_yoy']
        # 备选：从 indicators 取
        if 'revenue_yoy' in data.indicators.columns:
            return data.indicators['revenue_yoy']
        return pd.Series(dtype=float)


@register_factor("growth_profit_yoy", "growth")
class ProfitYoYFactor(BaseFactor):
    """
    净利润同比增长率
    
    书本结论：中等偏上最优
    方向：越高越好（有上限效应）
    """
    name = "净利润同比增速"
    book_chapter = "第9章"
    direction = "higher_better"
    
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
    """
    营业利润同比增长率
    
    书本结论：中等偏上最优
    方向：越高越好
    """
    name = "营业利润同比增速"
    book_chapter = "第9章"
    direction = "higher_better"
    
    def compute(self, data: FactorData) -> pd.Series:
        if 'op_profit_yoy' in data.financial.columns:
            return data.financial['op_profit_yoy']
        # 营业利润增速 = 营收增速的近似（数据缺失时的降级方案）
        # 注意：这是近似值，不如真实数据准确
        if 'revenue_yoy' in data.financial.columns:
            return data.financial['revenue_yoy']
        return pd.Series(dtype=float)
