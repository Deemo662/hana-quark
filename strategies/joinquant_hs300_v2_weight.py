# 改进版v2: 调权重 ROE(30%)+动量(25%)+低PE(20%)+毛利(15%)+现金流(10%)
# 沪深300版快速验证

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

    q = query(
        valuation.code, valuation.pe_ratio,
        indicator.roe, indicator.gross_profit_margin,
        balance.total_current_assets, balance.total_current_liability,
        cash_flow.net_operate_cash_flow, income.net_profit
    ).filter(valuation.code.in_(pool))

    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return
    df = df.set_index('code')

    df['current_ratio'] = df['total_current_assets'] / df['total_current_liability'].replace(0, 1)
    df['ocf_quality'] = df['net_operate_cash_flow'] / df['net_profit'].replace(0, 1)
    df['pe_positive'] = df['pe_ratio'].apply(lambda x: x if x and x > 0 else None)

    codes = df.index.tolist()
    prices = history(126, '1d', 'close', codes, df=False, skip_paused=True)
    mom_data = {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 126:
                mom_data[code] = (s.iloc[-1] - s.iloc[-126]) / s.iloc[-126]
    df['mom_6m'] = pd.Series(mom_data)

    df = df.dropna(subset=['roe', 'gross_profit_margin', 'pe_positive',
                            'mom_6m', 'ocf_quality', 'current_ratio'])
    df = df[(df['ocf_quality'] > -2) & (df['current_ratio'] > 0.5)]
    if len(df) < 10: return

    # ⭐ 权重调整: ROE↑ 动量↑ PE不变 毛利↓ 现金流↓
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['roe'].rank(ascending=False, pct=True) * 30
    scores['b'] = df['mom_6m'].rank(ascending=False, pct=True) * 25
    scores['c'] = df['pe_positive'].rank(ascending=True, pct=True) * 20
    scores['d'] = df['gross_profit_margin'].rank(ascending=False, pct=True) * 15
    scores['e'] = df['ocf_quality'].rank(ascending=False, pct=True) * 10
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
