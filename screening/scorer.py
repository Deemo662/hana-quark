"""
因子打分 + 股票排序模块
"""
from datetime import date
from typing import Optional
import pandas as pd
import numpy as np

from factors.base import BaseFactor, FactorData


class FactorScorer:
    """多因子打分排序"""

    def __init__(self, sort_orders: Optional[dict[str, str]] = None):
        """
        sort_orders: {factor_name: "asc"|"desc"}，asc=越小排名越高
        """
        self.sort_orders = sort_orders or {}

    def compute_factors(
        self,
        factor_names: list[str],
        data: FactorData,
        universe: pd.Index,
    ) -> dict[str, pd.Series]:
        """计算所有因子的原始值"""
        from factors.base import FACTOR_REGISTRY

        results = {}
        for fname in factor_names:
            factor_cls = FACTOR_REGISTRY.get(fname)
            if factor_cls is None:
                print(f"警告: 因子 {fname} 未注册，跳过")
                continue
            factor = factor_cls()
            raw = factor.compute(data)
            # 只保留股票池内的
            raw = raw[raw.index.isin(universe)]
            # 去极值
            raw = factor.winsorize(raw.dropna())
            results[fname] = raw
        return results

    def score(
        self,
        factor_values: dict[str, pd.Series],
        weights: Optional[dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        对因子值打分排名，生成综合得分
        返回: DataFrame columns=[factor_scores..., total_score], index=stock_code
        """
        if not factor_values:
            return pd.DataFrame()

        # 等权
        if weights is None:
            weights = {k: 1.0 / len(factor_values) for k in factor_values}

        scores = {}
        for fname, values in factor_values.items():
            order = self.sort_orders.get(fname, "desc")
            # rank: 升序则值越小rank越高
            ascending = order == "asc"
            ranked = values.rank(ascending=ascending, pct=True)
            w = weights.get(fname, 0)
            scores[f"{fname}_score"] = ranked * w * 100

        df = pd.DataFrame(scores)
        df["total_score"] = df.sum(axis=1)
        return df.sort_values("total_score", ascending=False)

    def select_top(self, scored: pd.DataFrame, top_n: int = 20) -> list[str]:
        """选出得分最高的N只股票"""
        return scored.head(top_n).index.tolist()
