"""
Baostock数据拉取器（可靠顺序版）

Baostock模块不支持多线程（全局连接冲突），采用顺序拉取。
K线约1-2秒/只，财务数据约30秒/只（查询多年季报）。
"""

import baostock as bs
import pandas as pd
import numpy as np
import time
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List
from tqdm import tqdm

from .cache import DataCache

logger = logging.getLogger(__name__)

KLINE_FIELDS = "date,open,high,low,close,preclose,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"


class BaostockFetcher:
    """Baostock数据拉取器（顺序执行，稳定可靠）"""
    
    def login(self):
        lg = bs.login()
        if lg.error_code != '0':
            raise ConnectionError(f"Baostock登录失败: {lg.error_msg}")
        logger.info("Baostock登录成功")
    
    def logout(self):
        bs.logout()
    
    # ===================================================================
    # 全量拉取
    # ===================================================================
    
    def fetch_all(self, cache: DataCache, start_date='20100101', end_date=None,
                  stock_codes=None, skip_kline=False, skip_financial=False):
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        self.login()
        
        try:
            logger.info("=" * 60)
            logger.info(f"  数据拉取: {start_date} ~ {end_date}")
            logger.info("=" * 60)
            
            # 1. 股票列表
            logger.info("\n[1/3] 股票列表...")
            stock_info = self._fetch_stock_list()
            cache.save_stock_info(stock_info)
            cache.log_update('stock_info', '', '', len(stock_info))
            logger.info(f"  ✓ {len(stock_info)} 只")
            
            if stock_codes is None:
                stock_codes = stock_info[
                    (stock_info['stock_type'] == '1') &
                    (stock_info['exchange'].isin(['SH', 'SZ']))
                ]['code'].tolist()
                logger.info(f"  沪深A股: {len(stock_codes)} 只")
            
            # 2. K线
            if not skip_kline:
                self._fetch_all_kline(cache, stock_codes, start_date, end_date)
            else:
                logger.info("\n[2/3] 跳过K线")
            
            # 3. 财务
            if not skip_financial:
                self._fetch_all_financial(cache, stock_codes)
            else:
                logger.info("\n[3/3] 跳过财务数据")
            
            logger.info("\n✓ 数据拉取完成！")
        finally:
            self.logout()
    
    # ===================================================================
    # 股票列表
    # ===================================================================
    
    def _fetch_stock_list(self) -> pd.DataFrame:
        rs = bs.query_stock_basic()
        rows = []
        while (rs.error_code == '0') & rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        
        # 转换格式
        info = df[['code', 'code_name', 'ipoDate', 'outDate', 'type']].copy()
        info.columns = ['code', 'name', 'listed_date', 'delisted_date', 'stock_type']
        info['code'] = info['code'].str.replace('sh.','').str.replace('sz.','').str.replace('bj.','')
        info['listed_date'] = info['listed_date'].str.replace('-','')
        info['delisted_date'] = info['delisted_date'].replace('', None)
        info['exchange'] = info['code'].apply(
            lambda x: 'SH' if x.startswith(('6','9')) else ('BJ' if x.startswith(('8','4')) else 'SZ')
        )
        info['industry'] = None
        return info
    
    # ===================================================================
    # 日K线
    # ===================================================================
    
    def _fetch_all_kline(self, cache: DataCache, codes: list, start: str, end: str):
        start_bs = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_bs = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        
        logger.info(f"\n[2/3] 日K线+估值（{len(codes)}只）...")
        logger.info(f"  ⚠ 预计{len(codes)*1.8/3600:.1f}小时")
        
        total, errors = 0, 0
        kline_batch, fin_batch = [], []
        BATCH_SIZE = 100  # 每100只批量写入一次
        
        for i, code in enumerate(tqdm(codes, desc="  拉取K线")):
            try:
                bs_code = self._to_bs(code)
                kdf, fdf = self._fetch_one_kline(bs_code, code, start_bs, end_bs)
                if len(kdf) > 0:
                    kline_batch.append(kdf)
                    total += len(kdf)
                if len(fdf) > 0:
                    fin_batch.append(fdf)
            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"  {code} 失败: {e}")
            
            # 批量写入（避免内存爆炸）
            if len(kline_batch) >= BATCH_SIZE:
                big = pd.concat(kline_batch, ignore_index=True)
                cache.save_daily_kline(big)
                kline_batch = []
            if len(fin_batch) >= BATCH_SIZE:
                big = pd.concat(fin_batch, ignore_index=True)
                self._safe_save_financial(cache, big)
                fin_batch = []
        
        # 写入剩余
        if kline_batch:
            cache.save_daily_kline(pd.concat(kline_batch, ignore_index=True))
        if fin_batch:
            self._safe_save_financial(cache, pd.concat(fin_batch, ignore_index=True))
        
        cache.log_update('kline', start, end, total)
        logger.info(f"  ✓ K线: {total}条, 失败{errors}只")
    
    def _fetch_one_kline(self, bs_code, raw_code, start, end):
        """拉取一只股票K线"""
        rs = bs.query_history_k_data_plus(
            bs_code, KLINE_FIELDS,
            start_date=start, end_date=end,
            frequency="d", adjustflag="2"
        )
        rows = []
        while (rs.error_code == '0') & rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame(), pd.DataFrame()
        
        df = pd.DataFrame(rows, columns=rs.fields)
        n = len(df)
        
        # K线
        kline = pd.DataFrame({
            'code': [raw_code]*n,
            'trade_date': df['date'].str.replace('-',''),
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
        kline = kline[kline['close'].notna() & (kline['close'] > 0)]
        
        # 估值快照（只取最新的PE/PB/PS）
        fin = pd.DataFrame({
            'code': [raw_code],
            'report_date': [df['date'].iloc[-1].replace('-','') if len(df)>0 else ''],
            'disclosure_date': [df['date'].iloc[-1].replace('-','') if len(df)>0 else ''],
            'pe_ttm': [self._sf(df['peTTM'].iloc[-1]) if len(df)>0 else None],
            'pb': [self._sf(df['pbMRQ'].iloc[-1]) if len(df)>0 else None],
            'ps_ttm': [self._sf(df['psTTM'].iloc[-1]) if len(df)>0 else None],
            'pcf_ttm': [self._sf(df['pcfNcfTTM'].iloc[-1]) if len(df)>0 else None],
        })
        
        return kline, fin
    
    # ===================================================================
    # 财务数据
    # ===================================================================
    
    def _fetch_all_financial(self, cache: DataCache, codes: list):
        logger.info(f"\n[3/3] 季报财务数据（{len(codes)}只）...")
        logger.info(f"  ⚠ 每只约30秒（查询17年×4季度），预计{len(codes)*30/3600:.0f}小时")
        logger.info(f"  ⚠ 首次拉取建议限制数量，如 --test 500")
        
        total, errors = 0, 0
        fin_batch = []
        BATCH_SIZE = 50
        
        for i, code in enumerate(tqdm(codes, desc="  拉取财务数据")):
            try:
                df = self._fetch_one_financial(code)
                if len(df) > 0:
                    fin_batch.append(df)
                    total += len(df)
            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"  {code} 失败: {e}")
            
            if len(fin_batch) >= BATCH_SIZE:
                self._safe_save_financial(cache, pd.concat(fin_batch, ignore_index=True))
                fin_batch = []
        
        if fin_batch:
            self._safe_save_financial(cache, pd.concat(fin_batch, ignore_index=True))
        
        cache.log_update('financial', '', '', total)
        logger.info(f"  ✓ 财务: {total}条, 失败{errors}只")
    
    def _fetch_one_financial(self, code: str) -> pd.DataFrame:
        """拉取一只股票所有季报（2010-2026）"""
        bs_code = self._to_bs(code)
        rows = []
        
        for year in range(2010, 2027):
            for q in range(1, 5):
                try:
                    rs = bs.query_profit_data(code=bs_code, year=year, quarter=q)
                    while (rs.error_code == '0') & rs.next():
                        data = rs.get_row_data()
                        rows.append({
                            'code': code,
                            'report_date': data[2].replace('-','') if len(data) > 2 else '',
                            'disclosure_date': data[1].replace('-','') if len(data) > 1 else '',
                            'roe': self._sf(data[5]) if len(data) > 5 else None,
                            'roa': self._sf(data[6]) if len(data) > 6 else None,
                            'gross_margin': self._sf(data[8]) if len(data) > 8 else None,
                            'net_margin': self._sf(data[7]) if len(data) > 7 else None,
                            'revenue_yoy': self._sf(data[9]) if len(data) > 9 else None,
                            'net_profit_yoy': self._sf(data[10]) if len(data) > 10 else None,
                        })
                except:
                    continue
        
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    
    # ===================================================================
    # 辅助
    # ===================================================================
    
    def _to_bs(self, code: str) -> str:
        code = code.replace('sh.','').replace('sz.','').replace('bj.','')
        if code.startswith(('6','9')): return f"sh.{code}"
        elif code.startswith(('8','4')): return f"bj.{code}"
        return f"sz.{code}"
    
    def _sf(self, value) -> Optional[float]:
        if value is None or value == '': return None
        try:
            f = float(value)
            return None if np.isnan(f) or np.isinf(f) else f
        except: return None
    
    def _safe_save_financial(self, cache: DataCache, df: pd.DataFrame):
        """安全写入：去重后写入"""
        if len(df) == 0:
            return
        # 去重：同code+report_date只保留最新
        df = df.drop_duplicates(subset=['code', 'report_date'], keep='last')
        try:
            cache.save_financial_data(df)
        except Exception as e:
            logger.warning(f"财务写入失败: {e}，可能是主键冲突，已跳过")
