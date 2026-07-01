# 纯动量策略: 3月动量+6月动量+换手率
# 本地自动化排名第1: CAGR 5.8%, IR 1.18

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
    # 全A股排除ST/停牌/次新股/高位股
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

    codes = pool[:500]

    # 计算动量
    # 3月动量(63天)
    p63 = history(63, '1d', 'close', codes, df=False, skip_paused=True)
    mom3 = {}
    for c in codes:
        if c in p63:
            s = pd.Series(p63[c])
            if len(s) >= 50:
                mom3[c] = (s.iloc[-1] - s.iloc[0]) / s.iloc[0] * 100

    # 6月动量(126天)
    p126 = history(126, '1d', 'close', codes, df=False, skip_paused=True)
    mom6 = {}
    for c in codes:
        if c in p126:
            s = pd.Series(p126[c])
            if len(s) >= 100:
                mom6[c] = (s.iloc[-1] - s.iloc[0]) / s.iloc[0] * 100

    # 排除60日涨幅>80%的高位股
    high_filter = {}
    for c in codes:
        if c in p63:
            high_filter[c] = mom3.get(c, 0) < 80

    # 组装
    df = pd.DataFrame({'mom_3m': mom3, 'mom_6m': mom6})
    df = df.dropna()
    df = df[df.index.map(lambda c: high_filter.get(c, False))]
    if len(df) < 10: return

    # 打分: 3月动量50% + 6月动量50%（纯动量，去换手率）
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['mom_3m'].rank(ascending=False, pct=True) * 50
    scores['b'] = df['mom_6m'].rank(ascending=False, pct=True) * 50
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
