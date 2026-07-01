# ============================================================
# 质量低波 v3（中证800池 + 择时 + ROIC）
# 全A股池有代码格式兼容问题，改用中证800保持稳定
# ============================================================
import pandas as pd
import numpy as np

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_commission=0.00025, close_commission=0.00025,
                             close_tax=0.0005, min_commission=5), type='stock')
    g.stock_num = 25; g.max_pe = 200; g.min_list_days = 500
    g.ma_period = 200; g.cash_buffer = 0.02
    g.debug = True
    run_monthly(rebalance, monthday=1, time='open')

def rebalance(context):
    # ===== 择时 =====
    hs300 = history(g.ma_period, '1d', 'close', ['000300.XSHG'], df=False, skip_paused=True)
    if '000300.XSHG' in hs300 and len(hs300['000300.XSHG']) > 0:
        ma200 = pd.Series(hs300['000300.XSHG']).mean()
        current = hs300['000300.XSHG'][-1]
        if g.debug and context.current_dt.month == 1:
            log.info(f"择时: {current:.0f} vs MA200 {ma200:.0f} ({'空仓' if current < ma200 else '持仓'})")
        if current < ma200:
            for code in list(context.portfolio.positions.keys()):
                order_target_value(code, 0)
            return
    
    # ===== 股票池 =====
    pool = get_index_stocks('000906.XSHG')  # 中证800
    current_data = get_current_data()
    sec_info = get_all_securities(['stock'], context.current_dt)
    pool = [s for s in pool
            if not current_data[s].paused
            and not current_data[s].is_st
            and (s in sec_info.index and 
                 (context.current_dt.date() - sec_info.loc[s, 'start_date']).days > g.min_list_days)]
    
    if g.debug: log.info(f"股票池: {len(pool)}只")
    if len(pool) < 30: return
    
    # ===== 因子 =====
    df = get_factor_data(context, pool)
    if df is None or len(df) < 20:
        if g.debug: log.warn(f"因子数据不足: {len(df) if df is not None else 0}条")
        return
    if g.debug: log.info(f"有效因子: {len(df)}只")
    
    # ===== 打分 =====
    df = calculate_scores(df)
    selected = df.sort_values('total_score', ascending=False).head(g.stock_num).index.tolist()
    if g.debug: log.info(f"入选: {len(selected)}只, TOP3: {selected[:3]}")
    
    # ===== 调仓 =====
    execute_trades(context, selected)

def get_factor_data(context, pool):
    q = query(
        valuation.code, valuation.pe_ratio,
        indicator.roe, indicator.gross_profit_margin,
        cash_flow.net_operate_cash_flow, income.net_profit,
    ).filter(valuation.code.in_(pool))
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return None
    df = df.set_index('code')
    
    df['pe_clean'] = df['pe_ratio'].apply(lambda x: x if (x and 0 < x < g.max_pe) else None)
    df['ocf_quality'] = (df['net_operate_cash_flow'] / df['net_profit'].replace(0, np.nan)).clip(-5, 5)
    df['roic_clean'] = df['roe']
    
    codes = df.index.tolist()
    prices = history(126, '1d', 'close', codes, df=False, skip_paused=True)
    vol_data = {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 63:
                vol_data[code] = s.pct_change().dropna().std() * np.sqrt(252)
    df['volatility_6m'] = pd.Series(vol_data)
    
    # 股息率(可选)
    try:
        div_q = query(valuation.code, valuation.dividend_yield_ratio
                     ).filter(valuation.code.in_(codes))
        div_df = get_fundamentals(div_q, date=context.current_dt)
        if div_df is not None and len(div_df) > 0:
            df['dividend_yield'] = div_df.set_index('code')['dividend_yield_ratio']
    except: df['dividend_yield'] = np.nan
    
    essential = ['roic_clean', 'gross_profit_margin', 'pe_clean', 'volatility_6m']
    df = df.dropna(subset=essential)
    if 'ocf_quality' in df.columns:
        df = df[df['ocf_quality'] > -2]
    return df

def calculate_scores(df):
    s = pd.DataFrame(index=df.index)
    s['s_roic'] = df['roic_clean'].rank(ascending=True, pct=True)
    s['s_gross'] = df['gross_profit_margin'].rank(ascending=True, pct=True)
    s['s_lowvol'] = df['volatility_6m'].rank(ascending=False, pct=True)
    s['s_pe'] = df['pe_clean'].rank(ascending=False, pct=True)
    s['s_ocf'] = df['ocf_quality'].rank(ascending=True, pct=True)
    s['total_score'] = s['s_roic']+s['s_gross']+s['s_lowvol']+s['s_pe']+s['s_ocf']
    if 'dividend_yield' in df.columns and df['dividend_yield'].notna().sum() > 5:
        s['s_div'] = df['dividend_yield'].rank(ascending=True, pct=True)
        s['total_score'] = s['total_score'] + s['s_div']
    return s

def execute_trades(context, selected):
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
    weight = (1 - g.cash_buffer) / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
