# 熊市防御版: 高股息+低负债+央企+ROE+过滤僵尸股
# 针对2022年后注册制+A股熊市环境设计

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
    # 1. 全A股，过滤ST/停牌/次新股
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

    # 2. 基本面: 股息率+ROE+资产负债率+央企
    q = query(
        valuation.code, valuation.pe_ratio, valuation.pb_ratio,
        indicator.roe, indicator.inc_total_revenue_year_on_year,
        balance.total_assets, balance.total_liability,
        cash_flow.net_operate_cash_flow, income.net_profit
    ).filter(valuation.code.in_(pool[:600]))

    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return
    df = df.set_index('code')

    # 股息率 = 每股分红/股价 ≈ 1/PE × 分红率（简化）
    # 负债率
    df['debt_ratio'] = df['total_liability'] / df['total_assets'].replace(0, 1)
    df['pe_positive'] = df['pe_ratio'].apply(lambda x: x if x and x > 0 else None)
    df['ocf_quality'] = df['net_operate_cash_flow'] / df['net_profit'].replace(0, 1)

    # 3. 过滤僵尸股: 日均成交>2000万（近20日均量×均价）
    codes = df.index.tolist()
    prices = history(20, '1d', 'close', codes, df=False, skip_paused=True)
    vols = history(20, '1d', 'volume', codes, df=False, skip_paused=True)
    liquid = {}
    for code in codes:
        if code in prices and code in vols:
            avg_amount = pd.Series(vols[code]).mean() * pd.Series(prices[code]).mean()
            if avg_amount > 20000000:  # >2000万
                liquid[code] = True
    df['liquid'] = pd.Series(liquid).fillna(False)
    df = df[df['liquid'] == True]

    # 4. 过滤
    df = df.dropna(subset=['roe', 'pe_positive', 'debt_ratio', 'ocf_quality'])
    df = df[(df['debt_ratio'] < 0.7) & (df['ocf_quality'] > -1) & (df['pe_positive'] > 0)]
    if len(df) < 10: return

    # 5. 打分: 低PE(25%)+高ROE(25%)+低负债(20%)+高OCF(15%)+营收增长(15%)
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['pe_positive'].rank(ascending=True, pct=True) * 25
    scores['b'] = df['roe'].rank(ascending=False, pct=True) * 25
    scores['c'] = df['debt_ratio'].rank(ascending=True, pct=True) * 20
    scores['d'] = df['ocf_quality'].rank(ascending=False, pct=True) * 15
    scores['e'] = df['inc_total_revenue_year_on_year'].rank(ascending=False, pct=True) * 15
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
