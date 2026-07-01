# 改进版: ROE+毛利率+PE+动量+现金流质量
# 基于神奇公式回测结论: 保留有效因子(ROE/毛利/PE)，波动率→动量，加现金流排雷

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
    # 1. 股票池
    pool = get_index_stocks('000300.XSHG')
    current_data = get_current_data()
    pool = [s for s in pool if not current_data[s].paused and not current_data[s].is_st]
    if len(pool) < 20: return

    # 2. 基本面: ROE/毛利率/PE/现金流
    q = query(
        valuation.code, valuation.pe_ratio,
        indicator.roe, indicator.gross_profit_margin,
        indicator.inc_net_profit_year_on_year,         # 净利润增速
        balance.total_current_assets,                   # 流动资产
        balance.total_current_liability,                # 流动负债
        cash_flow.net_operate_cash_flow,               # 经营现金流
        income.net_profit                               # 净利润
    ).filter(valuation.code.in_(pool))

    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return
    df = df.set_index('code')

    # 计算流动比率和现金流质量
    df['current_ratio'] = df['total_current_assets'] / df['total_current_liability'].replace(0, 1)
    df['ocf_quality'] = df['net_operate_cash_flow'] / df['net_profit'].replace(0, 1)
    df['pe_positive'] = df['pe_ratio'].apply(lambda x: x if x and x > 0 else None)

    # 3. 6月动量（替代波动率）
    codes = df.index.tolist()
    prices = history(126, '1d', 'close', codes, df=False, skip_paused=True)
    mom_data = {}
    for code in codes:
        if code in prices:
            s = pd.Series(prices[code])
            if len(s) >= 126:
                mom_data[code] = (s.iloc[-1] - s.iloc[-126]) / s.iloc[-126]
    df['mom_6m'] = pd.Series(mom_data)

    # 4. 过滤
    df = df.dropna(subset=['roe', 'gross_profit_margin', 'pe_positive',
                            'mom_6m', 'ocf_quality', 'current_ratio'])
    # 筛掉现金流质量极差和流动比率过低
    df = df[(df['ocf_quality'] > -2) & (df['current_ratio'] > 0.5)]
    if len(df) < 10: return

    # 5. 打分: ROE(25%) + 毛利(20%) + 低PE(20%) + 动量(20%) + 现金流质量(15%)
    scores = pd.DataFrame(index=df.index)
    scores['a'] = df['roe'].rank(ascending=False, pct=True) * 25
    scores['b'] = df['gross_profit_margin'].rank(ascending=False, pct=True) * 20
    scores['c'] = df['pe_positive'].rank(ascending=True, pct=True) * 20
    scores['d'] = df['mom_6m'].rank(ascending=False, pct=True) * 20
    scores['e'] = df['ocf_quality'].rank(ascending=False, pct=True) * 15
    scores['total'] = scores.sum(axis=1)

    selected = scores.sort_values('total', ascending=False).head(g.stock_num).index.tolist()
    weight = 0.98 / len(selected)
    for code in selected:
        order_target_value(code, context.portfolio.total_value * weight)
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target_value(code, 0)
