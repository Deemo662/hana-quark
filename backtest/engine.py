"""
回测引擎封装
基于 Backtrader，提供策略定义 + 绩效分析

核心职责：
  1. QuantStrategy: 每月调仓，等权持有top N股票
  2. BacktestEngine: 封装Cerebro、添加分析器、提取绩效指标
  3. 完整的A股手续费建模（佣金+印花税+滑点）
"""
import backtrader as bt
import pandas as pd
import numpy as np
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# A股手续费模型
# ============================================================

class AShareCommission(bt.CommInfoBase):
    """A股手续费：佣金万2.5（双向）+ 印花税千0.5（仅卖出）+ 滑点千1"""
    params = (
        ('commission', 0.00025),       # 佣金率
        ('stamp_duty', 0.0005),        # 印花税率（仅卖出）
        ('slippage', 0.001),           # 滑点
        ('stocklike', True),           # 股票模式
        ('commtype', bt.CommInfoBase.COMM_PERC),  # 按比例收费
    )

    def _getcommission(self, size, price, pseudoexec):
        """
        size: 股数 (>0买入, <0卖出)
        price: 执行价格
        """
        value = abs(size) * price

        # 佣金：双向
        comm = value * self.p.commission

        # 最低佣金5元（A股惯例）
        comm = max(comm, 5.0 if value > 0 else 0)

        # 印花税：仅卖出
        if size < 0:
            comm += value * self.p.stamp_duty

        return comm


# ============================================================
# 绩效结果
# ============================================================

@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    start_date: date
    end_date: date
    initial_capital: float
    final_value: float
    total_return: float          # 总收益率 (%)
    cagr: float                  # 年复合收益率 (%)
    sharpe_ratio: float          # 夏普比率
    max_drawdown: float          # 最大回撤 (%)
    annual_volatility: float     # 年化波动率 (%)
    win_rate: float              # 胜率 (%)
    calmar_ratio: float          # 卡玛比率 (CAGR / max_dd)
    monthly_returns: pd.Series = field(default_factory=pd.Series)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    daily_returns: pd.Series = field(default_factory=pd.Series)


# ============================================================
# 量化调仓策略
# ============================================================

class QuantStrategy(bt.Strategy):
    """
    每月调仓，等权持有top N股票

    params:
      holdings: {date_str: [codes]}  每月持仓快照
      rebalance_on_next: 如果调仓日为非交易日，顺延到下一交易日
    """
    params = (
        ("holdings", {}),
        ("target_budget", 0.98),  # 留2%现金缓冲
    )

    def __init__(self):
        # 预处理持仓：按日期排序
        self._schedule = sorted(
            (datetime.strptime(k, "%Y-%m-%d").date(), v)
            for k, v in self.p.holdings.items()
        )
        self._cursor = 0                # 当前调仓计划下标
        self._last_applied_date = None  # 上次已执行的调仓日

    def next(self):
        current_date = self.datas[0].datetime.date(0)

        # 推进cursor：找到当前日期之前的最新调仓计划
        while (self._cursor + 1 < len(self._schedule)
               and self._schedule[self._cursor + 1][0] <= current_date):
            self._cursor += 1

        if self._cursor >= len(self._schedule):
            return

        target_date, target_codes = self._schedule[self._cursor]

        # 只在首次遇到该调仓日时执行（顺延逻辑：非交易日时自然下一个bar执行）
        if self._last_applied_date == target_date:
            return

        self._last_applied_date = target_date
        self._rebalance(target_codes)

    def _rebalance(self, target_codes):
        """等权调仓到目标股票列表"""
        n = len(target_codes)
        if n == 0:
            return

        target_pct = self.p.target_budget / n

        code_to_data = {d._name: d for d in self.datas}

        for code, d in code_to_data.items():
            if code in target_codes:
                self.order_target_percent(data=d, target=target_pct)
            else:
                self.order_target_percent(data=d, target=0.0)


# ============================================================
# 回测引擎
# ============================================================

