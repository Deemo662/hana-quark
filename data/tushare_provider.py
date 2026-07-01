"""
Tushare 数据源 — 全市场秒级获取PE/PB/ROE/毛利率等
需要先注册 tushare.pro 获取 token（免费注册，基础数据免费）
"""
import os
from datetime import date
from typing import Optional
import pandas as pd
import tushare as ts

from .provider import DataProvider


class TushareProvider(DataProvider):
    """
    基于 Tushare Pro 的数据源
    首次使用需要:
    1. 注册 https://tushare.pro
    2. 获取 token
    3. 设置环境变量: export TUSHARE_TOKEN=your_token
    或在代码中: provider = TushareProvider(token='your_token')
    """

    def __init__(self, token: str = None):
        self.token = token or os.environ.get("TUSHARE_TOKEN", "")
        if not self.token:
            print("⚠ Tushare token 未设置。")
            print("  1. 注册 https://tushare.pro")
            print("  2. export TUSHARE_TOKEN=your_token")
        else:
            ts.set_token(self.token)
        self.pro = ts.pro_api()

    def get_stock_list(self, trade_date: Optional[date] = None) -> pd.DataFrame:
        """获取A股全量列表"""
        df = self.pro.stock_basic(exchange='', list_status='L',
                                   fields='ts_code,symbol,name,list_date')
        df['code'] = df['symbol'].astype(str).str.zfill(6)
        df['list_date'] = pd.to_datetime(df['list_date'])
        return df.set_index('code')

    def get_market_data(self, codes: list[str], start: date, end: date) -> pd.DataFrame:
        """获取日线行情（全量一次性拉取）"""
        ts_codes = [f"{c}.{'SH' if c.startswith('6') else 'SZ'}" for c in codes]
        frames = []
        for ts_code in ts_codes:
            try:
                df = self.pro.daily(ts_code=ts_code, start_date=start.strftime('%Y%m%d'),
                                     end_date=end.strftime('%Y%m%d'))
                if df is not None and not df.empty:
                    df['code'] = ts_code[:6]
                    df['trade_date'] = pd.to_datetime(df['trade_date'])
                    df = df.set_index(['code', 'trade_date'])
                    frames.append(df)
            except Exception:
                continue
        return pd.concat(frames) if frames else pd.DataFrame()

    def get_daily_indicators(self, codes: list[str], trade_date: date) -> pd.DataFrame:
        """
        获取全市场日频估值指标（秒级！）
        这是 Tushare 最大的优势：一次 API 调用拿到全市场 PE/PB/PS/市值
        """
        try:
            df = self.pro.daily_basic(
                trade_date=trade_date.strftime('%Y%m%d'),
                fields='ts_code,trade_date,pe,pe_ttm,pb,ps,ps_ttm,total_mv,circ_mv,turnover_rate,turnover_rate_f'
            )
            if df is None or df.empty:
                return pd.DataFrame()

            df['code'] = df['ts_code'].str[:6]
            df = df[df['code'].isin(codes)]
            df = df.rename(columns={
                'pe_ttm': 'pe_ttm', 'pb': 'pb', 'ps_ttm': 'ps_ttm',
                'total_mv': 'total_mv', 'circ_mv': 'circ_mv',
            })
            # 市值单位: 万元 → 亿元
            df['total_mv'] = df['total_mv'] / 10000
            df['circ_mv'] = df['circ_mv'] / 10000
            return df.set_index('code')
        except Exception as e:
            print(f"Tushare daily_basic 失败: {e}")
            return pd.DataFrame()

    def get_financial_data(self, codes: list[str], report_date: date) -> pd.DataFrame:
        """
        获取财务指标（ROE/ROA/毛利率/净利率等）
        Tushare 的 fina_indicator 接口一次可拿多只股票
        """
        try:
            ts_codes = [f"{c}.{'SH' if c.startswith('6') else 'SZ'}" for c in codes]
            df = self.pro.fina_indicator(ts_code=','.join(ts_codes[:200]))
            if df is None or df.empty:
                return pd.DataFrame()

            # 取最新一期
            latest = df.sort_values('end_date').groupby('ts_code').last().reset_index()
            latest['code'] = latest['ts_code'].str[:6]
            latest = latest.rename(columns={
                'roe': 'roe', 'roa': 'roa',
                'grossprofit_margin': 'gross_margin',
                'netprofit_margin': 'net_margin',
                'debt_to_assets': 'debt_to_assets',
            })
            return latest.set_index('code')[['roe', 'roa', 'gross_margin', 'net_margin', 'debt_to_assets']]
        except Exception as e:
            print(f"Tushare fina_indicator 失败: {e}")
            return pd.DataFrame()
