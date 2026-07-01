"""
市值因子

书本依据：董鹏飞第2章
核心发现：A股市值效应比美国更显著。最小分位年化14.86%，最大分位7.89%。
         加入市值因子几乎都能提升策略表现。
"""

import pandas as pd
from .base import BaseFactor, FactorData, register_factor


@register_factor("size_market_cap", "size")
class MarketCapFactor(BaseFactor):
    """市值因子：越小越好（A股规模效应显著）"""
    name = "总市值"
    category = "size"
    book_chapter = "第2章"
    book_conclusion = "市值越低收益率越高。最小分位14.86%，最大分位7.89%。A股市值效应比美国更显著。滚动10年期小盘股100%正收益"
    direction = "lower_better"
    book_best_quintile_return = 0.1486  # 最小市值分位
    book_worst_quintile_return = 0.0789  # 最大市值分位

    def compute(self, data: FactorData) -> pd.Series:
        df = data.indicators
        if "circ_mv" in df.columns:
            return df["circ_mv"]
        if "total_mv" in df.columns:
            return df["total_mv"]
        raise KeyError("市值数据缺失")
