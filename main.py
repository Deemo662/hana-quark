#!/usr/bin/env python3
"""
量化交易系统 - 主入口

用法:
  python main.py fetch              # 拉取全量数据（首次约1-2小时）
  python main.py fetch --test 10    # 测试模式：只拉10只
  python main.py report             # 数据质量报告
  python main.py run                # 每日运行：更新→因子→打分→信号
  python main.py backtest           # 回测模式

数据源: Baostock（缓存模式）/ AkShare（实时选股模式）
"""

import sys, os, logging, argparse, yaml
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.cache import DataCache
from data.akshare_provider import AkShareFetcher
from data.baostock_fetcher import BaostockFetcher
from data.cache_provider import CacheProvider

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# =====================================================================
# 数据拉取
# =====================================================================

def cmd_fetch(args):
    """拉取全量数据到SQLite"""
    cache = DataCache(db_path='data/cache/quant.db')
    fetcher = BaostockFetcher()
    
    try:
        end_date = args.end or datetime.now().strftime('%Y%m%d')
        stock_codes = None
        
        if args.test:
            n = int(args.test)
            # 测试模式：精选代表股票
            test_codes = [
                '600519', '000858', '000568',  # 白酒
                '600036', '601318',             # 金融
                '000333', '000651',             # 家电
                '300750', '002594',             # 新能源
                '600276', '300760',             # 医药
                '600900',                       # 电力
                '600585', '600887',             # 水泥/食品
                '002415', '000002',             # 科技/地产
                '600030', '601899',             # 券商/矿业
                '000001', '600887',             # 银行/食品
            ][:n]
            stock_codes = test_codes
            logger.info(f"测试模式：{len(stock_codes)} 只股票")
        
        fetcher.fetch_all(
            cache=cache,
            start_date=args.start or '20100101',
            end_date=end_date,
            stock_codes=stock_codes,
            skip_kline=args.skip_kline,
            skip_financial=args.skip_financial,
        )
        
        # 拉完自动生成质量报告
        cmd_report(args)
        
    finally:
        cache.close()


# =====================================================================
# 数据质量报告
# =====================================================================

def cmd_report(args):
    """生成数据质量报告"""
    cache = DataCache(db_path='data/cache/quant.db')
    
    try:
        stats = cache.get_table_stats()
        
        print("\n" + "=" * 60)
        print("  数据质量报告")
        print("=" * 60)
        print(f"\n  股票总数:     {stats.get('stock_info_rows', 0):,}")
        print(f"  K线总条数:    {stats.get('daily_kline_rows', 0):,}")
        print(f"  K线日期范围:  {stats.get('kline_date_range', 'N/A')}")
        print(f"  K线覆盖股票:  {stats.get('kline_stock_count', 0):,}")
        print(f"  财务数据条数: {stats.get('financial_data_rows', 0):,}")
        print(f"  财务日期范围: {stats.get('financial_date_range', 'N/A')}")
        
        import pandas as pd
        
        # K线抽样
        try:
            sample = pd.read_sql(
                "SELECT code, COUNT(*) as n, MIN(close) as min_c, MAX(close) as max_c "
                "FROM daily_kline GROUP BY code ORDER BY RANDOM() LIMIT 5",
                cache.conn
            )
            if len(sample) > 0:
                print(f"\n  K线抽样（5只）:")
                for _, r in sample.iterrows():
                    print(f"    {r['code']}: {r['n']}条, 价格{r['min_c']:.2f}~{r['max_c']:.2f}")
        except Exception as e:
            print(f"  ⚠ 抽样失败: {e}")
        
        # PE数据
        try:
            pe = pd.read_sql(
                "SELECT code, pe_ttm, pb, ps_ttm FROM financial_data "
                "WHERE pe_ttm IS NOT NULL AND pe_ttm > 0 ORDER BY report_date DESC LIMIT 5",
                cache.conn
            )
            if len(pe) > 0:
                print(f"\n  估值抽样（PE/PB/PS）:")
                print(pe.to_string(index=False))
        except:
            pass
        
        print("\n" + "=" * 60)
        
    finally:
        cache.close()


# =====================================================================
# 每日运行：因子 → 打分 → 信号
# =====================================================================

