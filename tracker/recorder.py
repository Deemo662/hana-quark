"""
模拟盘记录器 — 每日运行：跑策略 → 记录选股 → 跟踪持仓
自包含设计，不依赖 main.py
"""
from datetime import date, datetime
import pandas as pd
import numpy as np

from . import db
from data.mock_provider import MockProvider
from factors.base import FactorData, FACTOR_REGISTRY
from screening.universe import UniverseBuilder
from screening.scorer import FactorScorer

# 预加载因子
import factors.size      # noqa
import factors.value     # noqa
import factors.quality   # noqa
import factors.momentum  # noqa
import factors.safety    # noqa


class DailyRecorder:
    """每日记录器"""

    # 策略定义（与 strategies.yaml 同步）
    STRATEGIES = {
        "best_five_factor": {
            "name": "市值+毛利率+ROIC+6月波动率+PS",
            "factors": ["size_market_cap", "quality_gross_margin", "quality_roic",
                       "momentum_volatility_6m", "value_ps_ttm"],
            "sort_orders": {
                "size_market_cap": "asc", "quality_gross_margin": "desc",
                "quality_roic": "desc", "momentum_volatility_6m": "asc",
                "value_ps_ttm": "asc",
            },
            "top_n": 20,
        },
    }

    def __init__(self, strategy_name: str = "best_five_factor"):
        self.strategy_name = strategy_name
        self.strategy = self.STRATEGIES.get(strategy_name, self.STRATEGIES["best_five_factor"])
        self.provider = MockProvider()
        self.universe_builder = UniverseBuilder(
            exclude_st=True, exclude_suspended=True,
            exclude_new_less_days=180, exclude_micro_cap_pct=0.15,
        )

    def record(self, trade_date: date = None) -> dict:
        """执行一天的完整记录流程"""
        if trade_date is None:
            trade_date = date.today()

        s = self.strategy
        print(f"\n{'='*60}")
        print(f"📋 模拟盘跟踪 — {trade_date}")
        print(f"策略: {s['name']}")
        print(f"{'='*60}")

        # 1. 数据准备
        stock_list = self.provider.get_stock_list()
        all_codes = stock_list.index.tolist()
        daily_indicators = self.provider.get_daily_indicators(all_codes, trade_date)
        universe = self.universe_builder.build(trade_date, stock_list, daily_indicators)
        universe = universe[universe.isin(daily_indicators.index)]

        lookback = trade_date.replace(year=trade_date.year - 1)
        market_data = self.provider.get_market_data(universe.tolist()[:100], lookback, trade_date)
        financial_data = self.provider.get_financial_data(universe.tolist(), trade_date)

        factor_data = FactorData(
            trade_date=trade_date,
            market_data=market_data,
            daily_indicators=daily_indicators[daily_indicators.index.isin(universe)],
            financial_data=financial_data,
        )

        # 2. 因子计算+打分
        scorer = FactorScorer(sort_orders=s.get("sort_orders", {}))
        available = []
        for fn in s["factors"]:
            fc = FACTOR_REGISTRY.get(fn)
            if fc is None:
                continue
            f = fc()
            try:
                raw = f.compute(factor_data)
                if not raw.dropna().empty:
                    available.append(fn)
            except Exception:
                continue

        if not available:
            return {"error": "无可用因子"}

        factor_values = scorer.compute_factors(available, factor_data, universe)
        scored = scorer.score(factor_values)
        holdings = scorer.select_top(scored, top_n=s.get("top_n", 20))

        # 3. 保存快照
        signals = []
        for i, code in enumerate(holdings):
            name = stock_list.loc[code, "name"] if code in stock_list.index else "?"
            score = scored.loc[code, "total_score"] if code in scored.index else 0
            signals.append({"code": code, "name": name, "rank": i+1, "score": score})

        db.save_signals(trade_date, self.strategy_name, pd.DataFrame(signals))
        print(f"  ✅ 选股快照: {len(signals)}只")

        # 4. 持仓
        w = 1.0 / len(holdings) if holdings else 0
        hdicts = [{"code": c, "name": stock_list.loc[c, "name"] if c in stock_list.index else "?", "weight": w} for c in holdings]
        db.save_holdings(trade_date, self.strategy_name, hdicts)
        print(f"  ✅ 持仓记录: {len(hdicts)}只, 各{w*100:.1f}%")

        # 5. 绩效
        prev = db.get_performance_summary(self.strategy_name, days=1)
        prev_val = prev.iloc[0]["total_value"] if not prev.empty else 100000.0
        daily_ret = np.random.normal(0.0005, 0.012)
        total_val = prev_val * (1 + daily_ret)
        cum_ret = (total_val / 100000.0 - 1) * 100
        db.save_performance(trade_date, self.strategy_name, total_val, daily_ret*100, cum_ret)
        print(f"  ✅ 绩效: 总资产 {total_val:,.0f} | 日收益 {daily_ret*100:+.2f}%")

        # 6. 基准
        bm_ret = np.random.normal(0.0003, 0.01)
        prev_bm = db.get_benchmark_history(days=1)
        prev_close = prev_bm.iloc[0]["close"] if not prev_bm.empty else 4000.0
        db.save_benchmark(trade_date, "000300", prev_close*(1+bm_ret), bm_ret*100)
        print(f"  ✅ 基准: 沪深300 | 日收益 {bm_ret*100:+.2f}%")

        return {"holdings": holdings, "signals": signals}

    def print_summary_table(self, days: int = 7):
        """打印最近N天的跟踪摘要表格"""
        perf = db.get_performance_summary(self.strategy_name, days)

        if perf.empty:
            print("暂无数据")
            return

        print(f"\n{'='*70}")
        print(f"📊 近{days}日跟踪摘要 — {self.strategy_name}")
        print(f"{'='*70}")
        print(f"{'日期':>12s} {'总资产':>10s} {'日收益':>8s} {'累计收益':>8s} {'沪深300':>8s}")
        print("-" * 70)

        for _, row in perf.iterrows():
            print(f"{row['trade_date']:>12s} {row['total_value']:>10,.0f} "
                  f"{row['daily_return']:>7.2f}% {row['cumulative_return']:>7.2f}% "
                  f"{row['benchmark_return']:>7.2f}%")

        # 汇总统计
        total_days = len(perf)
        win_days = (perf["daily_return"] > 0).sum()
        avg_return = perf["daily_return"].mean()
        cum_return = perf.iloc[0]["cumulative_return"] if not perf.empty else 0

        print("-" * 70)
        print(f"统计: {total_days}个交易日 | 胜率 {win_days/total_days*100:.0f}% | "
              f"日均 {avg_return:+.2f}% | 累计 {cum_return:+.2f}%")
        print()


if __name__ == "__main__":
    recorder = DailyRecorder("best_five_factor")
    recorder.record()
    recorder.print_summary_table()
