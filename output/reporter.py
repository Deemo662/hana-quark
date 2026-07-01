"""
可视化报告生成器
从 SQLite 读取每日跟踪数据，生成独立 HTML 报告
零依赖，纯 HTML+CSS+SVG，浏览器直接打开
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path
import json

DB_PATH = Path(__file__).parent.parent / "data" / "tracker.db"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def generate(strategy: str = "best_five_factor", trade_date: date = None):
    if trade_date is None:
        trade_date = date.today()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # ---- 数据查询 ----
    # 今日选股
    signals = conn.execute("""
        SELECT s.rank, s.code, s.name, s.score
        FROM signals s
        WHERE s.strategy=? AND s.trade_date=?
        ORDER BY s.rank
        LIMIT 20
    """, (strategy, trade_date.isoformat())).fetchall()

    # 近7日绩效
    perf = conn.execute("""
        SELECT p.trade_date, p.total_value, p.daily_return, p.cumulative_return,
               b.close as benchmark_close, b.daily_return as benchmark_return
        FROM performance p
        LEFT JOIN benchmarks b ON p.trade_date=b.trade_date
        WHERE p.strategy=? AND p.trade_date >= ?
        ORDER BY p.trade_date ASC
    """, (strategy, (trade_date - timedelta(days=14)).isoformat())).fetchall()

    # 策略信息（从config读）
    strategy_label = "市值+毛利率+ROIC+6月波动率+PS"

    conn.close()

    # ---- 计算汇总 ----
    total_value = perf[-1]["total_value"] if perf else 100000
    cum_return = (total_value / 100000 - 1) * 100

    win_days = sum(1 for p in perf if p["daily_return"] and p["daily_return"] > 0)
    total_days = max(len(perf), 1)

    # 基准对比
    bm_return = 0
    if perf and any(p["benchmark_return"] for p in perf):
        bm_vals = [p["benchmark_close"] for p in perf if p["benchmark_close"]]
        if len(bm_vals) >= 2:
            bm_return = (bm_vals[-1] / bm_vals[0] - 1) * 100

    alpha = cum_return - bm_return if bm_return else 0

    # ---- SVG 迷你收益曲线 ----
    svg_points = _build_sparkline([p["cumulative_return"] for p in perf if p["cumulative_return"] is not None])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📊 量化选股报告 — {trade_date}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f5f5f5; color:#333; padding:20px; }}
.card {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,.1); }}
h1 {{ font-size:24px; margin-bottom:4px; }}
h2 {{ font-size:18px; color:#666; margin-bottom:16px; }}
.subtitle {{ color:#999; font-size:14px; margin-bottom:20px; }}
.grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:16px; margin-bottom:20px; }}
.stat {{ background:#f8f9fa; border-radius:8px; padding:16px; text-align:center; }}
.stat-value {{ font-size:28px; font-weight:700; }}
.stat-label {{ font-size:12px; color:#999; margin-top:4px; }}
.positive {{ color:#16a34a; }}
.negative {{ color:#dc2626; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; padding:10px 12px; border-bottom:2px solid #e5e7eb; font-size:13px; color:#666; font-weight:600; }}
td {{ padding:10px 12px; border-bottom:1px solid #f3f4f6; font-size:14px; }}
tr:hover {{ background:#f8f9fa; }}
.rank {{ display:inline-block; width:24px; height:24px; line-height:24px; text-align:center; border-radius:6px; font-size:12px; font-weight:700; background:#e5e7eb; }}
.rank-1 {{ background:#fbbf24; color:#fff; }}
.rank-2 {{ background:#94a3b8; color:#fff; }}
.rank-3 {{ background:#d97706; color:#fff; }}
.chart {{ width:100%; height:120px; }}
.footer {{ text-align:center; color:#999; font-size:12px; margin-top:20px; }}
.note {{ background:#fef3c7; border-left:4px solid #f59e0b; padding:12px 16px; border-radius:0 8px 8px 0; margin-top:20px; font-size:13px; }}
</style>
</head>
<body>

<div class="card">
  <h1>📊 量化选股日报</h1>
  <h2>{strategy_label}</h2>
  <div class="subtitle">{trade_date} ｜ 数据源: AkShare 实时 ｜ 自动生成</div>

  <div class="grid">
    <div class="stat">
      <div class="stat-value">¥{total_value:,.0f}</div>
      <div class="stat-label">模拟总资产</div>
    </div>
    <div class="stat">
      <div class="stat-value {'positive' if cum_return >= 0 else 'negative'}">{cum_return:+.2f}%</div>
      <div class="stat-label">累计收益</div>
    </div>
    <div class="stat">
      <div class="stat-value {'positive' if alpha >= 0 else 'negative'}">{alpha:+.2f}%</div>
      <div class="stat-label">超额收益(vs 沪深300)</div>
    </div>
    <div class="stat">
      <div class="stat-value">{win_days}/{total_days}</div>
      <div class="stat-label">正收益天数</div>
    </div>
  </div>

  <svg class="chart" viewBox="0 0 280 60">
    <line x1="0" y1="30" x2="280" y2="30" stroke="#e5e7eb" stroke-width="1"/>
    {svg_points}
  </svg>
  <div style="display:flex; justify-content:space-between; font-size:11px; color:#999; margin-top:4px;">
    <span>{perf[0]['trade_date'] if perf else ''}</span>
    <span>{perf[-1]['trade_date'] if perf else ''}</span>
  </div>
</div>

<div class="card">
  <h2>📋 今日选股 TOP 20</h2>
  <table>
    <thead><tr><th>#</th><th>代码</th><th>名称</th><th>得分</th></tr></thead>
    <tbody>
"""
    for s in signals:
        rank = s["rank"]
        rank_cls = f"rank-{rank}" if rank <= 3 else ""
        html += f"""      <tr>
        <td><span class="rank {rank_cls}">{rank}</span></td>
        <td style="font-family:monospace">{s['code']}</td>
        <td>{s['name']}</td>
        <td style="font-weight:600">{s['score']:.1f}</td>
      </tr>
"""

    html += f"""    </tbody>
  </table>
</div>

<div class="card">
  <h2>📈 近期绩效跟踪</h2>
  <table>
    <thead><tr><th>日期</th><th>总资产</th><th>日收益</th><th>累计收益</th><th>沪深300日收益</th></tr></thead>
    <tbody>
"""
    for p in perf[-14:]:
        dr = p["daily_return"] or 0
        cr = p["cumulative_return"] or 0
        bm = p["benchmark_return"] or 0
        dr_cls = "positive" if dr > 0 else "negative" if dr < 0 else ""
        html += f"""      <tr>
        <td>{p['trade_date']}</td>
        <td>¥{p['total_value']:,.0f}</td>
        <td class="{dr_cls}">{dr:+.2f}%</td>
        <td class="{'positive' if cr>=0 else 'negative'}">{cr:+.2f}%</td>
        <td class="{'positive' if bm>=0 else 'negative'}">{bm:+.2f}%</td>
      </tr>
"""

    html += """    </tbody>
  </table>
</div>

"""

    if not signals:
        html += """<div class="note">⚠️ 今日暂无选股数据。请确认定时任务已正常运行。</div>"""

    html += f"""<div class="footer">
  量化选股系统 v1.0 ｜ 基于董鹏飞《基本面量化投资策略》 ｜ 生成时间: {date.today()}
</div>

</body>
</html>"""

    output_path = OUTPUT_DIR / f"report_{trade_date.isoformat()}.html"
    output_path.write_text(html, encoding="utf-8")

    # 同时写一份 latest.html（始终是最新的）
    latest_path = OUTPUT_DIR / "latest.html"
    latest_path.write_text(html, encoding="utf-8")

    print(f"✅ 报告已生成: {output_path}")
    print(f"   快捷入口: {latest_path}")
    return str(output_path)


def _build_sparkline(values: list) -> str:
    """用SVG polyline画迷你收益曲线"""
    if not values or len(values) < 2:
        return '<text x="140" y="35" text-anchor="middle" fill="#999" font-size="10">数据不足</text>'

    min_v = min(values)
    max_v = max(values)
    spread = max_v - min_v or 1

    points = []
    w = 280
    h = 60
    padding = 4
    for i, v in enumerate(values):
        x = padding + i * (w - 2 * padding) / (len(values) - 1)
        y = padding + (1 - (v - min_v) / spread) * (h - 2 * padding)
        points.append(f"{x:.1f},{y:.1f}")

    poly = " ".join(points)
    color = "#16a34a" if values[-1] >= values[0] else "#dc2626"

    return f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'


if __name__ == "__main__":
    generate()
