"""
回测交叉验证器（第4重防线）

【白话说明】
跑完回测后，自动把结果和董鹏飞书中的数字对比。
如果偏差太大 → 说明代码有bug，必须排查。

【验证基准（来自书本第15章）】
- 整体股票年化基准: 10.0%~10.5%
- TOP1策略（市值+毛利率+ROIC+6月波动率+PS）: 18.44%
- TOP2策略（EV/Sales+ROE+权益/带息债务+6月波动率+3月动量）: 17.26%
- TOP3策略（ROE+6月波动率）: 16.90%
- 市值因子最优最差差值: 6.97%
"""

import numpy as np
import pandas as pd
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =====================================================================
# 书本基准数据（不可修改）
# =====================================================================

BOOK_BENCHMARKS = {
    # 整体市场基准
    "benchmark_return": {
        "book_value": 0.105,         # 整体股票年化10.5%
        "tolerance": 0.02,           # 容差±2%
        "description": "整体股票等权年化收益率",
        "action_if_fail": "检查股票池定义是否与书本一致（市值后15%剔除、ST排除等）"
    },
    
    # 各策略基准
    "best_five_factor": {
        "book_value": 0.1844,
        "tolerance": 0.03,
        "description": "TOP1: 市值+毛利率+ROIC+6月波动率+PS",
    },
    "roe_lowvol": {
        "book_value": 0.1690,
        "tolerance": 0.03,
        "description": "TOP3: ROE+6月波动率",
    },
    "magic_formula_improved": {
        "book_value": 0.1648,
        "tolerance": 0.03,
        "description": "TOP4: 中小市值改进神奇公式",
    },
    "pb_lowvol": {
        "book_value": 0.1514,
        "tolerance": 0.03,
        "description": "TOP8: PB+6月波动率",
    },
    "five_factor_v2": {
        "book_value": 0.1726,
        "tolerance": 0.03,
        "description": "TOP2: EV/Sales+ROE+权益/带息债务+6月波动率+3月动量",
    },
    
    # 单因子基准
    "size_factor_spread": {
        "book_value": 0.0697,        # 最小市值 - 最大市值 = 14.86% - 7.89%
        "tolerance": 0.02,
        "description": "市值因子最优最差分位差值",
        "action_if_fail": "检查市值计算和股票池过滤"
    },
}


@dataclass
class CrossValidationReport:
    """交叉验证报告"""
    strategy_name: str = ""
    book_cagr: float = 0.0        # 书中年化
    actual_cagr: float = 0.0      # 实测年化
    deviation: float = 0.0         # 偏差（实测-书本）
    deviation_pct: float = 0.0     # 偏差百分比
    within_tolerance: bool = False  # 是否在容差内
    confidence: str = "?"          # ✓ △ ✗
    notes: List[str] = field(default_factory=list)
    
    def report_line(self) -> str:
        icon = {"✓": "✓", "△": "△", "✗": "✗", "?": "?"}.get(self.confidence, "?")
        return (
            f"  {icon} {self.strategy_name:30s} "
            f"书本{self.book_cagr:.2%} → 实测{self.actual_cagr:.2%} "
            f"(偏差{self.deviation:+.2%})"
        )


