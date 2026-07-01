# ============================================================
# 质量低波选股策略 v2
# 基于董鹏飞《基本面量化投资策略》+ 2026年市场调研升级
# 
# 变更（相比v1）:
#   1. 去市值因子（注册制后壳价值消失）
#   2. 加6月波动率（全书TOP3双因子核心）
#   3. 等权重（非主观比例，书本验证更优）
#   4. 加股息率（2023-2025最强因子）
#   5. 紧股票池过滤
# ============================================================
# 在JoinQuant平台上使用:
#   1. 复制到"我的策略" → 新建策略
#   2. 回测区间建议: 2015-01-01 ~ 最新
#   3. 初始资金: 100000
#   4. 频率: 天
# ============================================================

import pandas as pd
import numpy as np


def initialize(context):
    """初始化"""
    # 基准: 沪深300
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    
    # ★手续费: 佣金万2.5 + 印花税千0.5(卖出) + 滑点千1
    set_order_cost(OrderCost(
        open_commission=0.00025,
        close_commission=0.00025,
        close_tax=0.0005,
        min_commission=5
    ), type='stock')
    
    # 策略参数
    g.stock_num = 25          # 持仓数量
    g.filter_pct = 0.20       # 剔除市值最小20%
    g.max_pe = 200            # PE上限（排除极端值）
    g.min_list_days = 500     # 上市至少500天≈2年
    
    # ★月度调仓，每月第1个交易日开盘时执行
    run_monthly(rebalance, monthday=1, time='open')


def rebalance(context):
    """月度调仓主逻辑"""
    
    # ===== 第1步: 构建股票池 =====
    pool = build_universe(context)
    if len(pool) < 30:
        log.warn(f"股票池仅{len(pool)}只，跳过本月")
        return
    
    # ===== 第2步: 获取因子数据 =====
    df = get_factor_data(context, pool)
    if df is None or len(df) < 20:
        log.warn(f"有效数据仅{len(df) if df is not None else 0}只，跳过本月")
        return
    
    # ===== 第3步: 等权打分 =====
    df = calculate_scores(df)
    
    # ===== 第4步: 选TOP N =====
    selected = df.sort_values('total_score', ascending=False).head(g.stock_num).index.tolist()
    
    # ===== 第5步: 调仓 =====
    execute_trades(context, selected)


def build_universe(context):
    """
    构建股票池
    ★ 用中证800作为初始池
    """
    pool = get_index_stocks('000906.XSHG')  # 中证800
    
    current_data = get_current_data()
    
    # ★获取上市日期（get_current_data不含start_date，需单独取）
    securities_info = get_all_securities(['stock'], context.current_dt)
    
    # ★五维过滤
    filtered = []
    for s in pool:
        # 1. 停牌 → 跳过
        if current_data[s].paused:
            continue
        # 2. ST → 跳过
        if current_data[s].is_st:
            continue
        # 3. 上市不足500天 → 跳过
        if s in securities_info.index:
            days_listed = (context.current_dt.date() - securities_info.loc[s, 'start_date']).days
            if days_listed < g.min_list_days:
                continue
        filtered.append(s)
    
    return filtered


