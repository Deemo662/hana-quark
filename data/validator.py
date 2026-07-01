"""
数据合理性校验器（第2重防线）

【白话说明】
从网上拉下来的数据不一定干净——可能有错误价格、异常PE值、NaN等问题。
这个文件定义了"什么数据算合理、什么算异常"的硬性规则。

【校验分为三级】
✓ 通过（PASS）：数据在合理范围内，正常使用
⚠ 警告（WARN）：数据异常但可能合理（如某些股票PE确实很高），标记但不丢弃
✗ 拒绝（REJECT）：数据明确错误（如收盘价<0），直接丢弃不参与计算

【设计原则】
规则来源于A股市场常识和统计数据。宁可错杀不可漏过——异常数据对回测的破坏
远大于少几只股票。
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """单次校验的结果"""
    total: int = 0          # 总检查项数
    passed: int = 0         # 通过数
    warnings: int = 0       # 警告数
    rejected: int = 0       # 拒绝数
    details: List[str] = field(default_factory=list)  # 详细说明

    def merge(self, other: 'ValidationResult'):
        self.total += other.total
        self.passed += other.passed
        self.warnings += other.warnings
        self.rejected += other.rejected
        self.details.extend(other.details)

    def report(self) -> str:
        """输出人类可读的校验报告"""
        lines = [
            "=" * 60,
            "  数据质量校验报告",
            "=" * 60,
            f"  总计检查: {self.total} 项",
            f"  ✓ 通过:   {self.passed} 项",
            f"  ⚠ 警告:   {self.warnings} 项",
            f"  ✗ 拒绝:   {self.rejected} 项",
            "=" * 60,
        ]
        if self.details:
            lines.append("\n  详细信息:")
            for d in self.details[:20]:  # 最多显示20条
                lines.append(f"    {d}")
            if len(self.details) > 20:
                lines.append(f"    ... 还有 {len(self.details) - 20} 条")
        return "\n".join(lines)


# =====================================================================
# 行情数据校验规则（硬编码）
# =====================================================================

def validate_kline(df: pd.DataFrame) -> ValidationResult:
    """
    校验日K线数据
    
    【检查项】
    1. 收盘价必须在合理范围（0.01 ~ 100000）
    2. 最高价 ≥ 最低价（铁律）
    3. 最高价 ≥ 收盘价 ≥ 最低价（K线基本规则）
    4. 成交量 ≥ 0
    5. 不出现NaN收盘价
    """
    result = ValidationResult()
    
    if df is None or len(df) == 0:
        result.details.append("数据为空，跳过校验")
        return result
    
    n = len(df)
    
    # ---- 检查1：收盘价范围 ----
    close = df.get('close', pd.Series(dtype=float))
    invalid_close = (close <= 0.01) | (close > 100000) | close.isna()
    n_invalid = invalid_close.sum()
    result.total += n
    if n_invalid > 0:
        bad_codes = df.loc[invalid_close, 'code'].unique() if 'code' in df.columns else []
        result.rejected += n_invalid
        result.details.append(f"✗ {n_invalid}条收盘价异常（<0.01或>100000或NaN），涉及{bad_codes[:5]}...")
    else:
        result.passed += n
    
    # ---- 检查2：最高价 ≥ 最低价 ----
    if 'high' in df.columns and 'low' in df.columns:
        bad_hl = df['high'] < df['low']
        n_bad_hl = bad_hl.sum()
        result.total += 1
        if n_bad_hl > 0:
            result.rejected += 1
            result.details.append(f"✗ {n_bad_hl}条 high < low（严重错误）")
        else:
            result.passed += 1
    
    # ---- 检查3：K线价格关系 ----
    # 收盘价应在最高最低之间（±1%容差，处理四舍五入）
    if all(c in df.columns for c in ['high', 'low', 'close']):
        bad_range = (df['close'] > df['high'] * 1.01) | (df['close'] < df['low'] * 0.99)
        n_bad_range = bad_range.sum()
        result.total += 1
        if n_bad_range > 0:
            result.warnings += 1
            result.details.append(f"⚠ {n_bad_range}条收盘价超出高低价范围（可能是复权计算差异）")
        else:
            result.passed += 1
    
    # ---- 检查4：成交量 ----
    if 'volume' in df.columns:
        bad_vol = df['volume'] < 0
        n_bad_vol = bad_vol.sum()
        result.total += 1
        if n_bad_vol > 0:
            result.rejected += 1
            result.details.append(f"✗ {n_bad_vol}条成交量为负数")
        else:
            result.passed += 1
        
        # 停牌标记（成交量为0）
        n_suspend = (df['volume'] == 0).sum()
        if n_suspend > 0:
            result.details.append(f"  ℹ {n_suspend}条成交量为0（停牌），不影响数据质量")
    
    # ---- 检查5：NaN检查 ----
    nan_close = df['close'].isna().sum() if 'close' in df.columns else 0
    result.total += 1
    if nan_close > 0:
        result.rejected += 1
        result.details.append(f"✗ {nan_close}条收盘价为NaN（严重错误）")
    else:
        result.passed += 1
    
    return result


# =====================================================================
# 财务数据校验规则（硬编码）
# =====================================================================

def validate_financial(df: pd.DataFrame) -> ValidationResult:
    """
    校验财务数据
    
    【检查项】
    1. PE_TTM 在 -10000 ~ 10000（A股极端值范围）
    2. PB 在 0.01 ~ 100
    3. ROE 在 -1.0 ~ 1.0（即 -100% ~ 100%）
    4. 毛利率 在 -0.5 ~ 1.0（允许少量负毛利企业）
    5. 总资产 > 总负债（资不抵债警告）
    """
    result = ValidationResult()
    
    if df is None or len(df) == 0:
        result.details.append("数据为空，跳过校验")
        return result
    
    n = len(df)
    
    # 以下每个检查项独立统计
    
    # ---- PE_TTM ----
    if 'pe_ttm' in df.columns:
        pe = df['pe_ttm']
        # PE合理范围：-10000到10000
        # 超过这个范围的视为数据错误
        bad_pe = (pe < -10000) | (pe > 10000)
        n_bad = bad_pe.sum()
        result.total += n
        if n_bad > 0:
            result.rejected += n_bad
            result.details.append(f"✗ {n_bad}条PE异常（<-10000或>10000）")
        else:
            result.passed += n
        
        # PE负值单独统计（不是错误，是策略需要剔除的）
        n_neg_pe = (pe < 0).sum()
        if n_neg_pe > 0:
            result.details.append(f"  ℹ {n_neg_pe}条PE为负（策略将排除，但数据本身正确）")
    else:
        result.details.append("  ⚠ 缺少PE_TTM字段")
    
    # ---- PB ----
    if 'pb' in df.columns:
        pb = df['pb']
        bad_pb = (pb < 0.01) | (pb > 100)
        n_bad = bad_pb.sum()
        result.total += n
        if n_bad > 0:
            result.rejected += n_bad
            result.details.append(f"✗ {n_bad}条PB异常（<0.01或>100）")
        else:
            result.passed += n
    
    # ---- ROE ----
    if 'roe' in df.columns:
        roe = df['roe']
        # AkShare返回的ROE通常是百分比数值（如15表示15%）
        # 也可能是小数形式（如0.15表示15%），需要根据实际数据判断
        # 这里用宽泛的范围：-200 ~ 200
        bad_roe = (roe < -200) | (roe > 200)
        n_bad = bad_roe.sum()
        result.total += n
        if n_bad > 0:
            result.rejected += n_bad
            result.details.append(f"✗ {n_bad}条ROE异常")
        else:
            result.passed += n
    
    # ---- 毛利率 ----
    if 'gross_margin' in df.columns:
        gm = df['gross_margin']
        # 毛利率合理范围：-50% ~ 100%（有些企业确实亏本卖）
        # AkShare返回值可能是 0~100（百分比） 或 0~1（小数）
        bad_gm = (gm < -50) | (gm > 100)
        n_bad = bad_gm.sum()
        result.total += n
        if n_bad > 0:
            result.rejected += n_bad
            result.details.append(f"✗ {n_bad}条毛利率异常")
        else:
            result.passed += n
    
    # ---- 资产负债率 ----
    if 'asset_liability_ratio' in df.columns:
        alr = df['asset_liability_ratio']
        # 资不抵债（>100%）不是数据错误，但值得标记
        bad_alr = (alr > 100) | (alr < 0)
        n_bad = bad_alr.sum()
        if n_bad > 0:
            result.warnings += n_bad
            result.details.append(f"⚠ {n_bad}条资产负债率异常（<0或>100%）")
    
    # ---- 市值 ----
    if 'total_market_cap' in df.columns:
        mcap = df['total_market_cap']
        bad_mcap = (mcap <= 0) | (mcap > 1e13)  # 市值不超过10万亿
        n_bad = bad_mcap.sum()
        result.total += n
        if n_bad > 0:
            result.rejected += n_bad
            result.details.append(f"✗ {n_bad}条市值异常")
        else:
            result.passed += n
    
    return result


# =====================================================================
# 综合校验入口
# =====================================================================

def validate_data(df: pd.DataFrame, data_type: str = 'kline') -> ValidationResult:
    """
    统一校验入口
    
    Args:
        df: 待校验的DataFrame
        data_type: 'kline' | 'financial'
    
    Returns:
        ValidationResult 包含通过/警告/拒绝统计和详情
    """
    if data_type == 'kline':
        return validate_kline(df)
    elif data_type == 'financial':
        return validate_financial(df)
    else:
        result = ValidationResult()
        result.details.append(f"未知数据类型: {data_type}")
        return result
