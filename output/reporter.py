"""
信号生成器

根据策略打分结果，生成每日调仓清单：
- 新买入：本期入选但当前未持有的
- 继续持有：连续入选的
- 卖出：当前持有但本期落选的
"""

import pandas as pd
from datetime import date, datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class TradeSignal:
    """单个交易信号"""
    code: str
    name: str = ""
    action: str = ""        # "BUY" / "SELL" / "HOLD"
    target_weight: float = 0.0
    current_weight: float = 0.0
    rank: int = 0           # 在TOP N中的排名
    total_score: float = 0.0
    reason: str = ""        # 信号理由


@dataclass
class DailyReport:
    """每日调仓报告"""
    strategy_name: str = ""
    report_date: date = None
    top_n: int = 20
    new_buys: List[TradeSignal] = field(default_factory=list)
    sells: List[TradeSignal] = field(default_factory=list)
    holds: List[TradeSignal] = field(default_factory=list)
    account_summary: Dict = field(default_factory=dict)
    
    def summary(self) -> str:
        """生成可读摘要"""
        lines = [
            "=" * 50,
            f"  {self.strategy_name}",
            f"  日期: {self.report_date}",
            f"  TOP {self.top_n} 选股",
            "=" * 50,
        ]
        
        if self.new_buys:
            lines.append(f"\n  🟢 买入 ({len(self.new_buys)}只):")
            for s in self.new_buys[:5]:
                lines.append(f"    {s.code} {s.name:8s} 排名#{s.rank} 目标仓位{s.target_weight:.1%}")
        
        if self.sells:
            lines.append(f"\n  🔴 卖出 ({len(self.sells)}只):")
            for s in self.sells[:5]:
                lines.append(f"    {s.code} {s.name:8s} 原因: {s.reason}")
        
        if self.holds:
            lines.append(f"\n  🔵 继续持有 ({len(self.holds)}只): TOP {len(self.holds)} 只")
        
        if self.account_summary:
            lines.append(f"\n  📊 账户概要:")
            for k, v in self.account_summary.items():
                lines.append(f"    {k}: {v}")
        
        return "\n".join(lines)
    
    def to_markdown(self) -> str:
        """生成飞书/企业微信Markdown消息"""
        md = [
            f"**【{self.strategy_name}】** {self.report_date}",
            "",
        ]
        
        if self.new_buys:
            md.append(f"🟢 **买入 {len(self.new_buys)} 只**")
            for s in self.new_buys[:8]:
                md.append(f"- {s.code} {s.name} 排名#{s.rank} 仓位{s.target_weight:.1%}")
            md.append("")
        
        if self.sells:
            md.append(f"🔴 **卖出 {len(self.sells)} 只**")
            for s in self.sells[:8]:
                md.append(f"- {s.code} {s.name} ({s.reason})")
            md.append("")
        
        if self.account_summary:
            md.append(f"📊 总仓位: {self.account_summary.get('position_pct', '?')}")
            md.append(f"📊 持股数: {self.account_summary.get('n_holdings', '?')}")
        
        return "\n".join(md)


class SignalReporter:
    """
    信号生成器
    
    输入：策略打分结果 + 当前持仓
    输出：调仓清单（买入/卖出/持有）
    """
    
    def __init__(self, strategy_name: str = "", top_n: int = 20):
        self.strategy_name = strategy_name
        self.top_n = top_n
    
    def generate(
        self,
        report_date: date,
        scored_stocks: pd.DataFrame,  # index=code, columns含total_score
        current_holdings: Optional[Dict[str, int]] = None,  # {code: shares}
        stock_names: Optional[Dict[str, str]] = None,       # {code: name}
        account_info: Optional[Dict] = None,                 # 账户信息
    ) -> DailyReport:
        """
        生成每日调仓报告
        
        Args:
            report_date: 报告日期
            scored_stocks: 打分结果（已按total_score降序排列）
            current_holdings: 当前持仓
            stock_names: 股票名称映射
            account_info: 账户概要（总资产、仓位等）
        """
        report = DailyReport(
            strategy_name=self.strategy_name,
            report_date=report_date,
            top_n=self.top_n,
            account_summary=account_info or {},
        )
        
        current_holdings = current_holdings or {}
        stock_names = stock_names or {}
        
        # 本次入选的股票
        selected = scored_stocks.head(self.top_n).index.tolist()
        
        for rank, (code, row) in enumerate(scored_stocks.head(self.top_n).iterrows(), 1):
            signal = TradeSignal(
                code=code,
                name=stock_names.get(code, ""),
                rank=rank,
                total_score=row.get('total_score', 0),
                target_weight=1.0 / self.top_n,
            )
            
            if code in current_holdings:
                signal.action = "HOLD"
                signal.current_weight = current_holdings[code] / sum(current_holdings.values()) if current_holdings else 0
                report.holds.append(signal)
            else:
                signal.action = "BUY"
                signal.reason = f"新入选TOP{self.top_n}，排名#{rank}"
                report.new_buys.append(signal)
        
        # 当前持有但本次落选的 → 卖出
        for code in current_holdings:
            if code not in selected:
                signal = TradeSignal(
                    code=code,
                    name=stock_names.get(code, ""),
                    action="SELL",
                    current_weight=current_holdings[code] / sum(current_holdings.values()) if current_holdings else 0,
                    reason="跌出TOP榜单",
                )
                report.sells.append(signal)
        
        return report
    
    def generate_multi_strategy(
        self,
        report_date: date,
        strategy_results: Dict[str, pd.DataFrame],  # {strategy_name: scored_df}
        current_holdings: Optional[Dict[str, int]] = None,
        stock_names: Optional[Dict[str, str]] = None,
    ) -> List[DailyReport]:
        """批量生成多个策略的报告"""
        reports = []
        for sname, scored in strategy_results.items():
            reporter = SignalReporter(sname, self.top_n)
            report = reporter.generate(report_date, scored, current_holdings, stock_names)
            reports.append(report)
        return reports
