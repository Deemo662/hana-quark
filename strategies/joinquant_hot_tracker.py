# 热点追踪策略 v2: 周频调仓 + 百分位筛选 + PE质量过滤
import pandas as pd

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_commission=0.00025, close_commission=0.00025,
        close_tax=0.0005, min_commission=5), type='stock')
    g.stock_num = 10
    g.days = 0
    g.refresh_rate = 5  # 每周调仓
    run_daily(trade, 'every_bar')


def trade(context):
    g.days += 1
    if g.days % g.refresh_rate != 0:
        return

    # 1. 全A股过滤
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
    codes = pool[:800]

    # 2. 热度=10日动量+量比
    p10 = history(10, '1d', 'close', codes, df=False, skip_paused=True)
    v10 = history(10, '1d', 'volume', codes, df=False, skip_paused=True)
    v20 = history(20, '1d', 'volume', codes, df=False, skip_paused=True)

    mom10, vol_ratio = {}, {}
    for c in codes:
        if c in p10 and c in v10 and c in v20:
            pc = pd.Series(p10[c])
            vc = pd.Series(v10[c])
            vp = pd.Series(v20[c])
            if len(pc) >= 8 and len(vp) >= 15:
                mom10[c] = (pc.iloc[-1] - pc.iloc[0]) / pc.iloc[0] * 100
                vol_ratio[c] = vc.mean() / vp.iloc[:10].mean() if vp.iloc[:10].mean() > 0 else 1

    # 3. PE(只用valuation表)
    q = query(valuation.code, valuation.pe_ratio).filter(valuation.code.in_(codes))
    df = get_fundamentals(q)
    if df is None or len(df) == 0: return
    df = df.set_index('code')
    df.columns = ['pe']
    df['pe'] = df['pe'].apply(lambda x: x if x and x > 0 else None)
    df['mom10'] = pd.Series(mom10)
    df['vol_ratio'] = pd.Series(vol_ratio)
    df = df.dropna()
    if len(df) < g.stock_num: return

    # 4. 排除今日涨停
    p2 = history(2, '1d', 'close', codes, df=False, skip_paused=True)
    for c in df.index:
        if c in p2 and c in current_data:
            s = pd.Series(p2[c])
            if len(s) >= 2 and s.iloc[-2] > 0:
                pct = (current_data[c].last_price / s.iloc[-2] - 1) * 100
                if pct > 9.5:
                    df = df.drop(c)

    # 5. 热度池=动量前40% AND 量比前50%
    mom_threshold = df['mom10'].quantile(0.6)
    vol_threshold = df['vol_ratio'].quantile(0.5)
    hot_pool = df[(df['mom10'] > mom_threshold) & (df['vol_ratio'] > vol_threshold)]
    if len(hot_pool) < g.stock_num:
        hot_pool = df.nlargest(g.stock_num * 3, 'mom10')

    # 6. 在热点池内: 动量40%+量能30%+低PE30%
    scores = pd.DataFrame(index=hot_pool.index)
    scores['a'] = hot_pool['mom10'].rank(ascending=False, pct=True) * 40
    scores['b'] = hot_pool['vol_ratio'].rank(ascending=False, pct=True) * 30
    scores['c'] = hot_pool['pe'].rank(ascending=True, pct=True) * 30
    scores['total'] = scores.sum(axis=1)
    selected = scores.nlargest(g.stock_num, 'total').index.tolist()

    # 7. 调仓
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
