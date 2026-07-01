# 融合版: 小市值+动量+ROE+双周调仓+10只集中
# 吸取小市值策略(13%)和v2动量(3.8%)各自优势

import pandas as pd

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_commission=0.00025, close_commission=0.00025,
        close_tax=0.0005, min_commission=5), type='stock')
    g.stock_num = 10
    g.days = 0
    g.refresh_rate = 10
    run_daily(check_and_trade, 'every_bar')


def check_and_trade(context):
    g.days += 1
    if g.days % g.refresh_rate != 0:
        return

    # 1. 股票池: 市值20-100亿(只用valuation表，和系统策略一致)
    current_data = get_current_data()
    q = query(
        valuation.code, valuation.market_cap, valuation.pe_ratio
    ).filter(
        valuation.market_cap.between(20, 100)
    ).order_by(valuation.market_cap.asc())

    df = get_fundamentals(q)
    if df is None or len(df) == 0: return
    df = df.set_index('code')
    df.columns = ['market_cap', 'pe']

    # 过滤停牌/ST
    valid = []
    for c in df.index:
        if c in current_data and not current_data[c].paused and not current_data[c].is_st:
            valid.append(c)
    df = df.loc[valid]
    if len(df) < g.stock_num: return

    # 2. 3月动量
    codes = df.index.tolist()
    p63 = history(63, '1d', 'close', codes, df=False, skip_paused=True)
    mom3 = {}
    for c in codes:
        if c in p63:
            s = pd.Series(p63[c])
            if len(s) >= 50:
                mom3[c] = (s.iloc[-1] - s.iloc[0]) / s.iloc[0] * 100
    df['mom_3m'] = pd.Series(mom3)

    # 3. 排除高位股
    df = df[df['mom_3m'] < 80]
    df = df.dropna(subset=['pe', 'mom_3m'])
    df = df[df['pe'] > 0]
    if len(df) < g.stock_num: return

    # 4. 打分: 市值30% + 动量50% + 低PE20%
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['market_cap'].rank(ascending=True, pct=True) * 30
    scores['b'] = df['mom_3m'].rank(ascending=False, pct=True) * 50
    scores['c'] = df['pe'].rank(ascending=True, pct=True) * 20
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()

    # 6. 调仓
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
    if len(selected) > 0:
        weight = 0.98 / len(selected)
        for code in selected:
            order_target_value(code, context.portfolio.total_value * weight)