class BacktestEngine:
    """回测引擎"""

    def __init__(
        self,
        initial_capital: float = 100_000,
        commission: float = 0.00025,
        stamp_duty: float = 0.0005,
        slippage: float = 0.001,
        risk_free_rate: float = 0.03,
    ):
        self.initial_capital = initial_capital
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slippage = slippage
        self.risk_free_rate = risk_free_rate

    # ---------- public API ----------

    def run(
        self,
        strategy_name: str,
        price_data: pd.DataFrame,
        holdings: dict[str, list[str]],
    ) -> BacktestResult:
        """
        执行回测

        Parameters
        ----------
        strategy_name : 策略名称
        price_data : MultiIndex (code, date) DataFrame
                     必须包含 close 列；缺 open/high/low/volume 时自动补全
        holdings : { "YYYY-MM-DD": [code1, code2, ...] }  每月持仓
        """
        cerebro = self._build_cerebro(price_data, holdings)
        start_val = cerebro.broker.getvalue()
        results = cerebro.run()
        final_val = cerebro.broker.getvalue()

        return self._extract_result(
            strategy_name=strategy_name,
            price_data=price_data,
            start_val=start_val,
            final_val=final_val,
            strat=results[0],
        )

    # ---------- internal ----------

    def _build_cerebro(self, price_data: pd.DataFrame, holdings: dict) -> bt.Cerebro:
        cerebro = bt.Cerebro()

        # 资金
        cerebro.broker.setcash(self.initial_capital)

        # 手续费
        comminfo = AShareCommission(
            commission=self.commission,
            stamp_duty=self.stamp_duty,
            slippage=self.slippage,
        )
        cerebro.broker.addcommissioninfo(comminfo)

        # 滑点（固定千1）
        cerebro.broker.set_slippage_perc(self.slippage)

        # 逐只添加行情数据
        codes = price_data.index.get_level_values(0).unique()
        for code in codes:
            df = price_data.loc[code]
            if not isinstance(df, pd.DataFrame) or len(df) < 2:
                continue
            df = df.sort_index()
            # 确保index为DatetimeIndex（Backtrader需要Timestamp而非date）
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            df = self._ensure_ohlcv(df)
            data = bt.feeds.PandasData(
                dataname=df,
                datetime=None,
                open="open",
                high="high",
                low="low",
                close="close",
                volume="volume",
                openinterest=-1,
                name=code,
            )
            cerebro.adddata(data)

        # 策略
        cerebro.addstrategy(QuantStrategy, holdings=holdings)

        # 分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                            timeframe=bt.TimeFrame.Days,
                            riskfreerate=self.risk_free_rate,
                            annualize=True)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name="annreturn")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="timereturn",
                            timeframe=bt.TimeFrame.Months)
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="dailyreturn",
                            timeframe=bt.TimeFrame.Days)

        return cerebro

    def _extract_result(
        self,
        strategy_name: str,
        price_data: pd.DataFrame,
        start_val: float,
        final_val: float,
        strat,
    ) -> BacktestResult:
        dates = price_data.index.get_level_values(1)
        years = max((dates.max() - dates.min()).days / 365.25, 0.01)

        total_return = (final_val / start_val - 1) * 100
        cagr = ((final_val / start_val) ** (1 / years) - 1) * 100

        # 夏普
        sharpe_analysis = strat.analyzers.sharpe.get_analysis()
        sharpe = sharpe_analysis.get("sharperatio", None)
        # 确保是float类型（有可能返回OrderedDict等对象）
        if sharpe is None or not isinstance(sharpe, (int, float)):
            sharpe = 0.0

        # 最大回撤
        dd = strat.analyzers.drawdown.get_analysis()
        max_dd = dd.get("max", {}).get("drawdown", 0) or 0

        # 月度收益
        month_raw = strat.analyzers.timereturn.get_analysis()
        monthly_returns = pd.Series(month_raw) if month_raw else pd.Series(dtype=float)

        # 年化波动率
        if len(monthly_returns) > 1:
            annual_vol = monthly_returns.std() * np.sqrt(12) * 100
        else:
            annual_vol = 0.0

        # 胜率（从TradeAnalyzer提取）
        trade_analyzer = strat.analyzers.trades.get_analysis()
        win_rate = self._calc_win_rate(trade_analyzer)

        # 卡玛比率
        calmar = cagr / max(abs(max_dd), 0.01) if max_dd else 0.0

        # 交易记录摘要
        trades_df = self._extract_trade_summary(trade_analyzer)

        # 日收益（供外部使用）
        daily_raw = strat.analyzers.dailyreturn.get_analysis()
        daily_returns = pd.Series(daily_raw) if daily_raw else pd.Series(dtype=float)

        return BacktestResult(
            strategy_name=strategy_name,
            start_date=dates.min(),
            end_date=dates.max(),
            initial_capital=self.initial_capital,
            final_value=final_val,
            total_return=total_return,
            cagr=cagr,
            sharpe_ratio=float(sharpe),
            max_drawdown=float(max_dd),
            annual_volatility=annual_vol,
            win_rate=win_rate,
            calmar_ratio=calmar,
            monthly_returns=monthly_returns,
            trades=trades_df,
            daily_returns=daily_returns,
        )

    # ---------- helpers ----------

    @staticmethod
    def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """补全缺失的OHLCV列"""
        for col, default in [("open", "close"), ("high", "close"),
                              ("low", "close"), ("volume", None)]:
            if col not in df.columns:
                df[col] = df[default] if default else 0
        return df

    @staticmethod
    def _calc_win_rate(ta: dict) -> float:
        """从TradeAnalyzer提取胜率"""
        # Backtrader 1.9 的 TradeAnalyzer 结构
        won = ta.get("won", {})
        lost = ta.get("lost", {})
        if isinstance(won, dict) and isinstance(lost, dict):
            w = won.get("total", 0) or 0
            l = lost.get("total", 0) or 0
            total = w + l
            return (w / total * 100) if total > 0 else 0.0
        # 降级路径
        total_closed = ta.get("total", {}).get("total", 0)
        won_closed = ta.get("won", {}).get("total", 0)
        if total_closed and total_closed > 0:
            return (won_closed / total_closed * 100)
        return 0.0

    @staticmethod
    def _extract_trade_summary(ta: dict) -> pd.DataFrame:
        rows = []
        total = ta.get("total", {})
        if isinstance(total, dict):
            rows.append({
                "total_trades": total.get("total", 0),
                "won": ta.get("won", {}).get("total", 0),
                "lost": ta.get("lost", {}).get("total", 0),
                "pnl_gross_total": ta.get("pnl", {}).get("gross", {}).get("total", 0),
                "pnl_net_total": ta.get("pnl", {}).get("net", {}).get("total", 0),
            })
        return pd.DataFrame(rows)


