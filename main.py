#!/usr/bin/env python3
"""
量化交易系统 - 主入口

用法:
  python main.py --fetch              # 第1次运行：拉取全量数据
  python main.py --fetch --test 5     # 测试模式：只拉5只股票
  python main.py --report             # 查看数据质量报告
  python main.py --run                # 每日运行：更新数据→因子→打分→信号
  python main.py --backtest           # 回测模式

数据流:
  AkShare(网络) --fetch--> SQLite缓存 --CacheProvider--> 因子层 --> 筛选层 --> 输出
"""

import sys, os, logging, argparse, yaml
from datetime import date, datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.cache import DataCache
from data.akshare_provider import AkShareFetcher
from data.cache_provider import CacheProvider
from data.validator import validate_data

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
    fetcher = AkShareFetcher(max_retries=3, delay=0.3)
    
    try:
        end_date = args.end or datetime.now().strftime('%Y%m%d')
        stock_codes = None
        
        if args.test:
            n = int(args.test)
            # 测试模式：只拉取最具代表性的股票
            test_codes = [
                '600519', '000858', '000568',  # 白酒
                '600036', '601318',             # 金融
                '000333', '000651',             # 家电
                '300750', '002594',             # 新能源
                '600276', '300760',             # 医药
                '600900',                       # 电力
                '600585', '600887',             # 水泥/食品
                '002415', '000002',             # 科技/地产
            ][:n]
            stock_codes = test_codes
            logger.info(f"测试模式：只拉取 {len(stock_codes)} 只股票")
        
        fetcher.fetch_all(
            cache=cache,
            start_date=args.start or '20100101',
            end_date=end_date,
            stock_codes=stock_codes,
            skip_kline=args.skip_kline,
            skip_financial=args.skip_financial,
        )
        
        # 拉取完成后生成质量报告
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
        print(f"\n  【数据库概况】")
        print(f"  股票数量:      {stats.get('stock_info_rows', 0)}")
        print(f"  K线总条数:     {stats.get('daily_kline_rows', 0):,}")
        print(f"  K线日期范围:   {stats.get('kline_date_range', 'N/A')}")
        print(f"  K线覆盖股票:   {stats.get('kline_stock_count', 0)}")
        print(f"  财务数据条数:  {stats.get('financial_data_rows', 0):,}")
        print(f"  财务数据范围:  {stats.get('financial_date_range', 'N/A')}")
        
        import pandas as pd
        
        # K线抽样
        try:
            sample = pd.read_sql(
                "SELECT * FROM daily_kline WHERE code IN "
                "(SELECT code FROM daily_kline GROUP BY code ORDER BY RANDOM() LIMIT 3)",
                cache.conn
            )
            if len(sample) > 0:
                print(f"\n  【K线数据抽样】（3只股票，{len(sample)}条）")
                print(f"  收盘价范围: {sample['close'].min():.2f} ~ {sample['close'].max():.2f}")
                print(f"  日均成交量: {sample['volume'].mean():.0f}")
                nan_close = sample['close'].isna().sum()
                if nan_close > 0:
                    print(f"  ⚠ {nan_close}条收盘价为NaN")
                else:
                    print(f"  ✓ 无NaN收盘价")
        except Exception as e:
            print(f"  ⚠ K线抽样失败: {e}")
        
        # 财务数据抽样
        try:
            fsample = pd.read_sql(
                "SELECT code, report_date, pe_ttm, roe, gross_margin FROM financial_data "
                "WHERE pe_ttm IS NOT NULL LIMIT 10",
                cache.conn
            )
            if len(fsample) > 0:
                print(f"\n  【财务数据抽样】（{len(fsample)}条）")
                print(f"  PE范围:  {fsample['pe_ttm'].min():.1f} ~ {fsample['pe_ttm'].max():.1f}")
                print(f"  ROE范围: {fsample['roe'].min():.1f} ~ {fsample['roe'].max():.1f}")
        except Exception as e:
            print(f"  ⚠ 财务抽样失败: {e}")
        
        # 最近更新
        try:
            log = cache.get_data_log(limit=5)
            if len(log) > 0:
                print(f"\n  【最近更新记录】")
                for _, row in log.iterrows():
                    icon = '✓' if row['status'] == 'success' else '⚠'
                    print(f"  {icon} {row['data_type']}: {row['start_date']}~{row['end_date']} "
                           f"({row['record_count']}条)")
        except:
            pass
        
        print("\n" + "=" * 60)
        
    finally:
        cache.close()


# =====================================================================
# 每日运行：因子 → 打分 → 信号
# =====================================================================

