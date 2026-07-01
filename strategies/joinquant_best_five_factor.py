"""
聚宽策略代码 — 直接复制粘贴到 joinquant.com 研究环境或策略编辑器
5条策略对应董鹏飞《基本面量化投资策略》第15章
"""

# ============================================================
# 策略1: 市值+毛利率+ROIC+6月波动率+PS (书中年化18.44%)
# ============================================================

def initialize_best_five_factor(context):
    """全书最强五因子策略"""
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_commission=0.00025, close_commission=0.00025,
        close_tax=0.0005, min_commission=5), type='stock')

    g.stock_num = 20
    g.factors = {
        'market_cap':       {'weight': 0.2, 'ascending': True},
        'gross_margin':     {'weight': 0.2, 'ascending': False},
        'roe':              {'weight': 0.2, 'ascending': False},   # ROIC替代
        'volatility_6m':    {'weight': 0.2, 'ascending': True},
        'ps_ratio':         {'weight': 0.2, 'ascending': True},
    }
    g.rebalance_months = [1, 4, 7, 10]  # 季末调仓（聚宽月频模拟接近书中年换手100%）
    run_monthly(trade_best_five, monthday=1)


def trade_best_five(context):
    """月度选股+调仓"""
    if context.current_dt.month not in g.rebalance_months:
        return

    # 1. 股票池：全A股，过滤ST/停牌/新股
    pool = _get_universe(context)

    # 2. 获取因子数据
    df = _get_fundamentals_batch(pool)
    if df is None or len(df) == 0:
        return

    # 3. 计算波动率因子
    prices = history(120, '1d', 'close', pool, df=False, skip_paused=True)
    vol = pd.Series({code: prices[code].pct_change().std() * (252 ** 0.5)
                     for code in pool if code in prices.columns})
    df['volatility_6m'] = df.index.map(lambda x: vol.get(x, None))

    # 4. 过滤缺失值
    df = df.dropna(subset=['market_cap', 'gross_margin', 'roe', 'volatility_6m', 'ps_ratio'])

    # 5. 打分排序
    scores = pd.DataFrame(index=df.index)
    for col, cfg in g.factors.items():
        ranked = df[col].rank(ascending=cfg['ascending'], pct=True)
        scores[col] = ranked * cfg['weight'] * 100

    scores['total'] = scores.sum(axis=1)
    scores = scores.sort_values('total', ascending=False)
    selected = scores.head(g.stock_num).index.tolist()

    # 6. 调仓
    _rebalance(context, selected)


def _get_universe(context):
    """构建股票池：全A股，剔除ST/停牌/次新股"""
    pool = list(get_all_securities(['stock']).index)
    current_data = get_current_data()

    filtered = []
    for code in pool:
        c = current_data[code]
        if c.paused or c.is_st:
            continue
        # 剔除上市不足180天
        days_listed = (context.current_dt.date() - c.start_date).days
        if days_listed < 180:
            continue
        filtered.append(code)
    return filtered


def _get_fundamentals_batch(codes):
    """批量获取基本面数据"""
    q = query(
        valuation.code,
        valuation.market_cap,
        valuation.ps_ratio,
        indicator.gross_profit_margin,
        indicator.roe,
    ).filter(valuation.code.in_(codes))

    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0:
        return None

    df = df.set_index('code')
    df = df.rename(columns={
        'market_cap': 'market_cap',
        'ps_ratio': 'ps_ratio',
        'gross_profit_margin': 'gross_margin',
        'roe': 'roe',
    })
    return df


def _rebalance(context, target_codes):
    """调仓：清仓不在目标清单的，等权买入目标"""
    current_positions = list(context.portfolio.positions.keys())

    # 卖出不在目标清单的
    for code in current_positions:
        if code not in target_codes:
            order_target_value(code, 0)

    if len(target_codes) == 0:
        return

    weight = 0.98 / len(target_codes)
    for code in target_codes:
        order_target_value(code, context.portfolio.total_value * weight)


# ============================================================
# 策略2: ROE+6月波动率 (书中年化16.90%)
# ============================================================

def initialize_roe_lowvol(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_commission=0.00025, close_commission=0.00025,
        close_tax=0.0005, min_commission=5), type='stock')
    g.stock_num = 20
    run_monthly(trade_roe_lowvol, monthday=1)


def trade_roe_lowvol(context):
    pool = _get_universe(context)
    df = _get_fundamentals_batch(pool)
    if df is None: return

    prices = history(120, '1d', 'close', pool, df=False, skip_paused=True)
    vol = pd.Series({c: prices[c].pct_change().std() * (252**0.5)
                     for c in pool if c in prices.columns})
    df['volatility_6m'] = df.index.map(lambda x: vol.get(x, None))

    df = df.dropna(subset=['roe', 'volatility_6m'])

    # ROE: rank desc (越高越好), 波动率: rank asc (越低越好)
    scores = pd.DataFrame(index=df.index)
    scores['roe_score'] = df['roe'].rank(ascending=False, pct=True) * 50
    scores['vol_score'] = df['volatility_6m'].rank(ascending=True, pct=True) * 50
    scores['total'] = scores.sum(axis=1)
    scores = scores.sort_values('total', ascending=False)

    _rebalance(context, scores.head(g.stock_num).index.tolist())


# ============================================================
# 策略3: 中小市值改进神奇公式 (书中年化16.48%)
# ============================================================

def initialize_magic_formula(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_commission=0.00025, close_commission=0.00025,
        close_tax=0.0005, min_commission=5), type='stock')
    g.stock_num = 20
    run_monthly(trade_magic, monthday=1)


def trade_magic(context):
    pool = _get_universe(context)
    # 先筛小市值
    q = query(
        valuation.code, valuation.market_cap,
        valuation.pe_ratio, indicator.roe, indicator.gross_profit_margin
    ).filter(valuation.code.in_(pool))
    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0: return
    df = df.set_index('code')

    # 波动率
    prices = history(120, '1d', 'close', pool, df=False, skip_paused=True)
    vol = pd.Series({c: prices[c].pct_change().std() * (252**0.5)
                     for c in pool if c in prices.columns})
    df['volatility_6m'] = df.index.map(lambda x: vol.get(x, None))
    df = df.dropna()

    # 4因子等权：小市值+低波+高ROE+高毛利+低PE
    scores = pd.DataFrame(index=df.index)
    scores['mv'] = df['market_cap'].rank(ascending=True, pct=True) * 20
    scores['vol'] = df['volatility_6m'].rank(ascending=True, pct=True) * 20
    scores['roe'] = df['roe'].rank(ascending=False, pct=True) * 20
    scores['gm'] = df['gross_profit_margin'].rank(ascending=False, pct=True) * 20
    scores['pe'] = df['pe_ratio'].where(df['pe_ratio'] > 0).rank(ascending=True, pct=True) * 20
    scores['total'] = scores.sum(axis=1)
    scores = scores.sort_values('total', ascending=False)

    _rebalance(context, scores.head(g.stock_num).index.tolist())


# ============================================================
# 简化入口：复制策略名到研究环境运行
# ============================================================

# 在聚宽研究环境中运行：
# 1. 复制以上代码
# 2. 选择策略: initialize_best_five_factor, initialize_roe_lowvol, initialize_magic_formula
# 3. 设置回测区间: 2021-01-01 ~ 2025-12-31
# 4. 初始资金: 100000
# 5. 点击"运行回测"
