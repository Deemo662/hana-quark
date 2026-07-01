"""
因子方向校验器（第3重防线）

【白话说明】
每个因子算完之后，要验证"这个因子的效果方向是否和董鹏飞书里说的一样"。
比如书里说"低PE的股票长期表现更好"，那我们把股票按PE从低到高分成10组，
看看收益是不是真的从高到低递减。

【校验逻辑】
1. 把股票按因子值排序，分成N组（默认10组）
2. 计算每组在未来一段时间（默认1个月）的平均收益率
3. 检查收益率是否按预期方向排列：
   - higher_better: 因子值越高 → 收益率越高
   - lower_better: 因子值越低 → 收益率越高
4. 输出校验报告：✓（通过）/ △（存疑）/ ✗（异常）
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FactorValidationReport:
    """单个因子的校验报告"""
    factor_name: str = ""
    factor_display_name: str = ""
    book_chapter: str = ""
    book_conclusion: str = ""
    expected_direction: str = ""
    book_best_return: float = 0.0
    book_worst_return: float = 0.0
    
    # 实测结果
    n_stocks: int = 0              # 参与校验的股票数
    n_groups: int = 10             # 分组数
    group_returns: List[float] = field(default_factory=list)  # 每组的平均收益
    group_counts: List[int] = field(default_factory=list)     # 每组的股票数
    actual_best_return: float = 0.0    # 实测最优组收益
    actual_worst_return: float = 0.0   # 实测最差组收益
    actual_spread: float = 0.0         # 实测最优-最差差值
    
    # 判定
    direction_match: bool = True        # 方向是否与书本一致
    monotonic: bool = True              # 是否单调（组间收益率不来回波动）
    confidence: str = "pending"         # ✓确认 / △存疑 / ✗异常 / ?未验证
    notes: List[str] = field(default_factory=list)
    
    def report(self) -> str:
        """人类可读的校验报告"""
        icon = {"✓": "✓", "△": "△", "✗": "✗", "?": "?"}.get(self.confidence, "?")
        
        lines = [
            f"\n{'─'*50}",
            f"  {icon} {self.factor_display_name} ({self.factor_name})",
            f"  书本章节: {self.book_chapter}",
            f"  书本结论: {self.book_conclusion}",
            f"  期望方向: {self.expected_direction}",
            f"  书本最优/最差: {self.book_best_return:.1%} / {self.book_worst_return:.1%}",
            f"  实测股票数: {self.n_stocks}",
            f"  实测最优/最差: {self.actual_best_return:.1%} / {self.actual_worst_return:.1%}",
            f"  实测差值: {self.actual_spread:.1%}",
        ]
        
        # 分组详情
        if self.group_returns:
            lines.append(f"  分组收益: {[f'{r:.1%}' for r in self.group_returns]}")
        
        # 判定
        if self.direction_match:
            lines.append(f"  方向判定: ✓ 与书本一致")
        else:
            lines.append(f"  方向判定: ✗ 与书本相反！需要检查计算逻辑")
        
        if self.notes:
            for note in self.notes:
                lines.append(f"  ℹ {note}")
        
        return "\n".join(lines)


class FactorValidator:
    """
    因子方向校验器
    
    检查每个因子的分位数收益率是否与书本结论一致。
    
    【使用前提】需要有历史收益率数据（需要至少1年的K线数据）
    """
    
    def __init__(self, n_groups: int = 10, forward_period_days: int = 21):
        """
        Args:
            n_groups: 分组数（默认10组=十分位）
            forward_period_days: 前向收益率天数（默认21≈1个月）
        """
        self.n_groups = n_groups
        self.forward_period_days = forward_period_days
    
    def validate_factor(
        self,
        factor_name: str,
        factor_values: pd.Series,       # index=code, values=因子值
        forward_returns: pd.Series,     # index=code, values=未来N日收益率
        factor_cls=None,                # 因子类（用于读取元数据）
    ) -> FactorValidationReport:
        """
        校验单个因子
        
        Args:
            factor_name: 因子注册名，如 'value_pe_ttm'
            factor_values: 因子值（已去极值、标准化后）
            forward_returns: 前向收益率（如未来21日收益率）
            factor_cls: 因子类引用（可选，用于读元数据）
        
        Returns:
            FactorValidationReport
        """
        report = FactorValidationReport()
        report.factor_name = factor_name
        
        # ---- 步骤1：读取书本元数据 ----
        if factor_cls is not None:
            inst = factor_cls() if callable(factor_cls) else factor_cls
            report.factor_display_name = getattr(inst, 'name', factor_name)
            report.book_chapter = getattr(inst, 'book_chapter', '')
            report.book_conclusion = getattr(inst, 'book_conclusion', '')
            report.expected_direction = getattr(inst, 'direction', '')
            report.book_best_return = getattr(inst, 'book_best_quintile_return', 0.0)
            report.book_worst_return = getattr(inst, 'book_worst_quintile_return', 0.0)
        
        # ---- 步骤2：数据对齐 ----
        # 只保留同时有因子值和收益率的股票
        common_codes = factor_values.dropna().index.intersection(forward_returns.dropna().index)
        
        if len(common_codes) < self.n_groups * 3:
            report.confidence = "?"
            report.notes.append(f"数据不足：仅{len(common_codes)}只有效股票，至少需要{self.n_groups * 3}只")
            return report
        
        fv = factor_values.loc[common_codes]
        fr = forward_returns.loc[common_codes]
        report.n_stocks = len(common_codes)
        
        # ---- 步骤3：分组 ----
        # 根据因子方向决定分组排序
        if report.expected_direction == 'lower_better':
            # 越低越好 → 升序排列（第1组=因子值最小的=应该收益最好）
            ascending = True
        elif report.expected_direction == 'higher_better':
            # 越高越好 → 降序排列（第1组=因子值最大的=应该收益最好）
            ascending = False
        else:
            # middle_better 或未知 → 升序排列
            ascending = True
            report.notes.append("方向为middle_better或未知，默认升序")
        
        sorted_fv = fv.sort_values(ascending=ascending)
        sorted_fr = fr.loc[sorted_fv.index]
        
        # 等分分组
        group_size = len(sorted_fv) // self.n_groups
        group_returns = []
        group_counts = []
        
        for g in range(self.n_groups):
            start = g * group_size
            end = start + group_size if g < self.n_groups - 1 else len(sorted_fv)
            group_fr = sorted_fr.iloc[start:end]
            group_returns.append(group_fr.mean())
            group_counts.append(len(group_fr))
        
        report.group_returns = group_returns
        report.group_counts = group_counts
        report.actual_best_return = group_returns[0]    # 最优组
        report.actual_worst_return = group_returns[-1]  # 最差组
        report.actual_spread = report.actual_best_return - report.actual_worst_return
        
        # ---- 步骤4：方向判定 ----
        # 检查最优组是否真的优于最差组
        if report.expected_direction in ('higher_better', 'lower_better'):
            if report.actual_best_return > report.actual_worst_return:
                report.direction_match = True
            else:
                report.direction_match = False
                report.notes.append(f"最优组({report.actual_best_return:.1%})反而不如最差组({report.actual_worst_return:.1%})")
        
        # ---- 步骤5：单调性检查 ----
        # 检查组间收益率是否单调（允许少量波动）
        diffs = np.diff(group_returns)
        n_reversals = (diffs < 0).sum()  # 反转次数
        if n_reversals > self.n_groups * 0.3:  # 超过30%的组反转
            report.monotonic = False
            report.notes.append(f"非单调：{n_reversals}/{self.n_groups-1}个反转")
        
        # ---- 步骤6：综合置信度 ----
        if not report.direction_match:
            report.confidence = "✗"
        elif report.actual_spread <= 0:
            report.confidence = "✗"
            report.notes.append("最优最差差值≤0")
        elif n_reversals > 2:
            report.confidence = "△"
            report.notes.append("存在方向反转，可能是噪声")
        else:
            report.confidence = "✓"
        
        return report
    
    def validate_all_factors(
        self,
        factor_values: Dict[str, pd.Series],
        forward_returns: pd.Series,
        registry: Dict,
    ) -> List[FactorValidationReport]:
        """
        批量校验所有因子
        
        Args:
            factor_values: {factor_name: values_series}
            forward_returns: 前向收益率
            registry: 因子注册表 FACTOR_REGISTRY
        
        Returns:
            校验报告列表
        """
        reports = []
        
        for fname, fv in factor_values.items():
            cls = registry.get(fname)
            report = self.validate_factor(fname, fv, forward_returns, cls)
            reports.append(report)
        
        # 汇总
        passed = sum(1 for r in reports if r.confidence == "✓")
        suspicious = sum(1 for r in reports if r.confidence == "△")
        failed = sum(1 for r in reports if r.confidence == "✗")
        unknown = sum(1 for r in reports if r.confidence == "?")
        
        logger.info(f"\n因子校验汇总: ✓{passed} △{suspicious} ✗{failed} ?{unknown} (共{len(reports)}个)")
        
        return reports
