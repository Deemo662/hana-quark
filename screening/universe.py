"""
股票池构建模块
"""
from datetime import date, timedelta
from typing import Optional
import pandas as pd


class UniverseBuilder:
    """构建可投资股票池"""

    def __init__(
        self,
        exclude_st: bool = True,
        exclude_new_less_days: int = 180,
        exclude_suspended: bool = True,
        exclude_micro_cap_pct: float = 0.15,
    ):
        self.exclude_st = exclude_st
        self.exclude_new_less_days = exclude_new_less_days
        self.exclude_suspended = exclude_suspended
        self.exclude_micro_cap_pct = exclude_micro_cap_pct

    def build(
        self,
        trade_date: date,
        stock_list: pd.DataFrame,
        daily_indicators: pd.DataFrame,
    ) -> pd.Index:
        """
        构建当日可投资股票池
        返回: 股票代码Index
        """
        codes = set(stock_list.index.tolist() if isinstance(stock_list.index, pd.Index)
                     else stock_list["code"].tolist())

        # 1. 剔除上市不足180天的新股/次新股
        if self.exclude_new_less_days and "list_date" in stock_list.columns:
            cutoff = trade_date - timedelta(days=self.exclude_new_less_days)
            valid_new = stock_list[stock_list["list_date"] <= cutoff]
            codes &= set(valid_new.index.tolist() if isinstance(valid_new.index, pd.Index)
                         else valid_new["code"].tolist())

        # 2. 剔除ST
        if self.exclude_st and "is_st" in daily_indicators.columns:
            st_codes = set(daily_indicators[daily_indicators["is_st"] == True].index.tolist()
                          if isinstance(daily_indicators.index, pd.Index)
                          else daily_indicators[daily_indicators["is_st"] == True]["code"].tolist())
            codes -= st_codes

        # 3. 剔除停牌
        if self.exclude_suspended and "is_suspended" in daily_indicators.columns:
            suspended = set(daily_indicators[daily_indicators["is_suspended"] == True].index.tolist()
                           if isinstance(daily_indicators.index, pd.Index)
                           else daily_indicators[daily_indicators["is_suspended"] == True]["code"].tolist())
            codes -= suspended

        # 4. 剔除市值最小15%的微型股
        if self.exclude_micro_cap_pct and "circ_mv" in daily_indicators.columns:
            mv = daily_indicators["circ_mv"].dropna()
            if len(mv) > 0:
                threshold = mv.quantile(self.exclude_micro_cap_pct)
                micro_codes = set(mv[mv < threshold].index.tolist()
                                 if isinstance(mv.index, pd.Index)
                                 else daily_indicators.loc[mv[mv < threshold].index, "code"].tolist())
                codes -= micro_codes

        return pd.Index(sorted(codes))
