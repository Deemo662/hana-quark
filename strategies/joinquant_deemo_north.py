# deemo精简版: 动量+ROE+PE+北向资金
# 来源: deemo A股深度报告 + 聚宽回测验证

import pandas as pd

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_commission=0.00025, close_commission=0.00025,
        close_tax=0.0005, min_commission=5), type='stock')
    g.stock_num = 20
    run_monthly(rebalance, monthday=1, time='open')


def rebalance(context):
    # 1. 全A股，过滤ST/停牌/次新股/高位股
    current_data = get_current_data()
    pool = []
    for s in get_all_securities(['stock']).index:
        c = current_data[s]
        if c.paused or c.is_st: continue
        info = get_security_info(s)
        if info is None: continue
        if (context.current_dt.date() - info.start_date).days < 180: continue
        pool.append(s)
    if len(pool) < 20: return

    # 2. 基本面: PE + ROE
    q = query(
        valuation.code, valuation.pe_ratio,
        indicator.roe, indicator.gross_profit_margin
    ).filter(valuation.code.in_(pool[:500]))
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return
    df = df.set_index('code')
    df.columns = ['pe', 'roe', 'gross_margin']
    df['pe_positive'] = df['pe'].apply(lambda x: x if x and x > 0 else None)

    # 3. 3月动量
    codes = df.index.tolist()
    prices = history(63, '1d', 'close', codes, df=False, skip_paused=True)
    mom_data = {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 50:
                mom_data[code] = (s.iloc[-1] - s.iloc[0]) / s.iloc[0] * 100
    df['mom_3m'] = pd.Series(mom_data)

    # 4. 排除20日涨幅>80%的高位股（deemo建议）
    prices20 = history(20, '1d', 'close', codes, df=False, skip_paused=True)
    mom20 = {}
    for code in codes:
        if code in prices20:
            s = pd.Series(prices20[code])
            if len(s) >= 15:
                mom20[code] = (s.iloc[-1] - s.iloc[0]) / s.iloc[0] * 100
    df['mom_20d'] = pd.Series(mom20)

    # 5. 北向资金: 最近5日净流入
    try:
        north = {}
        end_date = context.current_dt
        start_date = end_date - pd.Timedelta(days=10)
        # 聚宽北向资金表
        north_df = get_money_flow(codes, start_date, end_date, 
                                   fields=['date','sec_code','net_amount_main'])
        if north_df is not None and not north_df.empty:
            for code in codes:
                cdf = north_df[north_df['sec_code'] == code]
                if len(cdf) >= 3:
                    north[code] = cdf['net_amount_main'].tail(5).sum()
        df['north_flow'] = pd.Series(north)
    except:
        # 如果API不可用，用成交量增幅替代
        vols = history(40, '1d', 'volume', codes, df=False, skip_paused=True)
        vol_chg = {}
        for code in codes:
            if code in vols:
                s = pd.Series(vols[code])
                if len(s) >= 30:
                    vol_chg[code] = s.iloc[-20:].mean() / s.iloc[-40:-20].mean() - 1
        df['north_flow'] = pd.Series(vol_chg)

    # 6. 过滤
    df = df.dropna(subset=['pe_positive', 'roe', 'mom_3m', 'north_flow', 'mom_20d'])
    df = df[df['mom_20d'] < 80]  # 排除高位股
    df = df[df['pe_positive'] > 0]
    if len(df) < 10: return

    # 7. 打分: 动量35% + ROE30% + PE20% + 北向15%
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['mom_3m'].rank(ascending=False, pct=True) * 35
    scores['b'] = df['roe'].rank(ascending=False, pct=True) * 30
    scores['c'] = df['pe_positive'].rank(ascending=True, pct=True) * 20
    scores['d'] = df['north_flow'].rank(ascending=False, pct=True) * 15
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