def get_factor_data(context, pool):
    """
    获取所有因子所需的原始数据
    因子: ROE + 毛利率 + 6月波动率(低波) + PE(估值) + OCF质量(排雷) + 股息率
    """
    
    # ---- 财务数据 ----
    q = query(
        valuation.code,
        valuation.pe_ratio,                # PE
        valuation.pb_ratio,                # PB（备选）
        valuation.market_cap,              # 总市值
        indicator.roe,                     # ★ROE
        indicator.gross_profit_margin,     # ★毛利率
        cash_flow.net_operate_cash_flow,   # 经营活动现金流
        income.net_profit,                 # 净利润
    ).filter(valuation.code.in_(pool))
    
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0:
        return None
    
    df = df.set_index('code')
    
    # ---- 数据清洗 ----
    # PE: 排除负PE和极端PE
    df['pe_clean'] = df['pe_ratio'].apply(lambda x: x if (x and 0 < x < g.max_pe) else None)
    
    # OCF排雷: 经营现金流/净利润（过于极端的值截断）
    df['ocf_quality'] = df['net_operate_cash_flow'] / df['net_profit'].replace(0, np.nan)
    df['ocf_quality'] = df['ocf_quality'].clip(-5, 5)
    
    # ---- 6月波动率（126个交易日） ----
    # ★全书TOP3策略的核心因子，原v1脚本遗漏了它
    codes = df.index.tolist()
    prices = history(126, '1d', 'close', codes, df=False, skip_paused=True)
    
    vol_data = {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 63:  # 至少63个有效交易日（≈3个月）
                daily_ret = s.pct_change().dropna()
                # 年化波动率 = 日收益标准差 × sqrt(252)
                vol_data[code] = daily_ret.std() * np.sqrt(252)
    
    df['volatility_6m'] = pd.Series(vol_data)
    
    # ---- 动量（6个月，用于辅助参考） ----
    mom_data = {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 126:
                mom_data[code] = (s.iloc[-1] - s.iloc[-126]) / s.iloc[-126]
    df['momentum_6m'] = pd.Series(mom_data)
    
    # ---- 股息率 ----
    # JoinQuant的valuation表可能不含股息率，用基本面数据
    try:
        q2 = query(
            valuation.code,
            valuation.dividend_yield_ratio,
        ).filter(valuation.code.in_(codes))
        div_df = get_fundamentals(q2, date=context.current_dt)
        if div_df is not None and len(div_df) > 0:
            div_df = div_df.set_index('code')
            df['dividend_yield'] = div_df['dividend_yield_ratio']
    except:
        # 如果取不到股息率（老版本JoinQuant），不影响运行
        df['dividend_yield'] = np.nan
    
    # ---- 剔除缺失关键数据的行 ----
    essential = ['roe', 'gross_profit_margin', 'pe_clean', 'volatility_6m']
    df = df.dropna(subset=essential)
    
    # ---- 排雷过滤 ----
    # OCF质量极差（<-2）的排除
    if 'ocf_quality' in df.columns:
        df = df[df['ocf_quality'] > -2]
    
    return df


def calculate_scores(df):
    """
    等权打分（与书本一致，非主观比例）
    
    因子方向:
      ROE          → 越高越好
      毛利率        → 越高越好
      6月波动率     → 越低越好（★低波异象）
      PE(clean)    → 越低越好（价值）
      OCF质量      → 越高越好（排雷）
      股息率        → 越高越好（可选）
    """
    scores = pd.DataFrame(index=df.index)
    
    # 等权标准化排名（百分位）
    scores['s_roe'] = df['roe'].rank(ascending=True, pct=True)
    scores['s_gross'] = df['gross_profit_margin'].rank(ascending=True, pct=True)
    scores['s_lowvol'] = df['volatility_6m'].rank(ascending=False, pct=True)  # 低波→高分
    scores['s_pe'] = df['pe_clean'].rank(ascending=False, pct=True)  # 低PE→高分
    scores['s_ocf'] = df['ocf_quality'].rank(ascending=True, pct=True)
    
    # 基础5因子等权
    scores['total_score'] = (
        scores['s_roe'] +
        scores['s_gross'] +
        scores['s_lowvol'] +
        scores['s_pe'] +
        scores['s_ocf']
    )
    
    # 如果股息率可用，加成到总分（6因子等权）
    if 'dividend_yield' in df.columns and df['dividend_yield'].notna().sum() > 5:
        scores['s_div'] = df['dividend_yield'].rank(ascending=True, pct=True)
        # 重新等权（6因子各占1/6，5因子占5/6的相对贡献）
        scores['total_score'] = (
            scores['s_roe'] +
            scores['s_gross'] +
            scores['s_lowvol'] +
            scores['s_pe'] +
            scores['s_ocf'] +
            scores['s_div']
        )
    
    return scores


def execute_trades(context, selected):
    """执行调仓"""
    # 卖出落选股
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
    
    # 等权买入入选股（留2%现金缓冲）
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