def cmd_run(args):
    """每日运行模式"""
    provider = CacheProvider(db_path='data/cache/quant.db')
    
    try:
        trade_date = date.today()
        logger.info(f"运行日期: {trade_date}")
        
        # 获取股票列表
        stock_list = provider.get_stock_list(trade_date)
        logger.info(f"全市场股票: {len(stock_list)} 只")
        
        # 股票池过滤
        from screening.universe import UniverseBuilder
        universe_builder = UniverseBuilder()
        
        all_codes = (stock_list.index if hasattr(stock_list.index, 'tolist') 
                     else stock_list['code']).tolist()
        daily_indicators = provider.get_daily_indicators(all_codes[:500], trade_date)
        universe = universe_builder.build(trade_date, stock_list, daily_indicators)
        logger.info(f"可投资股票池: {len(universe)} 只")
        
        # 加载策略
        with open('config/strategies.yaml', 'r') as f:
            config = yaml.safe_load(f)
        
        strategies = config.get('strategies', {})
        
        # 行情数据（用于动量/波动率）
        from factors.base import FactorData
        start_date = trade_date - timedelta(days=365)
        market_data = provider.get_market_data(list(universe)[:200], start_date, trade_date)
        
        factor_data = FactorData(
            trade_date=trade_date,
            market_data=market_data,
            daily_indicators=daily_indicators,
            financial_data=provider.get_financial_data(list(universe)[:200], trade_date),
        )
        
        # 对每个策略打分
        from screening.scorer import FactorScorer
        
        for key, cfg in strategies.items():
            name = cfg.get('name', key)
            factor_names = cfg.get('factors', [])
            top_n = cfg.get('top_n', 20)
            
            scorer = FactorScorer(sort_orders=cfg.get('sort_orders', {}))
            factor_values = scorer.compute_factors(factor_names, factor_data, universe[:200])
            
            if not factor_values:
                logger.warning(f"  {name}: 无可用因子值，跳过")
                continue
            
            scored = scorer.score(factor_values)
            selected = scorer.select_top(scored, top_n)
            
            book_cagr = cfg.get('book_cagr_20', '?')
            print(f"\n{'='*50}")
            print(f"  {name}")
            print(f"  书本年化: {book_cagr}%  |  因子数: {len(factor_values)}  |  选{top_n}只")
            print(f"  TOP 5: {selected[:5]}")
        
        logger.info("\n每日运行完成。")
        
    finally:
        provider.close()


# =====================================================================
# 实时选股（--live）— 从AkShare直接拉取，不经过缓存
# =====================================================================

