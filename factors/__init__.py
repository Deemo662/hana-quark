"""
因子层

导入所有因子模块以触发 @register_factor 装饰器注册。
新增因子时在此处添加 import。
"""

from .base import BaseFactor, FactorData, FACTOR_REGISTRY, register_factor
from .value import PEFactor, PBFactor, PSFactor, PCFFactor, EV2EBITDAFactor, EV2SalesFactor, DividendYieldFactor
from .quality import ROEFactor, ROAFactor, ROICFactor, GrossMarginFactor, NetMarginFactor
from .momentum import Momentum3MFactor, Momentum6MFactor, Momentum12MFactor, Volatility6MFactor, Volatility12MFactor
from .size import MarketCapFactor
from .safety import OCFToProfitFactor, SalesCashToRevenueFactor, InterestCoverageFactor, DebtToAssetsFactor, EquityToDebtFactor
from .growth import RevenueYoYFactor, ProfitYoYFactor, OpProfitYoYFactor
