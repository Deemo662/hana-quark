"""
量化交易系统 - Streamlit看板
启动: streamlit run dashboard/app.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
import pandas as pd, yaml, sqlite3
from datetime import date, timedelta

st.set_page_config(page_title="量化交易系统", page_icon="📈", layout="wide")
st.title("📈 量化交易系统")
st.caption("基于董鹏飞《基本面量化投资策略》53因子实证")

with st.sidebar:
    st.header("⚙️ 配置")
    db_path = st.selectbox("数据库",
        ["data/cache/test_quant.db", "data/cache/quant.db"],
        format_func=lambda x: "测试库(19只)" if "test" in x else "全量库")
    
    try:
        with open('config/strategies.yaml') as f:
            cfg = yaml.safe_load(f)
        strats = {k: v['name'] for k, v in cfg['strategies'].items()}
    except:
        strats = {}
    
    skey = st.selectbox("策略", list(strats.keys()), format_func=lambda k: strats.get(k, k))
    top_n = st.slider("持仓数", 5, 50, 20, 5)
    if st.button("🔄 刷新"): st.rerun()

if not os.path.exists(db_path):
    st.warning(f"数据库不存在: {db_path}"); st.stop()

from data.cache_provider import CacheProvider
provider = CacheProvider(db_path=db_path)
stock_list = provider.get_stock_list()
codes = (stock_list.index if hasattr(stock_list.index, 'tolist') else stock_list['code']).tolist()

conn = sqlite3.connect(db_path)
ld = pd.read_sql("SELECT MAX(trade_date) as d FROM daily_kline", conn)['d'].iloc[0]
conn.close()
td = date(int(ld[:4]), int(ld[4:6]), int(ld[6:8])) if ld else date.today()
st.caption(f"数据日期: {td} | 股票: {len(codes)}只")

tab1, tab2, tab3 = st.tabs(["📊 信号", "📈 回测", "🔍 因子"])

with tab1:
    st.subheader(strats.get(skey, skey))
    with st.spinner("计算中..."):
        try:
            from screening.universe import UniverseBuilder
            from screening.scorer import FactorScorer
            from factors.base import FactorData
            import factors.value, factors.quality, factors.momentum, factors.size, factors.safety, factors.growth
            
            ccfg = cfg['strategies'][skey]
            indicators = provider.get_daily_indicators(codes[:200], td)
            market = provider.get_market_data(codes[:200], td - timedelta(days=365), td)
            fin = provider.get_financial_data(codes[:200], td)
            
            fd = FactorData(td, market, indicators, fin)
            universe = UniverseBuilder().build(td, stock_list, indicators)
            
            scorer = FactorScorer(sort_orders=ccfg.get('sort_orders', {}))
            fv = scorer.compute_factors(ccfg['factors'], fd, universe)
            
            if fv:
                scored = scorer.score(fv)
                selected = scorer.select_top(scored, top_n)
                
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader(f"🟢 TOP {top_n}")
                    show = scored.head(top_n)[['total_score']].reset_index()
                    show.columns = ['代码', '得分']
                    show['排名'] = range(1, len(show)+1)
                    st.dataframe(show[['排名','代码','得分']], hide_index=True)
                
                with c2:
                    book = ccfg.get('book_cagr_20', 0)
                    st.metric("书本参考年化", f"{book}%")
                    st.metric("有效因子", f"{len(fv)}/{len(ccfg['factors'])}")
            else:
                st.warning("因子数据不足")
        except Exception as e:
            st.error(f"计算失败: {e}")

with tab2:
    st.info("回测请用命令行")

with tab3:
    from factors.base import FACTOR_REGISTRY
    info = []
    for n, c in sorted(FACTOR_REGISTRY.items()):
        i = c()
        info.append({'因子': n, '类别': i.category, '方向': i.direction, '章节': i.book_chapter})
    st.dataframe(pd.DataFrame(info), hide_index=True)
    st.metric("已注册因子", len(FACTOR_REGISTRY))
