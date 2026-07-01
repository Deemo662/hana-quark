# Quant System 架构设计

## 设计原则
- **解耦**：层间通过抽象接口通信，不直接依赖具体实现
- **复用**：因子、策略、数据源均可插拔注册
- **拓展**：新增因子只需实现接口+注册，不改核心逻辑
- **准确**：数据层有缓存和校验，因子计算基于语义清晰的数据模型

## 架构分层

```
┌─────────────────────────────────────┐
│            output/  输出层           │
│  信号生成 · 持仓清单 · 调仓建议     │
└──────────────────┬──────────────────┘
                   │
┌──────────────────┴──────────────────┐
│         screening/  筛选层           │
│  股票池构建 · 因子打分 · 组合优化   │
└──────────────────┬──────────────────┘
                   │
┌──────────────────┴──────────────────┐
│          factors/  因子层            │
│  单因子计算 · 因子注册 · 复合因子   │
│  估值·质量·成长·动量·波动·股息·排雷│
└──────────────────┬──────────────────┘
                   │
┌──────────────────┴──────────────────┐
│           data/  数据层              │
│  数据源抽象 · AkShare实现 · 本地缓存 │
│  行情数据 · 财务数据 · 数据校验      │
└─────────────────────────────────────┘

独立维度：
┌─────────────────────────────────────┐
│        backtest/  回测层             │
│  Backtrader封装 · 绩效分析 · 报告   │
└─────────────────────────────────────┘
```

## 数据流向

```
config/strategies.yaml (策略定义)
        │
        ▼
data/provider ──→ screening/universe (股票池)
                        │
                        ▼
                  factors/registry (因子计算)
                        │
                        ▼
                  screening/scorer (打分排序)
                        │
                        ▼
                  screening/portfolio (组合构建)
                        │
                        ▼
                  output/reporter (信号输出)
```

## 关键技术选型
| 层次 | 技术 | 理由 |
|---|---|---|
| 数据源 | AkShare | 免费、A股全品种、财务+行情一体化 |
| 数据处理 | pandas | 因子计算天然适合DataFrame |
| 缓存 | SQLite | 轻量、零配置、足够用 |
| 回测 | Backtrader | 成熟稳定、事件驱动、文档完善 |
| 配置 | YAML | 人类可读、策略定义直观 |

## 因子注册机制
每个因子是一个独立模块，通过装饰器 `@register_factor` 注册到全局因子表。
策略配置只需写因子名，运行时自动查找对应实现。

```python
@register_factor("pe_ttm", category="value")
class PEFactor(BaseFactor):
    def compute(self, data: FactorData) -> pd.Series:
        ...
```

## 策略定义格式 (config/strategies.yaml)
```yaml
strategies:
  best_five_factor:
    name: "市值+毛利率+ROIC+6月波动率+PS"
    factors:
      - size_market_cap      # 市值（升序=越小越好）
      - quality_gross_margin  # 毛利率
      - quality_roic         # ROIC
      - momentum_volatility_6m  # 6月波动率
      - value_ps_ttm         # 市销率
    weights: equal           # 等权打分
    top_n: 20                # 选前20只
    rebalance: monthly       # 月频调仓

  magic_formula_improved:
    name: "中小市值改进神奇公式"
    factors:
      - size_market_cap
      - momentum_volatility_6m
      - quality_roic
      - quality_gross_margin
      - value_ev2ebitda
    weights: equal
    top_n: 20
    rebalance: monthly
```

## 准确性保障
1. 财务数据使用PIT（Point-In-Time）原则：调仓日只使用已披露的最新财报
2. 数据缓存带时间戳，增量更新避免重复拉取
3. 因子计算结果带校验：NaN值标记、极端值winsorize
4. 回测结果与书中对照验证
