# 回测框架已知问题

> 记录回测层 `backtest/engine.py` 与系统其他模块交互中发现的问题。
> 这些问题不影响Mock数据验证，但在接入真实A股数据前需要解决。

---

## 1. FactorData._codes 在 MultiIndex 行情下取值异常

**文件**: `factors/base.py:44`
**严重程度**: 低（当前不影响因子计算）

```python
self._codes = market_data.index.tolist() if not market_data.empty else []
```

当 `market_data` 是 MultiIndex `(code, date)` 时，`.index.tolist()` 返回的是元组列表，例如：
```
[('600519', Timestamp('2020-01-02')), ('600519', Timestamp('2020-01-03')), ...]
```
而非预期的股票代码列表 `['600519', '000858', ...]`。

**影响**: `self.codes` 属性目前仅在少数场景作为便利属性使用，因子计算直接通过 `data.market` 访问 MultiIndex 并调用 `.get_level_values(0).unique()`，所以当前不影响任何因子计算。

**修复建议**:
```python
if isinstance(market_data.index, pd.MultiIndex):
    self._codes = market_data.index.get_level_values(0).unique().tolist()
else:
    self._codes = market_data.index.tolist()
```

---

## 2. Mock数据日期类型不兼容 Backtrader

**文件**: `data/mock_provider.py:get_market_data()`
**严重程度**: 已修复

Mock数据中的 `date` 列使用 Python `datetime.date` 对象，而 Backtrader 的 `PandasData` feed 期望 `pandas.Timestamp` 索引。

**修复**: 在 `backtest/engine.py:_build_cerebro()` 中添加了 `pd.to_datetime(df.index)` 转换。

---

## 3. A股整数手（100股/手）未建模

**文件**: `backtest/engine.py:QuantStrategy._rebalance()`
**严重程度**: 中（真实回测时需修复）

当前使用 `self.order_target_percent()` 实现等权调仓，该方法按百分比下单，可能产生非整数手的股数。

**影响**: 在真实A股交易中，买入必须以100股（1手）为单位。当前Mock回测中此问题被掩盖。

**修复建议**: 自定义sizer或在下单前手动调整 size 为100的整数倍。或者使用 `bt.sizers.FixedSize`。

---

## 4. 最低佣金5元未完全建模

**文件**: `backtest/engine.py:AShareCommission`
**严重程度**: 低

A股佣金有最低5元的硬约束（部分券商已取消，但历史数据回测仍需考虑）。

**影响**: 对大规模资金回测影响极小，但对小资金（<2万元）回测会造成偏差。

**修复建议**: 已在 `_getcommission` 中加了 `max(comm, 5.0)` 的最低保护，但 Backtrader 的 commission 模型在部分场景下可能不精确。

---

## 5. 调仓日顺延逻辑依赖Backtrader自然延迟

**文件**: `backtest/engine.py:QuantStrategy.next()`
**严重程度**: 低

当调仓日（如月末）恰逢周末时，`current_date` 自然顺延到下一个交易日，调仓信号在第一个有效交易日执行。这是正确的行为。但需要确认模拟数据和真实交易日历的一致性。

**验证**: 当前Mock数据不包含非交易日，顺延逻辑仅处理周末。

---

## 6. 回测中无现金分红建模

**文件**: 全局
**严重程度**: 中

策略铁律规定"红利再投资"（STRATEGY_RULES.md 第9条），但Mock数据不生成分红事件，Backtrader策略也不处理分红。

**影响**: 真实回测中，分红约贡献年化1-2%的收益。缺少此建模会导致回测收益偏低。

**修复建议**: 在数据源中添加 `dividend` 字段，或在 Backtrader 中注册 dividend 事件处理。

---

## 7. 因子计算时未做行业中性化

**文件**: `screening/scorer.py`
**严重程度**: 低（功能增强）

当前因子打分不包含行业中性化步骤。书中部分策略提到了行业中性化的价值。

**说明**: 单纯的双因子模型（如 pb_lowvol）通常不做行业中性化。这是增强功能而非缺陷。

---

## 8. Mock数据源的seed固定导致结果可复现但缺乏随机性

**文件**: `data/mock_provider.py`
**严重程度**: 功能说明

`get_market_data` 使用固定的 `RandomState(42)`，`get_daily_indicators` 和 `get_financial_data` 使用 `hash(trade_date)` 作为 seed。

**说明**: 这是预期行为——固定 seed 保证同一日期生成的估值/财务数据一致（满足PIT原则），同时行情数据路径确定。

---

## 验证结论

| 检查项 | 状态 |
|--------|------|
| Backtrader数据消费（MultiIndex → PandasData） | ✅ 通过 |
| 月度调仓逻辑 | ✅ 通过 |
| 等权持有目标股票 | ✅ 通过 |
| 佣金+印花税建模 | ✅ 通过 |
| 绩效分析（CAGR/Sharpe/MaxDD/胜率） | ✅ 通过 |
| 月收益序列统计 | ✅ 通过 |
| 交易统计摘要 | ✅ 通过 |
| pb_lowvol 策略端到端 | ✅ 通过 (11.51% CAGR, Mock) |
| roe_lowvol 策略端到端 | ✅ 通过 (6.37% CAGR, Mock) |
| top_n=5 小组合验证 | ✅ 通过 (18.10% CAGR, Mock) |
| ev2sales 因子支持 | ✅ 新增 |
| equity_to_debt 因子支持 | ✅ 新增 |
| 25只股票大/中/小盘覆盖 | ✅ 新增 |
