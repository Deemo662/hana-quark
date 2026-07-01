"""
Baostock数据拉取器

【白话说明】
Baostock是专门为A股量化设计的免费数据源，无需注册。
相比AkShare，Baostock的优势：
1. 日K线自带PE/PB/PS/PCF估值指标（不用单独拉取）
2. 有完整的季度财务数据（ROE/ROA/毛利率等）
3. 网络兼容性好（从当前环境能正常连接）
4. 支持复权价格

【数据来源】http://baostock.com
【许可证】免费，可用于学术和研究
"""

import baostock as bs
import pandas as pd
import numpy as np
import time
import logging
import threading
from datetime import date, datetime, timedelta
from typing import Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from .cache import DataCache

logger = logging.getLogger(__name__)

# 建议线程数：Baostock是网络IO密集型，10线程能显著加速
DEFAULT_WORKERS = 10


class BaostockFetcher:
    """
    Baostock数据拉取器
    
    负责从Baostock拉取A股行情和财务数据，清洗后存入SQLite。
    """
    
    # Baostock字段映射：baostock字段 → 我们的字段
    KLINE_FIELDS = "date,open,high,low,close,preclose,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
    
    def __init__(self):
        self.logged_in = False
    
    def login(self):
        """登录Baostock（必须在使用前调用）"""
        if not self.logged_in:
            lg = bs.login()
            if lg.error_code != '0':
                raise ConnectionError(f"Baostock登录失败: {lg.error_msg}")
            self.logged_in = True
            logger.info("Baostock登录成功")
    
    def logout(self):
        """登出"""
        if self.logged_in:
            bs.logout()
            self.logged_in = False
    
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
        """
        拉取全量数据
        
        Args:
            cache: SQLite缓存实例
            start_date: 起始日期 'YYYYMMDD'
            end_date: 结束日期（默认今天）
            stock_codes: 指定股票代码（None=全部A股）
        """
        self.login()
        
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        logger.info("=" * 60)
        logger.info("  Baostock数据拉取")
        logger.info(f"  日期范围: {start_date} ~ {end_date}")
        logger.info("=" * 60)
        
        try:
            # ---- 1. 股票列表 ----
            logger.info("\n[1/3] 获取股票列表...")
            stock_list = self._fetch_stock_list()
            
            # 转换格式以匹配cache.py的期望
            stock_info = stock_list[['code', 'code_name', 'ipoDate', 'outDate', 'type']].copy()
            stock_info.columns = ['code', 'name', 'listed_date', 'delisted_date', 'stock_type']
            stock_info['exchange'] = stock_info['code'].apply(
                lambda x: 'SH' if x.startswith('sh.') else ('SZ' if x.startswith('sz.') else 'BJ')
            )
            stock_info['code'] = stock_info['code'].str.replace('sh.', '').str.replace('sz.', '').str.replace('bj.', '')
            stock_info['listed_date'] = stock_info['listed_date'].str.replace('-', '')
            stock_info['delisted_date'] = stock_info['delisted_date'].replace('', None)
            stock_info['industry'] = None
            stock_info['is_st'] = 0
            
            cache.save_stock_info(stock_info)
            cache.log_update('stock_info', '', '', len(stock_info))
            logger.info(f"  ✓ 共 {len(stock_info)} 只股票（含已退市）")
            
            if stock_codes is None:
                # 只取沪深两市A股（排除B股、北交所等）
                stock_codes = stock_info[
                    (stock_info['stock_type'] == '1') &  # 1=股票
                    (stock_info['exchange'].isin(['SH', 'SZ']))
                ]['code'].tolist()
                logger.info(f"  沪深A股: {len(stock_codes)} 只")
            
            # ---- 2. 日K线 + 估值指标 ----
            if not skip_kline:
                self._fetch_all_kline(cache, stock_codes, start_date, end_date)
            else:
                logger.info("\n[2/3] 跳过K线（已存在）")
            
            # ---- 3. 财务数据 ----
            if not skip_financial:
                self._fetch_all_financial(cache, stock_codes)
            else:
                logger.info("\n[3/3] 跳过财务数据（已存在）")
            
            logger.info("\n数据拉取完成！")
            
        finally:
            self.logout()
    
    # ===================================================================
    # 股票列表
    # ===================================================================
    
    def _fetch_stock_list(self) -> pd.DataFrame:
        """获取全部股票列表（含已退市）"""
        rs = bs.query_stock_basic()
        
        rows = []
        while (rs.error_code == '0') & rs.next():
            rows.append(rs.get_row_data())
        
        df = pd.DataFrame(rows, columns=rs.fields)
        logger.info(f"  Baostock返回: {len(df)} 条（含B股、债券等）")
        
        return df
    
    # ===================================================================
    # 日K线（多线程）
    # ===================================================================
    
    def _fetch_all_kline(self, cache: DataCache, codes: list, start: str, end: str):
        """多线程拉取日K线+估值指标"""
        n_workers = min(DEFAULT_WORKERS, len(codes))
        logger.info(f"\n[2/3] 获取日K线+估值指标（{len(codes)} 只, {n_workers}线程）...")
        logger.info("  ⚠ 预计10-30分钟（取决于股票数量）")
        
        start_bs = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_bs = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        
        kline_total, kline_errors = 0, 0
        fin_rows = []
        write_lock = threading.Lock()
        
        def fetch_one(code):
            """单个worker：拉取一只股票的K线（线程内独立login/logout）"""
            bs.login()
            try:
                bs_code = self._to_bs_code(code)
                kline_df, fin_df = self._fetch_single_kline(bs_code, code, start_bs, end_bs)
                return code, kline_df, fin_df, None
            except Exception as e:
                return code, pd.DataFrame(), pd.DataFrame(), str(e)
            finally:
                bs.logout()
        
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {executor.submit(fetch_one, code): code for code in codes}
            
            with tqdm(total=len(codes), desc="  拉取K线") as pbar:
                for future in as_completed(futures):
                    code, kline_df, fin_df, error = future.result()
                    
                    if error:
                        kline_errors += 1
                        if kline_errors <= 5:
                            logger.warning(f"  {code} 失败: {error}")
                    else:
                        with write_lock:
                            if len(kline_df) > 0:
                                cache.save_daily_kline(kline_df)
                                kline_total += len(kline_df)
                            if len(fin_df) > 0:
                                fin_rows.append(fin_df)
                    
                    pbar.update(1)
        
        # 保存估值快照
        if fin_rows:
            all_fin = pd.concat(fin_rows, ignore_index=True)
            cache.save_financial_data(all_fin)
            logger.info(f"    估值快照: {len(all_fin)} 条")
        
        cache.log_update('kline', start, end, kline_total)
        logger.info(f"  ✓ K线: {kline_total}条, 失败{kline_errors}只")
    
    def _fetch_single_kline(self, bs_code: str, raw_code: str, start: str, end: str):
        """
        拉取单只股票日K线
        
        Baostock返回的字段:
        date, open, high, low, close, preclose, volume, amount,
        turn(换手率%), peTTM, pbMRQ, psTTM, pcfNcfTTM, isST
        
        Returns:
            (kline_df, fin_snapshot_df)
        """
        rs = bs.query_history_k_data_plus(
            bs_code,
            self.KLINE_FIELDS,
            start_date=start, end_date=end,
            frequency="d", adjustflag="2"  # 2=前复权
        )
        
        rows = []
        while (rs.error_code == '0') & rs.next():
            rows.append(rs.get_row_data())
        
        if not rows:
            return pd.DataFrame(), pd.DataFrame()
        
        df = pd.DataFrame(rows, columns=rs.fields)
        
        # ---- 转换K线数据 ----
        # ★从df直接构建，避免空DataFrame导致的NaN问题
        n = len(df)
        kline = pd.DataFrame({
            'code': [raw_code] * n,
            'trade_date': df['date'].str.replace('-', ''),
            'open': pd.to_numeric(df['open'], errors='coerce'),
            'high': pd.to_numeric(df['high'], errors='coerce'),
            'low': pd.to_numeric(df['low'], errors='coerce'),
            'close': pd.to_numeric(df['close'], errors='coerce'),
            'pre_close': pd.to_numeric(df['preclose'], errors='coerce'),
            'volume': pd.to_numeric(df['volume'], errors='coerce'),
            'amount': pd.to_numeric(df['amount'], errors='coerce'),
            'turnover': pd.to_numeric(df['turn'], errors='coerce'),
            'is_suspend': (pd.to_numeric(df['volume'], errors='coerce') == 0).astype(int),
            'is_st': (df['isST'] == '1').astype(int),
        })
        
        # 过滤NaN收盘价
        kline = kline[kline['close'].notna() & (kline['close'] > 0)]
        
        # ---- 构建估值快照（存financial_data表） ----
        # 取最新一条作为估值快照
        fin = pd.DataFrame()
        latest = df.iloc[-1] if len(df) > 0 else None
        
        if latest is not None:
            fin['code'] = [raw_code]
            fin['report_date'] = [latest['date'].replace('-', '')]
            
            # 估值指标（直接从K线数据获取！Baostock的一大优势）
            fin['pe_ttm'] = [self._sf(latest.get('peTTM'))]
            fin['pb'] = [self._sf(latest.get('pbMRQ'))]
            fin['ps_ttm'] = [self._sf(latest.get('psTTM'))]
            fin['pcf_ttm'] = [self._sf(latest.get('pcfNcfTTM'))]
            
            # 市值需要从 amount/volume 反推或其他接口获取
            # Baostock的K线数据不直接提供市值
            fin['total_market_cap'] = [None]
            fin['float_market_cap'] = [None]
            
            # ROC指标（K线不提供，需要单独从财务接口获取）
            fin['roe'] = [None]
            fin['roa'] = [None]
            fin['roic'] = [None]
            fin['gross_margin'] = [None]
            fin['net_margin'] = [None]
            fin['revenue_yoy'] = [None]
            fin['net_profit_yoy'] = [None]
            fin['dividend_yield'] = [None]
            fin['ev_ebitda'] = [None]
            fin['asset_liability_ratio'] = [None]
            fin['ocf_to_op'] = [None]
            fin['sales_cash_to_revenue'] = [None]
            fin['op_to_total_profit'] = [None]
            fin['interest_coverage'] = [None]
            fin['ev2sales'] = [None]
            fin['equity_to_debt'] = [None]
            fin['disclosure_date'] = [latest['date'].replace('-', '')]
        
        return kline, fin
    
    # ===================================================================
    # 财务数据（季报，多线程）
    # ===================================================================
    
    def _fetch_all_financial(self, cache: DataCache, codes: list):
        """多线程拉取季报财务数据"""
        n_workers = min(DEFAULT_WORKERS, len(codes))
        logger.info(f"\n[3/3] 获取季报财务数据（{len(codes)} 只, {n_workers}线程）...")
        logger.info("  ⚠ 预计30分钟~2小时（取决于股票数量）")
        
        total, errors = 0, 0
        write_lock = threading.Lock()
        
        def fetch_one(code):
            """单个worker：拉取一只股票所有季报"""
            bs.login()
            try:
                df = self._fetch_single_financial(code)
                return code, df, None
            except Exception as e:
                return code, pd.DataFrame(), str(e)
            finally:
                bs.logout()
        
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {executor.submit(fetch_one, code): code for code in codes}
            
            with tqdm(total=len(codes), desc="  拉取财务数据") as pbar:
                for future in as_completed(futures):
                    code, df, error = future.result()
                    
                    if error:
                        errors += 1
                        if errors <= 5:
                            logger.warning(f"  {code} 失败: {error}")
                    elif len(df) > 0:
                        with write_lock:
                            cache.save_financial_data(df)
                            total += len(df)
                    
                    pbar.update(1)
        
        cache.log_update('financial', '', '', total)
        logger.info(f"  ✓ 财务数据: {total}条, 失败{errors}只")
    
    def _fetch_single_financial(self, code: str) -> pd.DataFrame:
        """
        拉取单只股票所有可用的季报数据
        
        Baostock提供三个财务接口:
        1. query_profit_data() - 利润表（ROE, ROA, 毛利率, 营收, 净利润等）
        2. query_balance_data() - 资产负债表（资产/负债）
        3. query_cash_flow_data() - 现金流量表
        
        我们合并三个接口的数据。
        """
        bs_code = self._to_bs_code(code)
        rows = []
        
        # ---- 利润表 ----
        for year in range(2010, 2027):  # 2010-2026
            for q in range(1, 5):
                try:
                    rs = bs.query_profit_data(code=bs_code, year=year, quarter=q)
                    while (rs.error_code == '0') & rs.next():
                        row_data = rs.get_row_data()
                        row = {
                            'code': code,
                            'report_date': self._fmt_report_date(row_data[2]),
                            'disclosure_date': row_data[1].replace('-', '') if len(row_data) > 1 else '',
                            # 利润表指标
                            'roe': self._sf(row_data[5]) if len(row_data) > 5 else None,
                            'roa': self._sf(row_data[6]) if len(row_data) > 6 else None,
                            'gross_margin': self._sf(row_data[8]) if len(row_data) > 8 else None,  # 销售毛利率
                            'net_margin': self._sf(row_data[7]) if len(row_data) > 7 else None,  # 销售净利率
                            'revenue_yoy': self._sf(row_data[9]) if len(row_data) > 9 else None,  # 营收同比
                            'net_profit_yoy': self._sf(row_data[10]) if len(row_data) > 10 else None,  # 净利同比
                        }
                        rows.append(row)
                except:
                    continue
        
        if not rows:
            return pd.DataFrame()
        
        return pd.DataFrame(rows)
    
    # ===================================================================
    # 辅助方法
    # ===================================================================
    
    def _to_bs_code(self, code: str) -> str:
        """将6位代码转为Baostock格式：000001 → sz.000001"""
        code = code.replace('sh.', '').replace('sz.', '').replace('bj.', '')
        if code.startswith(('6', '9')):
            return f"sh.{code}"
        elif code.startswith(('8', '4')):
            return f"bj.{code}"
        else:
            return f"sz.{code}"
    
    def _fmt_report_date(self, date_str: str) -> str:
        """格式化报告期日期"""
        if not date_str:
            return ''
        return date_str.replace('-', '')
    
    def _sf(self, value) -> Optional[float]:
        """安全转float，空字符串→None"""
        if value is None or value == '':
            return None
        try:
            f = float(value)
            return None if np.isnan(f) or np.isinf(f) else f
        except (ValueError, TypeError):
            return None