class CrossValidator:
    """
    回测交叉验证器
    
    将回测结果与书本基准对比，判定是否在合理偏差范围内。
    """
    
    def __init__(self, tolerance_override: Dict[str, float] = None):
        """
        Args:
            tolerance_override: 覆盖特定策略的容差，如 {'best_five_factor': 0.05}
        """
        self.benchmarks = BOOK_BENCHMARKS.copy()
        if tolerance_override:
            for k, v in tolerance_override.items():
                if k in self.benchmarks:
                    self.benchmarks[k]['tolerance'] = v
    
    def validate_cagr(
        self,
        strategy_key: str,
        actual_cagr: float,
        strategy_name: str = None,
    ) -> CrossValidationReport:
        """
        校验单个策略的年化收益率
        
        Args:
            strategy_key: 策略键名（需在 BOOK_BENCHMARKS 中存在）
            actual_cagr: 实测年化收益率（小数，如 0.1844）
            strategy_name: 策略显示名（可选）
        
        Returns:
            CrossValidationReport
        """
        report = CrossValidationReport()
        report.strategy_name = strategy_name or strategy_key
        report.actual_cagr = actual_cagr
        
        benchmark = self.benchmarks.get(strategy_key)
        
        if benchmark is None:
            report.confidence = "?"
            report.notes.append(f"策略 '{strategy_key}' 不在书本基准中，仅输出实测值")
            report.book_cagr = 0.0
            report.deviation = 0.0
            return report
        
        report.book_cagr = benchmark['book_value']
        report.deviation = actual_cagr - report.book_cagr
        report.deviation_pct = report.deviation / report.book_cagr if report.book_cagr != 0 else 0
        
        tolerance = benchmark['tolerance']
        report.within_tolerance = abs(report.deviation) <= tolerance
        
        if report.within_tolerance:
            report.confidence = "✓"
        elif abs(report.deviation) <= tolerance * 1.5:
            report.confidence = "△"
            report.notes.append(f"偏差略大（{report.deviation:+.2%}），可能是数据源差异")
        else:
            report.confidence = "✗"
            action = benchmark.get('action_if_fail', '检查因子计算逻辑和股票池定义')
            report.notes.append(f"偏差过大（{report.deviation:+.2%}），{action}")
        
        return report
    
    def validate_all_strategies(
        self,
        results: Dict[str, float],  # {strategy_key: actual_cagr}
    ) -> List[CrossValidationReport]:
        """
        批量校验
        
        Args:
            results: {策略键名: 实测年化收益率}
        
        Returns:
            校验报告列表
        """
        reports = []
        
        for key, cagr in results.items():
            report = self.validate_cagr(key, cagr)
            reports.append(report)
        
        # 汇总
        n_pass = sum(1 for r in reports if r.confidence == "✓")
        n_warn = sum(1 for r in reports if r.confidence == "△")
        n_fail = sum(1 for r in reports if r.confidence == "✗")
        
        logger.info(f"\n交叉验证汇总: ✓{n_pass} △{n_warn} ✗{n_fail} (共{len(reports)}个策略)")
        
        if n_fail > 0:
            logger.warning(f"  ⚠ {n_fail}个策略偏差过大，需要排查代码！")
        
        return reports
    
    def print_summary(self, reports: List[CrossValidationReport]):
        """打印人类可读的交叉验证汇总"""
        print("\n" + "=" * 60)
        print("  回测交叉验证（第4重防线）")
        print("=" * 60)
        print(f"  {'策略':30s} {'书中年化':>8s} {'实测年化':>8s} {'偏差':>8s} {'判定':4s}")
        print(f"  {'─'*30} {'─'*8} {'─'*8} {'─'*8} {'─'*4}")
        
        for r in reports:
            print(r.report_line())
        
        n_pass = sum(1 for r in reports if r.confidence == "✓")
        n_fail = sum(1 for r in reports if r.confidence == "✗")
        
        print(f"\n  结果: ✓{n_pass}通过 ✗{n_fail}异常 (共{len(reports)}个)")
        
        if n_fail > 0:
            print(f"\n  ⚠ 异常策略需要排查：")
            for r in reports:
                if r.confidence == "✗":
                    for note in r.notes:
                        print(f"    - {r.strategy_name}: {note}")
        
        print("=" * 60)
    
    def validate_benchmark(
        self,
        benchmark_cagr: float,
    ) -> CrossValidationReport:
        """
        校验市场基准收益率
        
        书本：整体股票年化10.5%
        """
        return self.validate_cagr("benchmark_return", benchmark_cagr, "整体股票基准")


# =====================================================================
# 便捷函数：从annualized_return直接校验
# =====================================================================

def quick_validate(strategy_key: str, actual_cagr: float) -> str:
    """
    快速校验：返回 ✓/△/✗ 判定
    
    【用法】
    >>> quick_validate("best_five_factor", 0.1850)
    '✓'
    """
    validator = CrossValidator()
    report = validator.validate_cagr(strategy_key, actual_cagr)
    return report.confidence
