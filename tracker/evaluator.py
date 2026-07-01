"""
评估器 — 定期（周/月）对比策略 vs 基准，给出评估意见
"""
from datetime import date, timedelta
from typing import Optional
import numpy as np
import pandas as pd

from . import db

BENCHMARK_NAME = {"000300": "沪深300"}


class PeriodicEvaluator:
    """定期评估器"""

    def __init__(self, strategy: str = "best_five_factor"):
        self.strategy = strategy

    def evaluate_weekly(self, end_date: Optional[date] = None) -> str:
        """生成周评估报告"""
        if end_date is None:
            end_date = date.today()
        start_date = end_date - timedelta(days=7)
        return self._evaluate(start_date, end_date, "weekly")

    def evaluate_monthly(self, end_date: Optional[date] = None) -> str:
        """生成月评估报告"""
        if end_date is None:
            end_date = date.today()
        start_date = end_date - timedelta(days=30)
        return self._evaluate(start_date, end_date, "monthly")

    def _evaluate(self, start: date, end: date, report_type: str) -> str:
        """核心评估逻辑"""
        perf = db.get_performance_summary(self.strategy, days=60)
        if perf.empty:
            return "暂无足够数据进行评估"

        perf = perf.sort_values("trade_date")
        perf = perf[(perf["trade_date"] >= start.isoformat()) & (perf["trade_date"] <= end.isoformat())]

        if len(perf) < 3:
            return f"评估期 {start}~{end} 数据不足（仅{len(perf)}个交易日）"

        # 计算指标
        strategy_returns = perf["daily_return"].values
        benchmark_returns = perf["benchmark_return"].dropna().values

        strategy_cum = (np.prod(1 + strategy_returns / 100) - 1) * 100
        benchmark_cum = (np.prod(1 + benchmark_returns / 100) - 1) * 100 if len(benchmark_returns) > 0 else 0

        win_days = (strategy_returns > 0).sum()
        total_days = len(strategy_returns)
        win_rate = win_days / total_days * 100

        # 超额收益
        alpha = strategy_cum - benchmark_cum

        # 波动率
        volatility = np.std(strategy_returns) * np.sqrt(252)

        # 最大回撤（简化）
        cum_series = np.cumprod(1 + strategy_returns / 100)
        peak = np.maximum.accumulate(cum_series)
        drawdown = (cum_series / peak - 1).min() * 100

        # 生成评估意见
        opinions = []
        if strategy_cum > 0:
            opinions.append(f"✅ 策略取得正收益 {strategy_cum:+.2f}%")
        else:
            opinions.append(f"⚠️ 策略录得负收益 {strategy_cum:+.2f}%")

        if alpha > 0:
            opinions.append(f"✅ 跑赢基准 +{alpha:.2f}%（超额收益）")
        else:
            opinions.append(f"📉 跑输基准 {alpha:.2f}%")

        if win_rate > 55:
            opinions.append(f"✅ 胜率 {win_rate:.0f}%，优秀")
        elif win_rate > 45:
            opinions.append(f"⚖️ 胜率 {win_rate:.0f}%，适中")
        else:
            opinions.append(f"⚠️ 胜率 {win_rate:.0f}%，偏低")

        if abs(drawdown) < 5:
            opinions.append(f"✅ 最大回撤仅 {drawdown:.1f}%，风险控制好")
        elif abs(drawdown) < 10:
            opinions.append(f"⚖️ 最大回撤 {drawdown:.1f}%，正常范围")
        else:
            opinions.append(f"⚠️ 最大回撤 {drawdown:.1f}%，注意风险")

        # 组装报告
        report = f"""
{'='*60}
📈 模拟盘{report_type}评估报告
{'='*60}
策略: {self.strategy}
区间: {start} ~ {end}
交易日: {total_days}天

📊 收益表现:
  策略收益:  {strategy_cum:+.2f}%
  基准收益:  {benchmark_cum:+.2f}%
  超额收益:  {alpha:+.2f}%
  日胜率:    {win_rate:.0f}%

📉 风险指标:
  年化波动:  {volatility:.1f}%
  最大回撤:  {drawdown:.1f}%

💡 评估意见:
  {"".join(f'  {o}' for o in opinions)}

{'='*60}
"""
        # 保存到数据库
        db.save_report(end, report_type, self.strategy, start, end, report.strip())

        return report


def generate_and_print(strategy: str = "best_five_factor"):
    """生成并打印周报+月报"""
    evaluator = PeriodicEvaluator(strategy)

    print(evaluator.evaluate_weekly())
    print(evaluator.evaluate_monthly())


if __name__ == "__main__":
    generate_and_print()
