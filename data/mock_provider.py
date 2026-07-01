"""
模拟数据源 — 用于架构验证
生成 A股典型数据，覆盖全部因子计算链路

更新日志:
  - 新增 ev2sales 字段（EV/Sales 因子）
  - 新增 equity_to_debt 字段（权益/带息债务因子）
  - 25只样本股票区分大/中/小盘风格
"""
import random
from datetime import date, timedelta
from typing import Optional
import pandas as pd
import numpy as np

from .provider import DataProvider


class MockProvider(DataProvider):
    """模拟数据源：生成符合A股统计特征的假数据，用于链路验证"""

    # 25只A股，覆盖大/中/小盘
    STOCKS = {
        # ---- 大盘蓝筹 (9只) ----
        "600519": "贵州茅台",    # 白酒龙头，高价股
        "000858": "五粮液",      # 白酒
        "000568": "泸州老窖",    # 白酒
        "600036": "招商银行",    # 银行
        "601318": "中国平安",    # 保险
        "600900": "长江电力",    # 电力
        "000333": "美的集团",    # 家电
        "000651": "格力电器",    # 家电
        "002415": "海康威视",    # 安防

        # ---- 中盘成长 (8只) ----
        "300750": "宁德时代",    # 新能源龙头
        "002594": "比亚迪",      # 新能源车
        "601012": "隆基绿能",    # 光伏
        "600276": "恒瑞医药",    # 医药
        "300760": "迈瑞医疗",    # 医疗器械
        "000002": "万科A",       # 地产
        "600030": "中信证券",    # 券商
        "600585": "海螺水泥",    # 建材

        # ---- 小盘风格 (8只) ----
        "300001": "特锐德",      # 充电桩
        "300002": "神州泰岳",    # 软件
        "300003": "乐普医疗",    # 医疗器械
        "002001": "新和成",      # 精细化工
        "002003": "伟星股份",    # 辅料
        "600887": "伊利股份",    # 乳业（这里归小盘以分散）
        "000001": "平安银行",    # 银行（这里归小盘以分散）
        "601899": "紫金矿业",    # 矿业（这里归小盘以分散）
    }

    # 股票风格标签
    STYLE = {
        "600519": "large", "000858": "large", "000568": "large",
        "600036": "large", "601318": "large", "600900": "large",
        "000333": "large", "000651": "large", "002415": "large",
        "300750": "mid",   "002594": "mid",   "601012": "mid",
        "600276": "mid",   "300760": "mid",   "000002": "mid",
        "600030": "mid",   "600585": "mid",
        "300001": "small", "300002": "small", "300003": "small",
        "002001": "small", "002003": "small", "600887": "small",
        "000001": "small", "601899": "small",
    }

    # 每只股票的初始价格和波动率（模拟不同风格）
    _STOCK_PARAMS = {
        "600519": {"base_price": 1800, "vol": 0.018},  # 茅台高价低波
        "000858": {"base_price": 150,  "vol": 0.020},
        "000568": {"base_price": 200,  "vol": 0.022},
        "600036": {"base_price": 35,   "vol": 0.014},
        "601318": {"base_price": 45,   "vol": 0.016},
        "600900": {"base_price": 22,   "vol": 0.012},
        "000333": {"base_price": 55,   "vol": 0.018},
        "000651": {"base_price": 35,   "vol": 0.017},
        "002415": {"base_price": 32,   "vol": 0.020},
        "300750": {"base_price": 200,  "vol": 0.028},
        "002594": {"base_price": 250,  "vol": 0.026},
        "601012": {"base_price": 30,   "vol": 0.030},
        "600276": {"base_price": 45,   "vol": 0.022},
        "300760": {"base_price": 280,  "vol": 0.024},
        "000002": {"base_price": 15,   "vol": 0.020},
        "600030": {"base_price": 20,   "vol": 0.022},
        "600585": {"base_price": 25,   "vol": 0.018},
        "300001": {"base_price": 15,   "vol": 0.032},
        "300002": {"base_price": 8,    "vol": 0.035},
        "300003": {"base_price": 18,   "vol": 0.028},
        "002001": {"base_price": 25,   "vol": 0.025},
        "002003": {"base_price": 12,   "vol": 0.030},
        "600887": {"base_price": 30,   "vol": 0.020},
        "000001": {"base_price": 12,   "vol": 0.018},
        "601899": {"base_price": 10,   "vol": 0.025},
    }

    def get_stock_list(self, trade_date: Optional[date] = None) -> pd.DataFrame:
        rows = []
        for code, name in self.STOCKS.items():
            rows.append({
                "code": code,
                "name": name,
                "list_date": date(2000, 1, 1),
                "style": self.STYLE.get(code, "mid"),
            })
        return pd.DataFrame(rows).set_index("code")

    def get_market_data(
        self, codes: list[str], start: date, end: date
    ) -> pd.DataFrame:
        """
        生成日线行情（随机游走 + 每只股票独立价格路径）

        Returns:
          MultiIndex (code, date) DataFrame with columns:
            open, high, low, close, volume, amount, turnover_rate
        """
        rows = []
        rng = np.random.RandomState(42)

        for code in codes:
            params = self._STOCK_PARAMS.get(
                code, {"base_price": 30, "vol": 0.025}
            )
            price = params["base_price"]
            vol = params["vol"]

            current_date = start
            while current_date <= end:
                # 跳过周末
                if current_date.weekday() >= 5:
                    current_date += timedelta(days=1)
                    continue

                daily_ret = rng.normal(0.0003, vol)  # 微小正漂移
                price *= (1 + daily_ret)
                price = max(price, 0.5)  # 防止归零

                open_p = price * (1 - rng.uniform(0, 0.005))
                high_p = price * (1 + rng.uniform(0, 0.015))
                low_p = price * (1 - rng.uniform(0, 0.015))
                vol_shares = rng.randint(500000, 80000000)

                rows.append({
                    "code": code,
                    "date": current_date,
                    "open": round(open_p, 2),
                    "high": round(high_p, 2),
                    "low": round(low_p, 2),
                    "close": round(price, 2),
                    "volume": vol_shares,
                    "amount": round(price * vol_shares, 2),
                    "turnover_rate": round(rng.uniform(0.3, 6.0), 2),
                })

                current_date += timedelta(days=1)

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.set_index(["code", "date"]).sort_index()
        return df

    def get_daily_indicators(
        self, codes: list[str], trade_date: date
    ) -> pd.DataFrame:
        """
        生成估值指标（日频快照）

        新增字段: ev2sales（EV/Sales），用于 value_ev2sales 因子
        """
        seed = hash(str(trade_date)) % 2**32
        rng = np.random.RandomState(seed)
        rows = []

        for code in codes:
            style = self.STYLE.get(code, "mid")

            # 不同风格的估值中枢
            if style == "large":
                pe_center, pb_center, mv_center = 15, 2.0, 500
            elif style == "mid":
                pe_center, pb_center, mv_center = 28, 3.5, 200
            else:  # small
                pe_center, pb_center, mv_center = 45, 4.5, 50

            pe = max(1, rng.normal(pe_center, pe_center * 0.4))
            pb = max(0.3, rng.normal(pb_center, pb_center * 0.5))
            total_mv = max(5, rng.normal(mv_center, mv_center * 0.5))

            rows.append({
                "code": code,
                "name": self.STOCKS.get(code, "?"),
                "pe_ttm": round(pe, 2),
                "pb": round(pb, 2),
                "total_mv": round(total_mv, 2),
                "circ_mv": round(total_mv * rng.uniform(0.6, 1.0), 2),
                "ps_ttm": round(max(0.3, rng.normal(2.5, 1.5)), 2),
                "pcf_ttm": round(max(1, rng.normal(8, 4)), 2),
                "ev2ebitda": round(max(1, rng.normal(12, 6)), 2),
                "ev2sales": round(max(0.5, rng.normal(3.0, 2.0)), 2),  # ← 新增
                "dividend_yield": round(max(0, rng.normal(1.8, 1.2)), 2),
            })

        return pd.DataFrame(rows).set_index("code")

    def get_financial_data(
        self, codes: list[str], report_date: date
    ) -> pd.DataFrame:
        """
        生成财务数据（季度/年度快照）

        新增字段: equity_to_debt（权益/带息债务），用于 safety_equity2debt 因子
        """
        seed = hash(str(report_date)) % 2**32
        rng = np.random.RandomState(seed)
        rows = []

        for code in codes:
            style = self.STYLE.get(code, "mid")

            # 大盘股：财务更稳健；小盘股：波动更大
            if style == "large":
                roe_center, debt_center, equity_debt_center = 15, 55, 2.5
            elif style == "mid":
                roe_center, debt_center, equity_debt_center = 10, 45, 1.8
            else:
                roe_center, debt_center, equity_debt_center = 6, 35, 1.2

            rows.append({
                "code": code,
                "roe": round(rng.normal(roe_center, 8), 2),
                "roa": round(rng.normal(roe_center * 0.5, 4), 2),
                "roic": round(rng.normal(roe_center * 0.8, 7), 2),
                "gross_margin": round(rng.normal(35, 15), 2),
                "net_margin": round(rng.normal(12, 8), 2),
                "debt_to_assets": round(rng.normal(debt_center, 20), 2),
                "revenue_yoy": round(rng.normal(15, 12), 2),
                "profit_yoy": round(rng.normal(12, 15), 2),
                "ocf_to_profit": round(rng.normal(1.0, 0.5), 2),
                "sales_cash_to_revenue": round(rng.normal(1.0, 0.3), 2),
                "interest_coverage": round(max(0.5, rng.normal(5, 3)), 2),
                "equity_to_debt": round(max(0.3, rng.normal(equity_debt_center, 1.5)), 2),  # ← 新增
            })

        return pd.DataFrame(rows).set_index("code")