def cmd_screen(args):
    """实时选股: AkShare直连, 计算因子并输出选股结果"""
    import akshare as ak
    from factors.base import FactorData
    from screening.scorer import FactorScorer

    def safe_float(val):
        try:
            if val is None: return None
            f = float(val)
            return None if np.isnan(f) or np.isinf(f) else f
        except (ValueError, TypeError):
            return None

    # ---- 加载策略 ----
    with open('config/strategies.yaml', 'r') as f:
        config = yaml.safe_load(f)

    strategy_name = args.strategy or 'best_five_factor'
    strategy_cfg = config['strategies'].get(strategy_name)
    if not strategy_cfg:
        print(f"错误: 策略 '{strategy_name}' 未找到")
        print(f"可用策略: {list(config['strategies'].keys())}")
        return

    print(f"\n{'='*60}")
    print(f"  实时选股: {strategy_cfg['name']}")
    print(f"  数据源: AkShare (live)")
    print(f"{'='*60}\n")

    fetcher = AkShareFetcher(max_retries=1, delay=0.15)
    trade_date = date.today()

    # 股票池 — 从AkShare动态获取全量A股
    print(f"[0/5] 获取A股全量列表...")
    import akshare as ak
    try:
        all_stocks = ak.stock_info_a_code_name()
        all_codes = all_stocks['code'].astype(str).str.zfill(6).tolist()
        print(f"  ✓ 全市场: {len(all_codes)} 只")
    except Exception:
        all_codes = ['600519','000858','600036','601318','000333','300750']
        print(f"  ⚠ 降级到硬编码列表: {len(all_codes)} 只")

    target_n = args.test if args.test else 400
    demo_codes = all_codes[:target_n]
    print(f"  → 本次采样: {len(demo_codes)} 只")

    # [1] 行情
    print(f"[1/5] 拉取 {len(demo_codes)} 只股票行情...")
    kline_rows, close_prices = [], {}
    for code in tqdm(demo_codes, desc="  行情"):
        try:
            df = fetcher._fetch_single_kline(
                code,
                (trade_date - timedelta(days=400)).strftime('%Y%m%d'),
                trade_date.strftime('%Y%m%d')
            )
            if len(df) > 0:
                kline_rows.append(df)
                close_prices[code] = float(df.iloc[-1]['close'])
        except Exception:
            pass

    if not kline_rows:
        print("错误: 未拉取到任何行情数据")
        return

    market_data = pd.concat(kline_rows, ignore_index=True)
    market_data['date'] = pd.to_datetime(market_data['trade_date'])
    market_data = market_data.set_index(['code', 'date']).sort_index()
    valid_codes = list(market_data.index.get_level_values(0).unique())
    print(f"  ✓ {len(valid_codes)} 只")

    # [2] 财务
    print(f"\n[2/5] 拉取财务数据...")
    fin_rows = []
    for code in tqdm(valid_codes, desc="  财务"):
        try:
            fd = fetcher._fetch_single_financial(code, close_price=close_prices.get(code))
            if fd is not None and len(fd) > 0:
                fin_rows.append(fd)
        except Exception:
            pass

    if not fin_rows:
        print("错误: 未拉取到财务数据")
        return

    financial_raw = pd.concat(fin_rows, ignore_index=True)
    # 只取每只股票最新一期
    financial_df = financial_raw.sort_values('report_date').groupby('code').last()
    print(f"  ✓ {len(financial_df)} 只有效财务数据")

    # [3] 日频指标
    print(f"\n[3/5] 整理日频指标...")
    daily_rows = []
    for code in valid_codes:
        row = {'code': code}
        if code in market_data.index.get_level_values(0):
            cm = market_data.loc[code].sort_index().iloc[-1]
            row['close'] = cm.get('close')
            row['is_suspended'] = int(cm.get('is_suspend', 0))
            row['is_st'] = int(cm.get('is_st', 0))

        if code in financial_df.index:
            lf = financial_df.loc[code]
            row['pe_ttm'] = safe_float(lf.get('pe_ttm'))
            row['pb'] = safe_float(lf.get('pb'))
            row['ps_ttm'] = safe_float(lf.get('ps_ttm'))
            row['total_mv'] = safe_float(lf.get('total_market_cap'))
            row['circ_mv'] = safe_float(lf.get('float_market_cap'))
            row['roe'] = safe_float(lf.get('roe'))
            row['roa'] = safe_float(lf.get('roa'))
            row['roic'] = safe_float(lf.get('roic'))
            row['gross_margin'] = safe_float(lf.get('gross_margin'))
            row['net_margin'] = safe_float(lf.get('net_margin'))
            row['debt_to_assets'] = safe_float(lf.get('asset_liability_ratio'))
        daily_rows.append(row)

    daily_df = pd.DataFrame(daily_rows).set_index('code')

    has_pe = daily_df['pe_ttm'].notna().sum()
    has_pb = daily_df['pb'].notna().sum()
    print(f"  ✓ PE:{has_pe}/{len(valid_codes)} PB:{has_pb}/{len(valid_codes)}")

    # [4] 因子
    print(f"\n[4/5] 计算因子...")
    factor_data = FactorData(
        trade_date=trade_date,
        market_data=market_data,
        daily_indicators=daily_df,
        financial_data=financial_df,
    )

    factor_names = strategy_cfg.get('factors', [])
    sort_orders = strategy_cfg.get('sort_orders', {})
    top_n = strategy_cfg.get('top_n', 20)

    scorer = FactorScorer(sort_orders=sort_orders)
    factor_values = scorer.compute_factors(factor_names, factor_data, daily_df.index)

    for fname in factor_names:
        fv = factor_values.get(fname)
        v = fv.notna().sum() if fv is not None else 0
        print(f"    {fname}: {v} 有效")

    # [5] 打分
    print(f"\n[5/5] 打分排名...")
    scored = scorer.score(factor_values)
    selected = scorer.select_top(scored, min(top_n, len(scored)))

    # 输出
    print(f"\n{'='*60}")
    print(f"  📊 选股结果 — {strategy_cfg['name']}")
    print(f"  日期: {trade_date}  |  因子: {', '.join(factor_names)}")
    print(f"{'='*60}")
    print(f"\n{'排名':<6} {'代码':<10} {'名称':<12} {'总分':>8}")
    print("-" * 40)

    name_map = {}
    try:
        sl = fetcher._retry_call(ak.stock_info_a_code_name)
        sl.columns = ['code', 'name']
        name_map = dict(zip(sl['code'], sl['name']))
    except:
        pass

    for i, code in enumerate(selected, 1):
        nm = name_map.get(code, '?')
        sc = scored.loc[code, 'total_score'] if code in scored.index else 0
        print(f"{i:<6} {code:<10} {nm:<12} {sc:>8.1f}")

    print(f"\n{'='*60}")
    print(f"  共选出 {len(selected)} 只股票")
    print(f"{'='*60}\n")


# =====================================================================
# 入口
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description='量化交易系统')
    
    # 顶级参数
    parser.add_argument('-s', '--strategy', type=str, default=None,
                        help='策略名称，配合 --live 使用')
    parser.add_argument('--live', action='store_true',
                        help='实时选股模式（AkShare直连，配合 -s 使用）')
    parser.add_argument('--start', type=str, default='20100101')
    parser.add_argument('--end', type=str, default=None)
    parser.add_argument('--test', type=int, default=None, help='测试N只股票')
    parser.add_argument('--skip-kline', action='store_true')
    parser.add_argument('--skip-financial', action='store_true')
    parser.add_argument('command', nargs='?', default=None,
                        choices=[None, 'fetch', 'report', 'run', 'backtest'],
                        help='子命令')
    
    args = parser.parse_args()
    
    # --live 模式优先
    if args.live or (args.strategy and args.command is None):
        cmd_screen(args)
        return
    
    if args.command == 'fetch':
        cmd_fetch(args)
    elif args.command == 'report':
        cmd_report(args)
    elif args.command == 'run':
        cmd_run(args)
    elif args.command == 'backtest':
        logger.info("回测功能将在第3-4周实现")
    else:
        parser.print_help()
        print("\n快速开始:")
        print("  python main.py fetch --test 10           # 测试10只股票")
        print("  python main.py fetch                     # 拉全量A股（约1-2小时）")
        print("  python main.py report                    # 数据质量报告")
        print("  python main.py run                       # 每日运行")
        print("  python main.py -s best_five_factor --live  # 实时选股")


if __name__ == '__main__':
    main()
