"""
PIT（Point-In-Time）原则实现

【白话说明】
这是量化回测中最容易出错的地方，也是最关键的地方。

【核心问题】
假设今天是2024年3月31日，茅台2023年年报要到2024年4月25日才披露。
如果我直接在3月31日用2023年年报数据来选股 → 这是"未来函数"（作弊）
正确的做法：3月31日只能用2023年三季报数据（因为三季报在2023年10月就披露了）

【PIT原则】
在任何调仓日期，只能使用该日期之前已经披露（disclosure_date ≤ 调仓日期）的财务数据。

【披露时间规则（中国A股）】
| 报告期 | 法定披露截止日 | 典型披露时间 |
|--------|---------------|-------------|
| 一季报 (0331) | 4月30日 | 4月中下旬 |
| 中报   (0630) | 8月31日 | 8月中下旬 |
| 三季报 (0930) | 10月31日 | 10月中下旬 |
| 年报   (1231) | 次年4月30日 | 次年3-4月 |

【实现策略】
理想情况：从数据源获取每份财报的"实际披露日期"
降级方案：使用法定截止日作为估算披露日期
  好处：保守估计（永远不会在未来日期使用财报数据）
  坏处：可能比实际可用日期晚1-2个月（少用了一些本可用的数据）
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


# =====================================================================
# 财报报告期 → 法定披露截止日 映射
# =====================================================================

def get_disclosure_deadline(report_date: str) -> str:
    """
    根据报告期返回法定披露截止日
    
    【保守策略】使用法定截止日作为"可用日期"。
    例如：2023年年报的报告期是20231231，披露截止日是20240430。
    只有到了2024年4月30日之后，这份年报数据才被允许使用。
    
    Args:
        report_date: 报告期，格式 'YYYYMMDD'，如 '20231231'
    
    Returns:
        披露截止日，格式 'YYYYMMDD'
    """
    year = int(report_date[:4])
    month_day = report_date[4:]
    
    if month_day == '0331':   # 一季报
        return f"{year}0430"
    elif month_day == '0630': # 中报
        return f"{year}0831"
    elif month_day == '0930': # 三季报
        return f"{year}1031"
    elif month_day == '1231': # 年报
        return f"{year + 1}0430"
    else:
        # 未知报告期，保守估计：报告期+4个月
        dt = datetime.strptime(report_date, '%Y%m%d')
        dt = dt + timedelta(days=120)
        return dt.strftime('%Y%m%d')


# =====================================================================
# PIT财务数据筛选器
# =====================================================================

def get_available_financials(
    financial_df: pd.DataFrame,
    as_of_date: str,
    use_actual_disclosure: bool = True
) -> pd.DataFrame:
    """
    【PIT核心方法】
    从财务数据DataFrame中，筛选出在指定日期之前已披露的记录。
    
    Args:
        financial_df: 包含所有财务数据的DataFrame
            - 必须包含字段: code, report_date, disclosure_date
        as_of_date: 调仓日期，格式 'YYYYMMDD'
        use_actual_disclosure: 
            True: 使用实际披露日期（如果有）
            False: 使用法定截止日
    
    Returns:
        在 as_of_date 当天可以合法使用的财务数据
    """
    if financial_df is None or len(financial_df) == 0:
        return pd.DataFrame()
    
    df = financial_df.copy()
    
    # ---- 步骤1：确定每条记录的可使用日期 ----
    if use_actual_disclosure and 'disclosure_date' in df.columns:
        # 有实际披露日期 → 使用实际披露日期
        df['_available_date'] = df['disclosure_date'].fillna(
            df['report_date'].apply(get_disclosure_deadline)
        )
    else:
        # 没有实际披露日期 → 使用法定截止日（保守估计）
        df['_available_date'] = df['report_date'].apply(get_disclosure_deadline)
    
    # ---- 步骤2：只保留在 as_of_date 之前可用的 ----
    available = df[df['_available_date'] <= as_of_date].copy()
    
    # ---- 步骤3：每只股票取最新可用的财报 ----
    # 同一只股票可能有多份已披露的财报，取最新的一份
    if len(available) > 0 and 'code' in available.columns:
        available = available.sort_values('report_date', ascending=False)
        available = available.drop_duplicates(subset=['code'], keep='first')
    
    # ---- 步骤4：清理临时字段 ----
    available = available.drop(columns=['_available_date'], errors='ignore')
    
    return available


def get_latest_available_report_date(
    financial_df: pd.DataFrame,
    as_of_date: str
) -> Optional[str]:
    """
    获取在指定日期前，最新可用的财报报告期
    
    【用途】批量获取财务数据时，知道应该用哪个报告期的数据
    
    Returns:
        报告期字符串，如 '20231231'；如果没有则返回 None
    """
    available = get_available_financials(financial_df, as_of_date)
    
    if len(available) == 0:
        return None
    
    return available['report_date'].max()


# =====================================================================
# 调仓日 → 可用财报报告期 映射表
# =====================================================================

def build_pit_mapping(
    trade_dates: List[str],
    report_dates: List[str]
) -> pd.DataFrame:
    """
    构建"每个交易日 → 可用财报报告期"的映射表
    
    【用途】
    回测时，每个月调仓日需要知道"这个月应该用哪个季度的财报"。
    这个映射表预计算好，避免每次都重复筛选。
    
    Args:
        trade_dates: 所有交易日期列表，如 ['20200301', '20200302', ...]
        report_dates: 所有财报报告期列表，如 ['20191231', '20200331', ...]
    
    Returns:
        DataFrame:
        - trade_date: 交易日
        - available_report_date: 该日可用的最新财报报告期
    """
    # 将报告期转为"可用日期"（法定截止日）
    report_availability = []
    for rd in report_dates:
        deadline = get_disclosure_deadline(rd)
        report_availability.append({
            'report_date': rd,
            'available_from': deadline
        })
    
    report_df = pd.DataFrame(report_availability)
    report_df = report_df.sort_values('available_from')
    
    # 为每个交易日找出最新可用的报告期
    mappings = []
    for td in trade_dates:
        # 找到所有 available_from <= td 的报告期
        available = report_df[report_df['available_from'] <= td]
        if len(available) > 0:
            latest = available.iloc[-1]['report_date']
        else:
            latest = None
        mappings.append({
            'trade_date': td,
            'available_report_date': latest
        })
    
    return pd.DataFrame(mappings)


# =====================================================================
# PIT自检：检测未来函数
# =====================================================================

def check_lookahead_bias(
    strategy_signals: pd.DataFrame,
    financial_used: pd.DataFrame
) -> Dict[str, any]:
    """
    【防幻觉自检】检测策略信号是否使用了未来数据
    
    【白话】如果策略在3月31日用到了4月25日才披露的年报数据，
    这就是"未来函数"（look-ahead bias），检测出来就报错。
    
    Args:
        strategy_signals: 策略信号，包含 trade_date 和 code
        financial_used: 策略实际使用的财务数据
    
    Returns:
        {
            'has_bias': True/False,
            'violations': 违规记录列表
        }
    """
    violations = []
    
    if len(strategy_signals) == 0 or len(financial_used) == 0:
        return {'has_bias': False, 'violations': []}
    
    # 合并信号和使用的财务数据
    merged = strategy_signals.merge(
        financial_used[['code', 'report_date', 'disclosure_date']],
        on='code',
        how='left'
    )
    
    # 检查：是否存在 trade_date < disclosure_date 的情况
    if 'disclosure_date' in merged.columns:
        bias_mask = merged['trade_date'] < merged['disclosure_date']
        n_bias = bias_mask.sum()
        
        if n_bias > 0:
            bias_examples = merged[bias_mask][['trade_date', 'code', 'report_date', 'disclosure_date']].head(5)
            violations = bias_examples.to_dict('records')
    
    return {
        'has_bias': len(violations) > 0,
        'violation_count': len(violations),
        'violations': violations
    }


# =====================================================================
# 测试/验证用
# =====================================================================

if __name__ == '__main__':
    # 快速自测
    print("PIT模块自测")
    print(f"2023年年报(20231231)的法定披露截止日: {get_disclosure_deadline('20231231')}")
    print(f"2024年一季报(20240331)的法定披露截止日: {get_disclosure_deadline('20240331')}")
    print(f"2024年中报(20240630)的法定披露截止日: {get_disclosure_deadline('20240630')}")
    print(f"2024年三季报(20240930)的法定披露截止日: {get_disclosure_deadline('20240930')}")
    
    # 预期输出:
    # 2023年年报 → 20240430
    # 2024年一季报 → 20240430
    # 2024年中报 → 20240831
    # 2024年三季报 → 20241031
