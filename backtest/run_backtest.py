#!/usr/bin/env python3
"""
回测运行脚本

端到端验证：
  1. MockProvider 生成模拟行情+财务数据
  2. 策略筛选层计算因子+打分+选股
  3. Backtrader 回测引擎执行月度调仓
  4. 输出完整绩效报告

用法:
  python backtest/run_backtest.py                    # 默认运行 pb_lowvol
  python backtest/run_backtest.py --strategy roe_lowvol
  python backtest/run_backtest.py --list              # 列出可用策略
  python backtest/run_backtest.py --years 5 --top_n 20
"""
import sys
import os
import argparse
import logging
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.mock_provider import MockProvider
from factors.base import FactorData
from screening.scorer import FactorScorer
from screening.universe import UniverseBuilder
from backtest.engine import BacktestEngine, print_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_strategy_config(strategy_name: str) -> dict:
    """加载策略配置"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "strategies.yaml"
    )
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    strategies = config.get("strategies", {})
    if strategy_name not in strategies:
        available = list(strategies.keys())
        raise ValueError(f"策略 '{strategy_name}' 不存在。可用: {available}")

    return strategies[strategy_name]


def list_strategies():
    """列出所有可用策略"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "strategies.yaml"
    )
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    print("\n可用策略:")
    print("-" * 70)
    for key, s in config.get("strategies", {}).items():
        book_cagr = s.get("book_cagr_20", "?")
        print(f"  {key:<30s}  {s['name']:<30s}  书中年化: {book_cagr}%")
    print("-" * 70)
    print()


def get_month_end_dates(start: date, end: date) -> list[date]:
    """获取区间内每个月的最后一个日历日"""
    dates = []
    current = start.replace(day=1)
    while current <= end:
        # 当月最后一天
        next_month = current + relativedelta(months=1)
        month_end = next_month - timedelta(days=1)
        if month_end >= start and month_end <= end:
            dates.append(month_end)
        current = next_month
    return dates


def get_last_trading_day(dt: date) -> date:
    """回退到最近的非周末日期（简化版，不处理假期）"""
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt


def generate_holdings(
    provider: MockProvider,
    strategy_cfg: dict,
    price_data: pd.DataFrame,
    start: date,
    end: date,
    top_n: int = 20,
) -> dict[str, list[str]]:
    """
    生成每月持仓快照

    对每个月末：
      1. 获取当天估值+财务数据
      2. 构建股票池
      3. 计算因子
      4. 打分排序选top N

    Returns:
      { "YYYY-MM-DD": [code1, code2, ...] }
    """
    factor_names = strategy_cfg["factors"]
    sort_orders = strategy_cfg.get("sort_orders", {})
    weights = strategy_cfg.get("weights", "equal")
    if weights == "equal":
        weights = None  # scorer 默认等权

    scorer = FactorScorer(sort_orders=sort_orders)
    universe_builder = UniverseBuilder()

    month_ends = get_month_end_dates(start, end)
    logger.info(f"生成 {len(month_ends)} 个月持仓快照 "
                f"({month_ends[0]} ~ {month_ends[-1]})...")

    holdings = {}
    codes_all = list(provider.STOCKS.keys())

    for i, me in enumerate(month_ends):
        trade_dt = get_last_trading_day(me)
        date_key = trade_dt.strftime("%Y-%m-%d")

        # 1. 获取当日估值+财务指标
        indicators = provider.get_daily_indicators(codes_all, trade_dt)
        financial = provider.get_financial_data(codes_all, trade_dt)

        # 2. 构建股票池
        stock_list = provider.get_stock_list(trade_dt)
        universe = universe_builder.build(trade_dt, stock_list, indicators)

        # 3. 行情数据：取最近250个交易日用于因子计算（动量+波动率需足够历史）
        lookback = trade_dt - timedelta(days=365)
        market_slice = price_data.loc[
            price_data.index.get_level_values(1) <= trade_dt
        ]
        market_slice = market_slice.loc[
            market_slice.index.get_level_values(1) >= lookback
        ]

        # 4. 构建 FactorData
        factor_data = FactorData(
            trade_date=trade_dt,
            market_data=market_slice,
            daily_indicators=indicators,
            financial_data=financial,
        )

        # 5. 计算因子
        factor_values = scorer.compute_factors(factor_names, factor_data, universe)

        if not factor_values:
            logger.warning(f"  {date_key}: 无有效因子值，跳过")
            continue

        # 6. 打分排序
        scored = scorer.score(factor_values, weights)
        selected = scorer.select_top(scored, top_n=min(top_n, len(scored)))

        holdings[date_key] = selected

        if (i + 1) % 6 == 0:
            logger.info(f"  [{i+1}/{len(month_ends)}] {date_key}: "
                        f"选股 {len(selected)} 只, "
                        f"top3: {selected[:3]}")

    logger.info(f"生成完成: {len(holdings)} 个月有持仓")
    return holdings


