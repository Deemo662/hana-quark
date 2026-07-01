"""
AkShare数据拉取工具

【白话说明】
这不是数据"提供者"（Provider），而是数据"搬运工"。
它负责从AkShare拉取数据，清洗后存入SQLite缓存。

之后因子层通过 CacheProvider 从SQLite读取数据，不再直接调用这个模块。

【数据流】
AkShare(网络) → 此模块拉取 → SQLite缓存 → CacheProvider → 因子层

【修复记录 2025-07-01】
- stock_zh_a_spot_em → stock_info_a_code_name（东方财富push2域名不通）
- stock_zh_a_hist → stock_zh_a_daily（改用sina源，后复权）
- stock_financial_analysis_indicator → stock_financial_abstract（改用可用的API）
- PE/PB/PS/市值由财务数据+收盘价自行计算
"""

import akshare as ak
import pandas as pd
import numpy as np
import time
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List
from tqdm import tqdm

from .cache import DataCache

logger = logging.getLogger(__name__)


class AkShareFetcher:
    """
    AkShare数据拉取器

    负责：从网络拉取A股行情和财务数据，清洗后存入SQLite。
    """

    def __init__(self, max_retries: int = 3, delay: float = 0.5):
        self.max_retries = max_retries
        self.delay = delay
        self.cache = None

    # ===================================================================
    # 工具方法
    # ===================================================================

    def _retry_call(self, func, *args, **kwargs):
        """带重试的API调用"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                result = func(*args, **kwargs)
                time.sleep(self.delay)
                return result
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(f"第{attempt+1}次调用失败: {e}，{wait}秒后重试...")
                time.sleep(wait)
        logger.error(f"重试{self.max_retries}次仍失败: {last_error}")
        raise last_error

    @staticmethod
    def _to_sina_symbol(code: str) -> str:
        """
        将纯数字代码转为 sina 格式

        '600519' → 'sh600519'
        '000001' → 'sz000001'
        '300750' → 'sz300750'
        """
        if code.startswith(('6', '9')):
            return f'sh{code}'
        return f'sz{code}'

    @staticmethod
    def _sf(value) -> Optional[float]:
        """安全转float"""
        if value is None:
            return None
        try:
            f = float(value)
            return None if np.isnan(f) or np.isinf(f) else f
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _fmt_date(val) -> str:
        """日期 → 'YYYYMMDD'"""
        if val is None:
            return ''
        if isinstance(val, (date, datetime)):
            return val.strftime('%Y%m%d')
        s = str(val).replace('-', '').replace('/', '').strip()
        return s[:8] if len(s) >= 8 else s

    @staticmethod
    def _est_disclosure_date(report_date: str) -> str:
        """
        估算财报披露日期（保守=法定截止日）

        年报(1231): 次年4月30日
        一季报(0331): 当年4月30日
        中报(0630): 当年8月31日
        三季报(0930): 当年10月31日
        """
        if not report_date or len(report_date) < 8:
            return ''
        try:
            year = int(report_date[:4])
            md = report_date[4:8]
            if md == '1231':
                return f'{year + 1}0430'
            elif md == '0331':
                return f'{year}0430'
            elif md == '0630':
                return f'{year}0831'
            elif md == '0930':
                return f'{year}1031'
            else:
                dt = datetime.strptime(report_date, '%Y%m%d') + timedelta(days=120)
                return dt.strftime('%Y%m%d')
        except:
            return ''

    # ===================================================================
    # 全量拉取
    # ===================================================================

    def fetch_all(
        self,
        cache: DataCache,
        start_date: str = '20100101',
        end_date: str = None,
        stock_codes: list = None,
        skip_kline: bool = False,
        skip_financial: bool = False,
    ):
        """拉取全量数据"""
        self.cache = cache

        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')

        logger.info("=" * 60)
        logger.info("  AkShare数据拉取")
        logger.info(f"  日期范围: {start_date} ~ {end_date}")
        logger.info("=" * 60)

        # 1. 股票列表
        logger.info("\n[1/4] 获取股票列表...")
        stock_list = self._fetch_stock_list()
        cache.save_stock_info(stock_list)
        cache.log_update('stock_info', '', '', len(stock_list))
        logger.info(f"  ✓ 共 {len(stock_list)} 只股票")

        if stock_codes is None:
            stock_codes = stock_list['code'].tolist()

        # 2. 交易日历
        logger.info("\n[2/4] 获取交易日历...")
        self._fetch_trade_calendar(cache, start_date, end_date)

        # 3. 日K线
        if not skip_kline:
            self._fetch_all_kline(cache, stock_codes, start_date, end_date)
        else:
            logger.info("\n[3/4] 跳过K线（已存在）")

        # 4. 财务数据
        if not skip_financial:
            self._fetch_all_financial(cache, stock_codes)
        else:
            logger.info("\n[4/4] 跳过财务数据（已存在）")

        logger.info("\n数据拉取完成！")
        cache.log_update('all', start_date, end_date, 0, 'success')

    # ===================================================================
    # 股票列表
    # ===================================================================

    def _fetch_stock_list(self) -> pd.DataFrame:
        """
        获取A股全量股票列表

        使用 stock_info_a_code_name（东方财富源，已验证可用）
        """
        df = self._retry_call(ak.stock_info_a_code_name)
        df.columns = ['code', 'name']

        df['exchange'] = df['code'].apply(
            lambda x: 'SH' if x.startswith(('6', '9'))
            else ('BJ' if x.startswith(('8', '4')) else 'SZ')
        )
        df['listed_date'] = None
        df['delisted_date'] = None
        df['industry'] = None

        return df

    # ===================================================================
    # 交易日历
    # ===================================================================

    def _fetch_trade_calendar(self, cache: DataCache, start: str, end: str):
        """获取交易日历"""
        try:
            cal = self._retry_call(ak.tool_trade_date_hist_sina)
            cal['trade_date'] = pd.to_datetime(cal['trade_date']).dt.strftime('%Y%m%d')
            cal = cal[(cal['trade_date'] >= start) & (cal['trade_date'] <= end)]
            cal['is_open'] = 1
            cache.save_trade_calendar(cal[['trade_date', 'is_open']])
            logger.info(f"  ✓ 共 {len(cal)} 个交易日")
        except Exception as e:
            logger.warning(f"  ⚠ 交易日历获取失败，使用简易日历: {e}")
            dates = pd.date_range(start=start, end=end, freq='B')
            cal = pd.DataFrame({
                'trade_date': dates.strftime('%Y%m%d'),
                'is_open': 1
            })
            cache.save_trade_calendar(cal)

    # ===================================================================
    # 日K线
    # ===================================================================

    def _fetch_all_kline(self, cache: DataCache, codes: list,
                         start: str, end: str):
        """
        拉取所有股票日K线

        使用 stock_zh_a_daily（sina源，后复权）
        """
        logger.info(f"\n[3/4] 获取日K线（{len(codes)} 只股票）...")
        logger.info("  ⚠ 每只约1-2秒，请耐心等待")

        total, errors = 0, 0

        for code in tqdm(codes, desc="  拉取K线"):
            try:
                df = self._fetch_single_kline(code, start, end)
                if len(df) > 0:
                    cache.save_daily_kline(df)
                    total += len(df)
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"  {code} 失败: {e}")

        cache.log_update('kline', start, end, total)
        logger.info(f"  ✓ K线: {total}条, 失败{errors}只")

    def _fetch_single_kline(self, code: str, start: str, end: str) -> pd.DataFrame:
        """
        拉取单只股票日K线

        改用 stock_zh_a_daily（sina源），因为 stock_zh_a_hist（东方财富push2）
        在当前环境下返回 ConnectionError。
        """
        sina_sym = self._to_sina_symbol(code)

        try:
            df = self._retry_call(
                ak.stock_zh_a_daily,
                symbol=sina_sym,
                adjust='hfq',  # ★ 后复权
            )
        except Exception as e:
            logger.debug(f"  {code} K线拉取失败: {e}")
            return pd.DataFrame()

        if df is None or len(df) == 0:
            return pd.DataFrame()

        # 统一字段名和格式
        df = df.rename(columns={'date': 'trade_date'})

        # 过滤日期范围
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        start_dt = pd.to_datetime(start)
        end_dt = pd.to_datetime(end)
        df = df[(df['trade_date'] >= start_dt) & (df['trade_date'] <= end_dt)]

        if len(df) == 0:
            return pd.DataFrame()

        df['trade_date'] = df['trade_date'].dt.strftime('%Y%m%d')

        # 添加必要字段
        df['code'] = code
        df['pre_close'] = df['close'].shift(1)
        df['is_st'] = 0
        df['is_suspend'] = (df['volume'] == 0).astype(int)

        # 确保 amount 存在
        if 'amount' not in df.columns or df['amount'].isna().all():
            df['amount'] = df['close'] * df['volume']

        # 修正 high < low
        bad = df['high'] < df['low']
        if bad.any():
            df.loc[bad, ['high', 'low']] = df.loc[bad, ['low', 'high']].values

        df.loc[df['close'].isna() | (df['close'] <= 0), 'close'] = np.nan

        return df[['code', 'trade_date', 'open', 'high', 'low', 'close',
                   'pre_close', 'volume', 'amount', 'is_st', 'is_suspend']]

    # ===================================================================
    # 财务数据
    # ===================================================================

    def _fetch_all_financial(self, cache: DataCache, codes: list):
        """
        拉取所有股票财务数据

        使用 stock_financial_abstract（已验证可用）
        从中提取各项财务指标，并计算 PE/PB/PS/市值。
        """
        logger.info(f"\n[4/4] 获取财务数据（{len(codes)} 只股票）...")
        logger.info("  ⚠ 每只约2-3秒")

        total, errors = 0, 0

        for code in tqdm(codes, desc="  拉取财务数据"):
            try:
                df = self._fetch_single_financial(code)
                if df is not None and len(df) > 0:
                    cache.save_financial_data(df)
                    total += len(df)
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"  {code} 失败: {e}")

        cache.log_update('financial', '', '', total)
        logger.info(f"  ✓ 财务数据: {total}条, 失败{errors}只")

    def _fetch_single_financial(self, code: str, close_price: float = None) -> pd.DataFrame:
        """
        从 stock_financial_abstract 提取财务指标

        该API一次返回所有历史报告期数据，格式为：
        - 行: 指标名（如'归母净利润'、'净资产收益率(ROE)'等）
        - 列: 报告期（如'20250331', '20241231'...）

        我们需要：
        1. 提取每个报告期的财务比率（ROE/ROA/毛利率等）
        2. 用累计净利润计算TTM，再结合最新收盘价算出PE/PB/PS/市值
        """
        try:
            fd = self._retry_call(ak.stock_financial_abstract, symbol=code)
        except Exception as e:
            logger.debug(f"  {code} 财务拉取失败: {e}")
            return pd.DataFrame()

        if fd is None or len(fd) == 0:
            return pd.DataFrame()

        # ---- 找出所有报告期列 ----
        # 列名如 '20250331', '20241231' 等
        report_cols = [c for c in fd.columns
                       if isinstance(c, str) and len(c) == 8 and c.isdigit()]
        if not report_cols:
            return pd.DataFrame()

        # ---- 索引关键指标 ----
        def _get_val(indicator_name: str, col: str):
            """从财务摘要中提取指定指标在指定报告期的值"""
            row = fd[fd['指标'] == indicator_name]
            if len(row) == 0:
                return None
            val = row.iloc[0].get(col)
            return self._sf(val)

        # ---- 逐报告期构建行 ----
        rows = []
        for col in report_cols:
            r = {
                'code': code,
                'report_date': col,
                'disclosure_date': self._est_disclosure_date(col),
            }

            # 基础财务比率（直接从API获取）
            r['roe'] = _get_val('净资产收益率(ROE)', col)
            r['roa'] = _get_val('总资产报酬率(ROA)', col)
            r['roic'] = _get_val('投入资本回报率', col)
            r['gross_margin'] = _get_val('毛利率', col)
            r['net_margin'] = _get_val('销售净利率', col)

            # 资产负债率
            debt = _get_val('资产负债率', col)
            if debt is not None:
                r['asset_liability_ratio'] = debt

            # 成长指标（同比需要比较去年同期，简化：填None）
            r['revenue_yoy'] = None
            r['net_profit_yoy'] = None
            r['op_profit_yoy'] = None

            # 每股数据（用于后续算PE/PB）
            eps = _get_val('基本每股收益', col)
            bvps = _get_val('每股净资产', col)
            net_profit = _get_val('归母净利润', col)
            revenue = _get_val('营业总收入', col)

            # ---- 计算PE/PB/PS（合并TTM估值）----
            # 用总股本作为桥梁：总股本 = 归母净利润 / EPS
            total_shares = None
            if eps and eps != 0 and net_profit:
                total_shares = net_profit / eps

            # 获取该报告期的收盘价来计算估值
            # 优先使用传入的close_price，否则从缓存中查找
            if close_price is None:
                close_price = self._get_close_price(code, col)

            if close_price and total_shares and total_shares > 0:
                market_cap = close_price * total_shares

                # PE_TTM: 用TTM净利润
                ttm_net_profit = self._compute_ttm(fd, '归母净利润', col)
                if ttm_net_profit and ttm_net_profit > 0:
                    r['pe_ttm'] = market_cap / ttm_net_profit

                # PB
                if bvps and bvps > 0:
                    r['pb'] = close_price / bvps

                # PS_TTM
                ttm_revenue = self._compute_ttm(fd, '营业总收入', col)
                if ttm_revenue and ttm_revenue > 0:
                    r['ps_ttm'] = market_cap / ttm_revenue

                # 市值
                r['total_market_cap'] = market_cap
                # 流通市值估算：没有精确数据时用总市值的70%
                r['float_market_cap'] = market_cap * 0.7
            else:
                r['pe_ttm'] = None
                r['pb'] = None
                r['ps_ttm'] = None
                r['total_market_cap'] = None
                r['float_market_cap'] = None

            # 现金流相关（stock_financial_abstract 不含这些）
            r['pcf_ttm'] = None
            r['dividend_yield'] = None
            r['ev_ebitda'] = None
            r['ocf_to_op'] = None
            r['sales_cash_to_revenue'] = None
            r['op_to_total_profit'] = None
            r['interest_coverage'] = None
            r['total_assets'] = None
            r['total_liabilities'] = None

            rows.append(r)

        return pd.DataFrame(rows)

    def _get_close_price(self, code: str, report_date: str) -> Optional[float]:
        """
        获取指定报告日期的收盘价

        优先从已缓存的K线查找，若无则返回None
        """
        if self.cache is None:
            return None
        try:
            kline = self.cache.get_kline(code, end_date=report_date)
            if kline is not None and len(kline) > 0:
                # 取报告日期前最近的收盘价
                return float(kline.iloc[-1]['close'])
        except Exception:
            pass
        return None

    def _compute_ttm(self, fd: pd.DataFrame, indicator: str,
                     base_col: str) -> Optional[float]:
        """
        计算TTM（过去4个季度滚动值）

        stock_financial_abstract 中的利润表数据是【年内累计】：
        - Q1 (0331): 1-3月累计
        - H1 (0630): 1-6月累计
        - 3Q (0930): 1-9月累计
        - FY (1231): 全年累计

        单季 = 本季累计 - 上季累计
        TTM = 最近4个单季之和

        base_col: 基准报告期，如'20250331'
        """
        row = fd[fd['指标'] == indicator]
        if len(row) == 0:
            return None

        # 所有可用报告期（按时间排序）
        all_cols = sorted(
            [c for c in fd.columns
             if isinstance(c, str) and len(c) == 8 and c.isdigit()],
            reverse=True
        )

        values = {}  # {col: float_value}
        for c in all_cols:
            v = row.iloc[0].get(c)
            fv = self._sf(v)
            if fv is not None:
                values[c] = fv

        if base_col not in values:
            return None

        # 收集基准及其之前至少4个季度的数据
        # 先构建需要的季度列表
        quarters_needed = self._get_prev_quarters(base_col, 4)
        available_quarters = sorted(values.keys())

        standalone = {}
        for q in quarters_needed:
            if q not in values:
                continue
            cumulative = values[q]
            # 找前一季度
            prev_q = self._prev_quarter_in_year(q)
            if prev_q and prev_q in values:
                prev_cum = values[prev_q]
                standalone[q] = cumulative - prev_cum
            else:
                # 如果是Q1（或无法找前一季度），就是单季值本身
                standalone[q] = cumulative

        if len(standalone) < 4:
            return None

        # 取最近4个季度求和
        sorted_quarters = sorted(standalone.keys())
        last_four = sorted_quarters[-4:]
        return sum(standalone[q] for q in last_four)

    @staticmethod
    def _get_prev_quarters(base: str, n: int) -> list:
        """
        获取base及其之前的n个季度

        '20250331' → ['20250331', '20241231', '20240930', '20240630']
        """
        year = int(base[:4])
        md = base[4:]

        quarters_map = {
            '0331': (year, '0331'),
            '0630': (year, '0331'),
            '0930': (year, '0331'),
            '1231': (year, '0331'),
        }

        # 从base开始，按季度倒退
        all_dates = []
        cur_year = year

        # 确定base对应的年末月份
        base_month = {'0331': 3, '0630': 6, '0930': 9, '1231': 12}.get(md, 3)

        # 生成季度日期序列
        y, m = cur_year, base_month
        for _ in range(n):
            m_str = f'{m:02d}'
            if m == 3:
                d = f'{y}0331'
            elif m == 6:
                d = f'{y}0630'
            elif m == 9:
                d = f'{y}0930'
            else:
                d = f'{y}1231'
            all_dates.append(d)

            # 倒退一个季度
            if m == 3:
                m = 12
                y -= 1
            else:
                m -= 3

        return all_dates

    @staticmethod
    def _prev_quarter_in_year(q: str) -> Optional[str]:
        """
        同一年内前一季度

        '20250630' → '20250331'
        '20250331' → None（Q1没有同年前一季度）
        '20251231' → '20250930'
        """
        md = q[4:]
        if md == '0331':
            return None  # Q1无前季
        elif md == '0630':
            return q[:4] + '0331'
        elif md == '0930':
            return q[:4] + '0630'
        elif md == '1231':
            return q[:4] + '0930'
        return None
