# 五因子策略: 市值+毛利率+ROE+6月波动率+PS
# 来源: 董鹏飞《基本面量化投资策略》第15章 (书中年化18.44%)
# 复制到聚宽策略编辑器 → 日期2021-01-01~2025-12-31 → 运行回测

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
    # 1. 全A股股票池（剔除ST/停牌/次新股）
    current_data = get_current_data()
    pool = []
    for s in get_all_securities(['stock']).index:
        c = current_data[s]
        if c.paused or c.is_st:
            continue
        # 剔次新股：上市不足180天
        info = get_security_info(s)
        if info is None:
            continue
        days_listed = (context.current_dt.date() - info.start_date).days
        if days_listed < 180:
            continue
        pool.append(s)

    if len(pool) < 20:
        return

    # 2. 基本面数据
    q = query(
        valuation.code, valuation.market_cap, valuation.ps_ratio,
        indicator.gross_profit_margin, indicator.roe
    ).filter(valuation.code.in_(pool))

    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0:
        return
    df = df.set_index('code')
    df.columns = ['market_cap', 'ps_ratio', 'gross_margin', 'roe']

    # 3. 6月波动率（history返回dict，用prices[s]取值）
    codes = df.index.tolist()
    prices = history(120, '1d', 'close', codes, df=False, skip_paused=True)

    vol_data = {}
    for code in codes:
        if code in prices:
            rets = pd.Series(prices[code]).pct_change().dropna()
            if len(rets) > 60:
                vol_data[code] = rets.std() * (252 ** 0.5)
    df['vol_6m'] = pd.Series(vol_data)

    # 4. 过滤
    df = df.dropna(subset=['market_cap', 'gross_margin', 'roe', 'vol_6m', 'ps_ratio'])
    if len(df) < 10:
        return

    # 5. 打分（等权20%×5因子）
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['market_cap'].rank(ascending=True, pct=True) * 20
    scores['b'] = df['gross_margin'].rank(ascending=False, pct=True) * 20
    scores['c'] = df['roe'].rank(ascending=False, pct=True) * 20
    scores['d'] = df['vol_6m'].rank(ascending=True, pct=True) * 20
    scores['e'] = df['ps_ratio'].rank(ascending=True, pct=True) * 20
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()

    # 6. 调仓
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