def run_backtest(
    strategy_name: str = "pb_lowvol",
    years: int = 4,
    top_n: int = 20,
    initial_capital: float = 100_000,
):
    """
    运行完整的回测流程
    """
    strategy_cfg = load_strategy_config(strategy_name)
    logger.info(f"策略: {strategy_cfg['name']}")
    logger.info(f"因子: {strategy_cfg['factors']}")
    logger.info(f"书中年化: {strategy_cfg.get('book_cagr_20', '?')}% (20只)")

    # ============================================================
    # Step 1: 生成模拟数据
    # ============================================================
    provider = MockProvider()

    end_date = date(2022, 12, 31)
    lookback_start = date(end_date.year - years - 1, 1, 1)  # 多1年用于因子计算
    backtest_start = date(end_date.year - years, 1, 1)

    logger.info(f"数据区间: {lookback_start} ~ {end_date}")
    logger.info(f"回测区间: {backtest_start} ~ {end_date}")

    codes_all = list(provider.STOCKS.keys())
    logger.info(f"股票数量: {len(codes_all)}")

    price_data = provider.get_market_data(codes_all, lookback_start, end_date)
    logger.info(f"行情数据: {len(price_data)} 条")

    # ============================================================
    # Step 2: 生成每月持仓
    # ============================================================
    holdings = generate_holdings(
        provider=provider,
        strategy_cfg=strategy_cfg,
        price_data=price_data,
        start=backtest_start,
        end=end_date,
        top_n=top_n,
    )

    # ============================================================
    # Step 3: 裁剪行情数据到回测区间（仅用于回测引擎需要的股票）
    # ============================================================
    required_codes = set()
    for codes in holdings.values():
        required_codes.update(codes)
    logger.info(f"回测覆盖 {len(required_codes)} 只股票")

    bt_price_data = price_data.loc[
        price_data.index.get_level_values(0).isin(required_codes)
    ].copy()
    bt_price_data = bt_price_data.loc[
        bt_price_data.index.get_level_values(1) >= backtest_start
    ]
    logger.info(f"回测行情数据: {len(bt_price_data)} 条")

    # ============================================================
    # Step 4: 运行回测
    # ============================================================
    engine = BacktestEngine(
        initial_capital=initial_capital,
        commission=0.00025,
        stamp_duty=0.0005,
        slippage=0.001,
        risk_free_rate=0.03,
    )

    logger.info("启动回测引擎...")
    result = engine.run(
        strategy_name=strategy_cfg["name"],
        price_data=bt_price_data,
        holdings=holdings,
    )

    # ============================================================
    # Step 5: 输出报告
    # ============================================================
    print_report(result)

    # 与书中数据对照
    book_cagr_20 = strategy_cfg.get("book_cagr_20")
    book_cagr_40 = strategy_cfg.get("book_cagr_40")
    if book_cagr_20:
        print(f"[对照] 书中年化(20只): {book_cagr_20}%")
        print(f"[对照] 模拟年化(20只): {result.cagr:.2f}%")
        diff = abs(result.cagr - book_cagr_20)
        print(f"[对照] 偏差: {diff:.2f}%")
        if diff < 3:
            print(f"[对照] ✓ 偏差在可接受范围内(<3%)")
        else:
            print(f"[对照] ⚠ 偏差较大，但Mock数据随机，属预期范围")

    if book_cagr_40:
        print(f"[对照] 书中年化(40只): {book_cagr_40}%")

    print()
    print("注意: Mock数据使用伪随机数生成，回测结果不会等于书中真实数据。")
    print("      本次验证重点：回测框架的计算逻辑和输出格式是否正确。")
    print()

    return result


def main():
    parser = argparse.ArgumentParser(description="量化策略回测验证")
    parser.add_argument("--strategy", type=str, default="pb_lowvol",
                        help="策略名称 (默认: pb_lowvol)")
    parser.add_argument("--list", action="store_true",
                        help="列出所有可用策略")
    parser.add_argument("--years", type=int, default=4,
                        help="回测年数 (默认: 4)")
    parser.add_argument("--top_n", type=int, default=20,
                        help="持仓数量 (默认: 20)")
    parser.add_argument("--capital", type=float, default=100_000,
                        help="初始资金 (默认: 100000)")
    args = parser.parse_args()

    if args.list:
        list_strategies()
        return

    run_backtest(
        strategy_name=args.strategy,
        years=args.years,
        top_n=args.top_n,
        initial_capital=args.capital,
    )


if __name__ == "__main__":
    main()
