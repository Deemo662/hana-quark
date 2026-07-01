"""
股票池构建模块 v2
注册制后升级：更紧的过滤、更多维度
"""
from datetime import date, timedelta
from typing import Optional
import pandas as pd


class UniverseBuilder:
    """构建可投资股票池"""

    def __init__(
        self,
        exclude_st: bool = True,
        exclude_new_less_days: int = 500,       # ★v2: 上市<2年剔除（原180天）
        exclude_suspended: bool = True,
        exclude_micro_cap_pct: float = 0.20,    # ★v2: 剔除后20%（原15%）
        min_daily_amount: float = 5_000_000,    # ★v2: 日均成交额>500万（防僵尸股）
        min_turnover_pct: float = 0.1,          # ★v2: 日均换手率>0.1%
        exclude_pe_negative: bool = True,        # ★v2: 剔除负PE
    ):
        self.exclude_st = exclude_st
        self.exclude_new_less_days = exclude_new_less_days
        self.exclude_suspended = exclude_suspended
        self.exclude_micro_cap_pct = exclude_micro_cap_pct
        self.min_daily_amount = min_daily_amount
        self.min_turnover_pct = min_turnover_pct
        self.exclude_pe_negative = exclude_pe_negative

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

        # 1. 剔除上市不足N天的新股/次新股（v2: 500天≈2年）
        if self.exclude_new_less_days and "list_date" in stock_list.columns:
            cutoff = pd.Timestamp(trade_date) - timedelta(days=self.exclude_new_less_days)
            list_dates = pd.to_datetime(stock_list["list_date"], errors='coerce')
            valid_new = stock_list[list_dates <= cutoff]
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

        # 4. 剔除市值最小N%的微型股（v2: 20%）
        if self.exclude_micro_cap_pct and "circ_mv" in daily_indicators.columns:
            mv = daily_indicators["circ_mv"].dropna()
            if len(mv) > 0:
                threshold = mv.quantile(self.exclude_micro_cap_pct)
                micro_codes = set(mv[mv < threshold].index.tolist()
                                 if isinstance(mv.index, pd.Index)
                                 else daily_indicators.loc[mv[mv < threshold].index, "code"].tolist())
                codes -= micro_codes

        # 5. ★v2新增: 剔除负PE
        if self.exclude_pe_negative and "pe_ttm" in daily_indicators.columns:
            pe = daily_indicators["pe_ttm"]
            neg_pe_codes = set(pe[pe < 0].index.tolist()
                              if isinstance(pe.index, pd.Index)
                              else daily_indicators[pe < 0]["code"].tolist())
            codes -= neg_pe_codes

        # 6. ★v2新增: 日均成交额过滤（防僵尸股）
        if self.min_daily_amount and "amount" in daily_indicators.columns:
            amt = daily_indicators["amount"]
            low_amt_codes = set(amt[amt < self.min_daily_amount].index.tolist()
                               if isinstance(amt.index, pd.Index)
                               else daily_indicators[amt < self.min_daily_amount]["code"].tolist())
            codes -= low_amt_codes

        return pd.Index(sorted(codes))
