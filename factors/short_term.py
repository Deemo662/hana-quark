"""
短线因子：首板回调 / 量能突破 / 烂板反转 / 龙虎榜 / 动量
注册到全局 FACTOR_REGISTRY，与基本面因子共存
"""
import numpy as np
import pandas as pd
from factors.base import BaseFactor, FactorData, register_factor


# ===== 首板回调相关 =====

@register_factor("hot_first_board", "short_term")
class FirstBoardFactor(BaseFactor):
    """昨日首板涨停（非一字板、非ST）"""
    def compute(self, data: FactorData) -> pd.Series:
        if not hasattr(data, 'limit_up_data') or data.limit_up_data is None:
            return pd.Series(dtype=float)
        df = data.limit_up_data
        if df.empty:
            return pd.Series(dtype=float)
        result = {}
        for code in data.codes:
            r = df[df['code'] == code]
            if r.empty:
                result[code] = 0
            else:
                latest = r.iloc[-1]
                is_first = latest.get('is_first_board', 0)
                is_zt = latest.get('is_zt', 0)
                result[code] = 1.0 if (is_first and is_zt) else 0.0
        return pd.Series(result)


@register_factor("hot_callback_ratio", "short_term")
class CallbackRatioFactor(BaseFactor):
    """首板次日回调幅度：越小越好（-3%到+3%最优）"""
    def compute(self, data: FactorData) -> pd.Series:
        result = {}
        for code in data.codes:
            df = data.market.loc[code] if code in data.market.index.get_level_values(0) else pd.DataFrame()
            if len(df) < 2:
                result[code] = np.nan
                continue
            s = df.sort_index()
            yesterday_close = s['close'].iloc[-2]
            today_open = s['open'].iloc[-1]
            if yesterday_close > 0:
                result[code] = (today_open - yesterday_close) / yesterday_close * 100
            else:
                result[code] = np.nan
        return pd.Series(result)


# ===== 量能相关 =====

@register_factor("hot_volume_ratio", "short_term")
class VolumeRatioFactor(BaseFactor):
    """开盘量比：开盘30分钟量 / 过去5日均量——越高表示越活跃"""
    def compute(self, data: FactorData) -> pd.Series:
        result = {}
        for code in data.codes:
            df = data.market.loc[code] if code in data.market.index.get_level_values(0) else pd.DataFrame()
            if len(df) < 6:
                result[code] = np.nan
                continue
            s = df.sort_index()
            today_vol = s['volume'].iloc[-1]
            avg_vol = s['volume'].iloc[-6:-1].mean()
            result[code] = today_vol / avg_vol if avg_vol > 0 else np.nan
        return pd.Series(result)


@register_factor("hot_turnover_accel", "short_term")
class TurnoverAccelFactor(BaseFactor):
    """换手率加速：今日换手 / 5日均换手"""
    def compute(self, data: FactorData) -> pd.Series:
        result = {}
        for code in data.codes:
            df = data.market.loc[code] if code in data.market.index.get_level_values(0) else pd.DataFrame()
            if len(df) < 6 or 'turnover_rate' not in df.columns:
                result[code] = np.nan
                continue
            s = df.sort_index()
            today = s['turnover_rate'].iloc[-1]
            avg = s['turnover_rate'].iloc[-6:-1].mean()
            result[code] = today / avg if avg > 0 else np.nan
        return pd.Series(result)


# ===== 动量相关 =====

@register_factor("hot_momentum_5d", "short_term")
class ShortMomentumFactor(BaseFactor):
    """5日动量：短期涨势最强的股票"""
    def compute(self, data: FactorData) -> pd.Series:
        result = {}
        for code in data.codes:
            df = data.market.loc[code] if code in data.market.index.get_level_values(0) else pd.DataFrame()
            if len(df) < 5:
                result[code] = np.nan
                continue
            s = df.sort_index()
            result[code] = (s['close'].iloc[-1] - s['close'].iloc[-5]) / s['close'].iloc[-5] * 100
        return pd.Series(result)


# ===== 烂板/炸板相关 =====

@register_factor("hot_broken_board", "short_term")
class BrokenBoardFactor(BaseFactor):
    """昨日烂板信号（盘中触板未封）"""
    def compute(self, data: FactorData) -> pd.Series:
        if not hasattr(data, 'limit_up_data') or data.limit_up_data is None:
            return pd.Series(dtype=float)
        df = data.limit_up_data
        if df.empty:
            return pd.Series(dtype=float)
        result = {}
        for code in data.codes:
            r = df[df['code'] == code]
            if r.empty:
                result[code] = 0
            else:
                latest = r.iloc[-1]
                day_high = latest.get('high', 0)
                day_close = latest.get('close', 0)
                limit_price = latest.get('limit_up_price', 0)
                # 烂板：最高价触及涨停但收盘未封
                is_broken = 1.0 if (day_high >= limit_price * 0.99 and day_close < limit_price * 0.98) else 0.0
                result[code] = is_broken
        return pd.Series(result)


# ===== 龙虎榜相关 =====

@register_factor("hot_inst_net_buy", "short_term")
class InstNetBuyFactor(BaseFactor):
    """机构席位净买入（万元）"""
    def compute(self, data: FactorData) -> pd.Series:
        if not hasattr(data, 'lhb_data') or data.lhb_data is None:
            return pd.Series(dtype=float)
        df = data.lhb_data
        if df.empty:
            return pd.Series(dtype=float)
        result = {}
        for code in data.codes:
            r = df[df['code'] == code]
            if r.empty:
                result[code] = 0
            else:
                result[code] = r['inst_net_buy'].iloc[-1] if 'inst_net_buy' in r.columns else 0
        return pd.Series(result)


# ===== 小市值（短线偏好） =====

@register_factor("hot_circ_mv_small", "short_term")
class SmallCircMVFactor(BaseFactor):
    """流通市值：越小越好（短线资金偏好小盘）"""
    def compute(self, data: FactorData) -> pd.Series:
        return data.indicators.get("circ_mv", pd.Series(dtype=float))


# ===== 情绪周期（简化版） =====

@register_factor("hot_sentiment", "short_term")
class SentimentFactor(BaseFactor):
    """市场情绪：涨停家数占比作为情绪指标"""
    def compute(self, data: FactorData) -> pd.Series:
        if not hasattr(data, 'limit_up_data') or data.limit_up_data is None:
            return pd.Series(dtype=float)
        df = data.limit_up_data
        if df.empty:
            return pd.Series(dtype=float)
        total_stocks = len(data.codes)
        limit_up_count = len(df[df['is_zt'] == 1]) if 'is_zt' in df.columns else 0
        sentiment = limit_up_count / total_stocks * 100 if total_stocks > 0 else 0
        # 所有股票返回相同情绪值
        return pd.Series(sentiment, index=data.codes)