def cmd_run(args):
    """
    每日运行模式：
    使用CacheProvider从SQLite读取数据，
    计算因子、打分排名、生成调仓信号。
    """
    cache_provider = CacheProvider(db_path='data/cache/quant.db')
    
    try:
        trade_date = date.today()
        logger.info(f"运行日期: {trade_date}")
        
        # ---- 1. 获取股票列表 ----
        stock_list = cache_provider.get_stock_list(trade_date)
        logger.info(f"全市场股票: {len(stock_list)} 只")
        
        # ---- 2. 构建股票池 ----
        from screening.universe import UniverseBuilder
        universe_builder = UniverseBuilder()
        
        # 获取当日指标用于过滤
        all_codes = stock_list.index.tolist() if hasattr(stock_list.index, 'tolist') else stock_list['code'].tolist()
        daily_indicators = cache_provider.get_daily_indicators(all_codes[:500], trade_date)  # 先取前500只测试
        
        universe = universe_builder.build(trade_date, stock_list, daily_indicators)
        logger.info(f"可投资股票池: {len(universe)} 只")
        
        # ---- 3. 加载因子数据 ----
        from factors.base import FactorData
        
        # 获取行情数据（过去1年，用于计算动量和波动率）
        start_date = trade_date - timedelta(days=365)
        market_data = cache_provider.get_market_data(
            list(universe)[:100], start_date, trade_date  # 测试：前100只
        )
        
        # 构建FactorData
        factor_data = FactorData(
            trade_date=trade_date,
            market_data=market_data,
            daily_indicators=daily_indicators,
            financial_data=cache_provider.get_financial_data(
                list(universe)[:100], trade_date
            ),
        )
        
        # ---- 4. 加载策略配置 ----
        with open('config/strategies.yaml', 'r') as f:
            config = yaml.safe_load(f)
        
        strategies = config.get('strategies', {})
        if not strategies:
            logger.warning("未配置任何策略，检查 config/strategies.yaml")
            return
        
        # ---- 5. 对每个策略打分 ----
        from screening.scorer import FactorScorer
        
        for strategy_key, strategy_cfg in strategies.items():
            logger.info(f"\n--- 策略: {strategy_cfg.get('name', strategy_key)} ---")
            
            factor_names = strategy_cfg.get('factors', [])
            sort_orders = strategy_cfg.get('sort_orders', {})
            top_n = strategy_cfg.get('top_n', 20)
            
            scorer = FactorScorer(sort_orders=sort_orders)
            factor_values = scorer.compute_factors(factor_names, factor_data, universe[:200])
            scored = scorer.score(factor_values)
            selected = scorer.select_top(scored, top_n)
            
            logger.info(f"  因子数: {len(factor_names)}")
            logger.info(f"  有效因子值: {len(factor_values)}")
            logger.info(f"  入选{top_n}只: {selected[:5]}..." if len(selected) > 5 else f"  入选: {selected}")
        
        logger.info("\n每日运行完成。")
        
    finally:
        cache_provider.close()


# =====================================================================
# 回测
# =====================================================================

def cmd_backtest(args):
    """回测模式（第3-4周完善）"""
    logger.info("回测功能将在第3周实现。")
    logger.info("当前可用: python main.py --fetch 拉取数据")
    logger.info("          python main.py --report 查看数据质量")


# =====================================================================
# 入口
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description='量化交易系统')
    sub = parser.add_subparsers(dest='cmd')
    
    # fetch
    p_fetch = sub.add_parser('fetch', help='拉取全量数据')
    p_fetch.add_argument('--start', type=str, default='20100101')
    p_fetch.add_argument('--end', type=str, default=None)
    p_fetch.add_argument('--test', type=int, default=None, help='测试模式：只拉取N只股票')
    p_fetch.add_argument('--skip-kline', action='store_true')
    p_fetch.add_argument('--skip-financial', action='store_true')
    
    # report
    sub.add_parser('report', help='数据质量报告')
    
    # run
    sub.add_parser('run', help='每日运行（因子+打分+信号）')
    
    # backtest
    sub.add_parser('backtest', help='回测')
    
    # 兼容旧参数
    parser.add_argument('--fetch', action='store_true', help='(兼容) 拉取数据')
    parser.add_argument('--report', action='store_true', help='(兼容) 数据质量报告')
    parser.add_argument('--run', action='store_true', help='(兼容) 每日运行')
    parser.add_argument('--backtest', action='store_true', help='(兼容) 回测')
    parser.add_argument('--start', type=str, default='20100101')
    parser.add_argument('--end', type=str, default=None)
    parser.add_argument('--test', type=int, default=None)
    parser.add_argument('--skip-kline', action='store_true')
    parser.add_argument('--skip-financial', action='store_true')
    
    args = parser.parse_args()
    
    # 兼容新旧参数
    if args.cmd == 'fetch' or args.fetch:
        cmd_fetch(args)
    elif args.cmd == 'report' or args.report:
        cmd_report(args)
    elif args.cmd == 'run' or args.run:
        cmd_run(args)
    elif args.cmd == 'backtest' or args.backtest:
        cmd_backtest(args)
    else:
        parser.print_help()
        print("\n快速开始:")
        print("  python main.py fetch --test 5   # 测试：拉5只股票")
        print("  python main.py fetch            # 拉全部A股数据")
        print("  python main.py report           # 查看数据质量")
        print("  python main.py run              # 每日运行（因子+打分）")


if __name__ == '__main__':
    main()
