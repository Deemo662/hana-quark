# 策略2: ROE+6月波动率 (书中年化16.90%)
# 沪深300版

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
    pool = get_index_stocks('000300.XSHG')
    current_data = get_current_data()
    pool = [s for s in pool if not current_data[s].paused and not current_data[s].is_st]
    if len(pool) < 20: return

    q = query(valuation.code, indicator.roe).filter(valuation.code.in_(pool))
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return
    df = df.set_index('code')
    df.columns = ['roe']

    codes = df.index.tolist()
    prices = history(120, '1d', 'close', codes, df=False, skip_paused=True)
    vol_data = {}
    for code in codes:
        if code in prices:
            rets = pd.Series(prices[code]).pct_change().dropna()
            if len(rets) > 60:
                vol_data[code] = rets.std() * (252 ** 0.5)
    df['vol_6m'] = pd.Series(vol_data)
    df = df.dropna(subset=['roe', 'vol_6m'])
    if len(df) < 10: return

    # ROE(desc) + 波动率(asc) 各50%
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['roe'].rank(ascending=False, pct=True) * 50
    scores['b'] = df['vol_6m'].rank(ascending=True, pct=True) * 50
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