# ============================================================
# 报告输出
# ============================================================

def print_report(result: BacktestResult):
    """打印格式化的回测报告"""
    print()
    print("╔" + "═" * 63 + "╗")
    print(f"║  策略: {result.strategy_name:<53s} ║")
    print(f"║  区间: {str(result.start_date)} ~ {str(result.end_date):<29s} ║")
    print("╠" + "═" * 63 + "╣")
    print(f"║  初始资金     ¥{result.initial_capital:>15,.0f}              ║")
    print(f"║  最终权益     ¥{result.final_value:>15,.0f}              ║")
    print("╠" + "═" * 63 + "╣")
    print(f"║  总收益率     {result.total_return:>15.2f}%              ║")
    print(f"║  年化收益率   {result.cagr:>15.2f}%              ║")
    print(f"║  夏普比率     {result.sharpe_ratio:>15.2f}                ║")
    print(f"║  最大回撤     {result.max_drawdown:>15.2f}%              ║")
    print(f"║  年化波动率   {result.annual_volatility:>15.2f}%              ║")
    print(f"║  卡玛比率     {result.calmar_ratio:>15.2f}                ║")
    print(f"║  胜率         {result.win_rate:>15.1f}%              ║")
    print("╠" + "═" * 63 + "╣")

    if len(result.monthly_returns) > 0:
        mr = result.monthly_returns
        print(f"║  月度收益统计                                       ║")
        print(f"║    正收益月数: {(mr > 0).sum():<3d}  负收益月数: {(mr < 0).sum():<3d}                   ║")
        print(f"║    月均收益:   {mr.mean() * 100:>8.2f}%                            ║")
        print(f"║    最佳月:     {mr.max() * 100:>8.2f}%                            ║")
        print(f"║    最差月:     {mr.min() * 100:>8.2f}%                            ║")

    if len(result.trades) > 0:
        print(f"╠" + "═" * 63 + "╣")
        print(f"║  交易统计                                         ║")
        for _, row in result.trades.iterrows():
            t = int(row.get("total_trades", 0))
            w = int(row.get("won", 0))
            l = int(row.get("lost", 0))
            pnl = row.get("pnl_net_total", 0) or 0
            print(f"║    总交易: {t:<4d}  盈利: {w:<4d}  亏损: {l:<4d}                  ║")
            print(f"║    净盈亏: ¥{pnl:>12,.0f}                              ║")

    print("╚" + "═" * 63 + "╝")
    print()
