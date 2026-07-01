# ============================================================
# 质量低波选股策略 v3 增强版
#
# v2 → v3 升级:
#   ① 全A股股票池（5000+只），仅过滤ST/停牌/次新/负PE/市值末20%
#   ② 大盘择时：沪深300<MA200时空仓避险
#   ③ ROIC替代ROE（排除高杠杆伪优质股）
#   ④ 行业集中度上限（单一行业≤30%）
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
    
    g.stock_num = 25
    g.max_pe = 200
    g.min_list_days = 500
    g.ma_period = 200
    g.max_sector_pct = 0.30
    g.cash_buffer = 0.02
    
    run_monthly(rebalance, monthday=1, time='open')


def rebalance(context):
    # ===== ★第0步: 大盘择时 =====
    hs300 = history(g.ma_period, '1d', 'close', ['000300.XSHG'], df=False, skip_paused=True)
    if '000300.XSHG' in hs300:
        ma200 = pd.Series(hs300['000300.XSHG']).mean()
        if hs300['000300.XSHG'][-1] < ma200:
            for code in list(context.portfolio.positions.keys()):
                order_target_value(code, 0)
            return
    
    # ===== 第1步: 全A股股票池 =====
    pool = build_universe(context)
    if len(pool) < 30: return
    
    # ===== 第2步: 因子 =====
    df = get_factor_data(context, pool)
    if df is None or len(df) < 20: return
    
    # ===== 第3步: 打分 =====
    df = calculate_scores(df)
    
    # ===== 第4步: 行业集中度控制 =====
    selected = select_with_sector_limit(context, df, g.stock_num, g.max_sector_pct)
    
    # ===== 第5步: 调仓 =====
    execute_trades(context, selected)


def build_universe(context):
    """全A股池 + 五维过滤"""
    pool = list(get_all_securities(['stock'], context.current_dt).index)
    current_data = get_current_data()
    sec_info = get_all_securities(['stock'], context.current_dt)
    
    valid = []
    for s in pool:
        if s not in current_data or current_data[s].paused or current_data[s].is_st:
            continue
        if s in sec_info.index:
            days = (context.current_dt.date() - sec_info.loc[s, 'start_date']).days
            if days < g.min_list_days:
                continue
        valid.append(s)
    
    if len(valid) < 50: return valid
    
    q = query(valuation.code, valuation.pe_ratio, valuation.market_cap
             ).filter(valuation.code.in_(valid))
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return valid
    
    df = df[(df['pe_ratio'] > 0) & (df['pe_ratio'] < g.max_pe)]
    if 'market_cap' in df.columns and len(df) > 50:
        df = df[df['market_cap'] > df['market_cap'].quantile(0.20)]
    
    return df['code'].tolist()


def get_factor_data(context, pool):
    """★v3: ROIC替代ROE"""
    q = query(
        valuation.code, valuation.pe_ratio, valuation.ps_ratio,
        indicator.roe, indicator.roic, indicator.gross_profit_margin,
        cash_flow.net_operate_cash_flow, income.net_profit,
    ).filter(valuation.code.in_(pool))
    
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return None
    df = df.set_index('code')
    
    df['pe_clean'] = df['pe_ratio'].apply(lambda x: x if (x and 0 < x < g.max_pe) else None)
    df['ocf_quality'] = (df['net_operate_cash_flow'] / df['net_profit'].replace(0, np.nan)).clip(-5, 5)
    df['roic_clean'] = df['roic'].fillna(df['roe'])
    
    codes = df.index.tolist()
    prices = history(126, '1d', 'close', codes, df=False, skip_paused=True)
    vol_data, mom_data = {}, {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 63:
                rets = s.pct_change().dropna()
                vol_data[code] = rets.std() * np.sqrt(252)
            if len(s) >= 126:
                mom_data[code] = (s.iloc[-1] - s.iloc[-126]) / s.iloc[-126]
    df['volatility_6m'] = pd.Series(vol_data)
    df['momentum_6m'] = pd.Series(mom_data)
    
    try:
        div_q = query(valuation.code, valuation.dividend_yield_ratio
                     ).filter(valuation.code.in_(codes))
        div_df = get_fundamentals(div_q, date=context.current_dt)
        if div_df is not None and len(div_df) > 0:
            df['dividend_yield'] = div_df.set_index('code')['dividend_yield_ratio']
    except:
        df['dividend_yield'] = np.nan
    
    essential = ['roic_clean', 'gross_profit_margin', 'pe_clean', 'volatility_6m']
    df = df.dropna(subset=essential)
    if 'ocf_quality' in df.columns:
        df = df[df['ocf_quality'] > -2]
    return df


def calculate_scores(df):
    """等权打分"""
    s = pd.DataFrame(index=df.index)
    s['s_roic'] = df['roic_clean'].rank(ascending=True, pct=True)
    s['s_gross'] = df['gross_profit_margin'].rank(ascending=True, pct=True)
    s['s_lowvol'] = df['volatility_6m'].rank(ascending=False, pct=True)
    s['s_pe'] = df['pe_clean'].rank(ascending=False, pct=True)
    s['s_ocf'] = df['ocf_quality'].rank(ascending=True, pct=True)
    s['total_score'] = s['s_roic'] + s['s_gross'] + s['s_lowvol'] + s['s_pe'] + s['s_ocf']
    if 'dividend_yield' in df.columns and df['dividend_yield'].notna().sum() > 5:
        s['s_div'] = df['dividend_yield'].rank(ascending=True, pct=True)
        s['total_score'] = s['total_score'] + s['s_div']
    return s


def select_with_sector_limit(context, df, top_n, max_pct):
    """行业集中度控制"""
    df = df.sort_values('total_score', ascending=False)
    sector_count, selected = {}, []
    
    for code in df.index:
        try:
            info = get_security_info(code)
            sector = info.industry_name if hasattr(info, 'industry_name') and info.industry_name else '其他'
        except:
            sector = '未知'
        
        current_pct = sector_count.get(sector, 0) / max(top_n, 1)
        if current_pct >= max_pct and len(selected) >= 5:
            continue
        
        selected.append(code)
        sector_count[sector] = sector_count.get(sector, 0) + 1
        if len(selected) >= top_n: break
    
    return selected


def execute_trades(context, selected):
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
    weight = (1 - g.cash_buffer) / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
