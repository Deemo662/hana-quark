# ============================================================
# 红利低波策略
# 2023-2025年A股表现最强的因子组合
#
# 逻辑: 高股息=确定性溢价 + 低波动=抗跌
# 中证红利低波指数(000922) 2023年+12%, 2024年+18%
# 同期沪深300 2023年-11%
#
# 仅2个因子，极简但有效
# 适合熊市/震荡市防御配置
# ============================================================

import pandas as pd
import numpy as np


def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_commission=0.00025, close_commission=0.00025,
        close_tax=0.0005, min_commission=5
    ), type='stock')
    
    g.stock_num = 30          # 红利策略适合多持几只分散
    g.vol_window = 126        # 波动率计算窗口（6个月）
    
    # ★季度调仓（红利策略换手低，季度够用）
    run_monthly(rebalance, monthday=1, time='open')


def rebalance(context):
    # 股票池: 中证800
    pool = get_index_stocks('000906.XSHG')
    current_data = get_current_data()
    securities_info = get_all_securities(['stock'], context.current_dt)
    pool = [s for s in pool 
            if not current_data[s].paused 
            and not current_data[s].is_st
            and (context.current_dt.date() - securities_info.loc[s, 'start_date']).days > 500]
    if len(pool) < 30: return
    
    # ---- 股息率 ----
    q = query(
        valuation.code,
        valuation.pe_ratio,
    ).filter(valuation.code.in_(pool))
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return
    df = df.set_index('code')
    
    # ★股息率（如果JoinQuant支持）
    try:
        q2 = query(valuation.code, valuation.dividend_yield_ratio
                  ).filter(valuation.code.in_(df.index.tolist()))
        div_df = get_fundamentals(q2, date=context.current_dt)
        if div_df is not None and len(div_df) > 0:
            div_df = div_df.set_index('code')
            df['dividend_yield'] = div_df['dividend_yield_ratio']
        else:
            log.warn("股息率数据不可用，跳过本月")
            return
    except:
        log.warn("股息率查询失败，跳过本月")
        return
    
    # ---- 6月波动率 ----
    codes = df.index.tolist()
    prices = history(g.vol_window, '1d', 'close', codes, df=False, skip_paused=True)
    vol_data = {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 63:
                rets = s.pct_change().dropna()
                vol_data[code] = rets.std() * np.sqrt(252)
    df['volatility'] = pd.Series(vol_data)
    
    # ---- 过滤 ----
    df = df.dropna(subset=['dividend_yield', 'volatility'])
    df = df[df['dividend_yield'] > 0]  # 至少要有分红
    if len(df) < 20: return
    
    # ★排除PE为负的
    if 'pe_ratio' in df.columns:
        df = df[(df['pe_ratio'] > 0) & (df['pe_ratio'] < 200)]
    
    # ---- 打分: 股息率越高越好 + 波动率越低越好 ----
    scores = pd.DataFrame(index=df.index)
    scores['s_div'] = df['dividend_yield'].rank(ascending=True, pct=True)
    scores['s_lowvol'] = df['volatility'].rank(ascending=False, pct=True)
    scores['total'] = scores['s_div'] + scores['s_lowvol']
    
    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()
    
    # ---- 调仓 ----
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
