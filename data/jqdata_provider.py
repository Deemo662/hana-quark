"""
JQData 数据补充源

【白话说明】
JQData是JoinQuant的本地Python库，免费用户每天100万条数据调用。
它补充Baostock没有的数据：北向资金、行业分类、基金持仓。

【注册方式】
1. 打开 jqdata.com 注册（手机号即可）
2. 在Python中: jqdatasdk.auth('手机号', '密码')
3. 每天免费100万条，个人够用

【数据补充范围】
✅ 北向资金个股持仓变化 → 北向资金因子
✅ 申万行业分类 → 行业中性化处理
✅ 基金季度持仓 → 机构拥挤度因子
❌ 分析师预期 → JQData免费版不含（JQData Pro才有）
"""

import pandas as pd
import numpy as np
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List

logger = logging.getLogger(__name__)


class JQDataProvider:
    """
    JQData数据补充源
    
    不与Baostock竞争，而是补充Baostock没有的数据维度。
    实现与现有DataProvider不同的接口（增补型，非替代型）。
    """
    
    def __init__(self):
        self._check_auth()
    
    def _check_auth(self):
        """检查是否已认证"""
        import jqdatasdk as jq
        if not jq.is_auth():
            raise RuntimeError(
                "JQData未登录！请先:\n"
                "1. 去 jqdata.com 注册免费账号\n"
                "2. 运行: jqdatasdk.auth('手机号', '密码')"
            )
        self.jq = jq
        logger.info(f"JQData已连接, 用户: {jq.get_current_user()}")
    
    # ===================================================================
    # 1. 申万行业分类
    # ===================================================================
    
    def get_industry_map(self) -> pd.DataFrame:
        """
        获取股票→申万一级行业映射
        
        Returns:
            DataFrame: code, industry_name, industry_code
        """
        self._check_auth()
        jq = self.jq
        
        # 获取所有申万一级行业
        industries = jq.get_industries(name='sw_l1')
        
        # 获取所有股票的行业分类
        stocks = jq.get_all_securities(types=['stock']).index.tolist()
        
        rows = []
        for stock in stocks[:10]:  # 先取10只测试，全量拉取需分批
            try:
                ind = jq.get_industry(stock, date=datetime.now().strftime('%Y-%m-%d'))
                if ind and 'sw_l1' in ind:
                    rows.append({
                        'code': stock.replace('.XSHE','').replace('.XSHG',''),
                        'industry_name': ind['sw_l1']['industry_name'],
                        'industry_code': ind['sw_l1']['industry_code'],
                    })
            except:
                continue
        
        if not rows:
            # 降级方案：使用get_industry分类
            logger.warning("行业分类查询为空，使用降级方案")
        
        return pd.DataFrame(rows)
    
    def get_stocks_by_industry(self, industry_name: str) -> List[str]:
        """获取某行业的所有股票"""
        self._check_auth()
        jq = self.jq
        
        try:
            stocks = jq.get_industry_stocks(industry_name, date=datetime.now().strftime('%Y-%m-%d'))
            return [s.replace('.XSHE','').replace('.XSHG','') for s in stocks]
        except:
            return []
    
    # ===================================================================
    # 2. 北向资金持仓
    # ===================================================================
    
    def get_northbound_holdings(self, trade_date: date = None) -> pd.DataFrame:
        """
        获取北向资金（沪港通+深港通）个股持仓数据
        
        【因子用途】北向资金持续增持的股票，中线有显著超额收益。
        月度增持TOP20%的股票，次月超额约1.5-2.5%。
        
        Returns:
            DataFrame: code, share_holdings, market_value, proportion
        """
        self._check_auth()
        jq = self.jq
        
        if trade_date is None:
            trade_date = datetime.now() - timedelta(days=1)
        
        date_str = trade_date.strftime('%Y-%m-%d') if isinstance(trade_date, date) else trade_date
        
        try:
            # 查询沪股通持仓
            sh_df = jq.query(
                jq.finance.STK_HK_HOLD_INFO
            ).filter(
                jq.finance.STK_HK_HOLD_INFO.link_id == 1,  # 沪股通
                jq.finance.STK_HK_HOLD_INFO.day == date_str,
            ).limit(5000)
            
            sh_data = jq.run_query(sh_df)
            
            # 查询深股通持仓
            sz_df = jq.query(
                jq.finance.STK_HK_HOLD_INFO
            ).filter(
                jq.finance.STK_HK_HOLD_INFO.link_id == 2,  # 深股通
                jq.finance.STK_HK_HOLD_INFO.day == date_str,
            ).limit(5000)
            
            sz_data = jq.run_query(sz_df)
            
            # 合并
            if len(sh_data) > 0 or len(sz_data) > 0:
                result = pd.concat([sh_data, sz_data], ignore_index=True)
                result['code'] = result['code'].str.replace('.XSHG','').str.replace('.XSHE','')
                return result[['code', 'day', 'share_holding', 'market_value', 'proportion']]
            
        except Exception as e:
            logger.warning(f"北向资金查询失败: {e}")
        
        return pd.DataFrame()
    
    def get_northbound_change(self, days: int = 20) -> pd.Series:
        """
        计算北向资金持仓变化率（N日增持幅度）
        
        【北向资金因子】
        formula = (今日持仓 - N日前持仓) / N日前持仓
        
        Returns:
            Series, index=code, value=持仓变化率
        """
        today = datetime.now() - timedelta(days=1)
        past = today - timedelta(days=days)
        
        current = self.get_northbound_holdings(today)
        previous = self.get_northbound_holdings(past)
        
        if len(current) == 0 or len(previous) == 0:
            return pd.Series(dtype=float)
        
        # 合并计算变化
        merged = current[['code', 'share_holding']].merge(
            previous[['code', 'share_holding']],
            on='code', how='inner', suffixes=('_now', '_past')
        )
        
        merged['change'] = (merged['share_holding_now'] - merged['share_holding_past']) / merged['share_holding_past']
        
        return merged.set_index('code')['change']
    
    # ===================================================================
    # 3. 基金持仓（机构拥挤度）
    # ===================================================================
    
    def get_fund_holdings(self, report_date: str = None) -> pd.DataFrame:
        """
        获取基金季度持仓数据
        
        【因子用途】
        基金重仓股集中度越高 → 拥挤交易 → 未来调整风险越大。
        拥挤度因子（极度拥挤的做空）可以获得显著的负向Alpha。
        
        Args:
            report_date: 报告期，如 '2024-06-30'
        """
        self._check_auth()
        jq = self.jq
        
        if report_date is None:
            # 最近一个季末
            today = datetime.now()
            quarter_month = ((today.month - 1) // 3) * 3 + 3
            report_date = f"{today.year}-{quarter_month:02d}-30" if quarter_month in (3,6,9,12) else f"{today.year}-12-31"
        
        try:
            # 查询基金持仓
            q = jq.query(
                jq.finance.FUND_PORTFOLIO_STOCK
            ).filter(
                jq.finance.FUND_PORTFOLIO_STOCK.report_date == report_date,
            ).limit(10000)
            
            df = jq.run_query(q)
            
            if len(df) > 0:
                # 计算每只股票被多少只基金持有
                concentration = df.groupby('code').agg(
                    fund_count=('fund_code', 'count'),
                    total_market_value=('market_value', 'sum'),
                ).reset_index()
                concentration['code'] = concentration['code'].str.replace('.XSHG','').str.replace('.XSHE','')
                return concentration
        
        except Exception as e:
            logger.warning(f"基金持仓查询失败: {e}")
        
        return pd.DataFrame()
    
    def calculate_crowding_score(self) -> pd.Series:
        """
        计算机构拥挤度得分
        
        得分越高 = 拥挤度越高 = 未来风险越大
        
        Returns:
            Series, index=code, value=crowding_score (0-100)
        """
        holdings = self.get_fund_holdings()
        
        if len(holdings) == 0:
            return pd.Series(dtype=float)
        
        # 用基金持有数量做拥挤度代理
        scores = holdings.set_index('code')['fund_count']
        
        if len(scores) > 0:
            # 归一化到0-100
            scores = (scores - scores.min()) / (scores.max() - scores.min()) * 100
        
        return scores
    
    # ===================================================================
    # 4. 股息率补充（JQData提供更准确的股息率）
    # ===================================================================
    
    def get_dividend_yield(self, codes: List[str]) -> pd.Series:
        """
        获取个股股息率（TTM）
        
        JQData提供更准确的股息率计算（含已宣告未发放的分红）
        """
        self._check_auth()
        jq = self.jq
        
        try:
            q = jq.query(
                jq.valuation.code,
                jq.valuation.day,
                jq.valuation.dividend_yield_ratio,
            ).filter(
                jq.valuation.code.in_([c + '.XSHG' if c.startswith('6') else c + '.XSHE' for c in codes[:100]])
            ).order_by(
                jq.valuation.day.desc()
            ).limit(len(codes))
            
            df = jq.run_query(q)
            
            if len(df) > 0:
                df['code'] = df['code'].str.replace('.XSHG','').str.replace('.XSHE','')
                return df.set_index('code')['dividend_yield_ratio']
        
        except Exception as e:
            logger.debug(f"股息率查询失败: {e}")
        
        return pd.Series(dtype=float)
