import pandas as pd
import streamlit as st

from ref_datatraker import fetch_chart, fetch_summary, format_market_cap

QUICK_SYMBOLS = [
    ("AAPL", "AAPL"),
    ("TSLA", "TSLA"),
    ("NVDA", "NVDA"),
    ("005930.KS", "삼성전자"),
]

ANALYSIS_DAYS = 100
MA_WINDOW = 10
RS_WINDOW = 20


def get_benchmark_symbol(symbol: str) -> str:
    """종목 시장에 맞는 벤치마크 지수"""
    upper = symbol.upper()
    if upper.endswith(".KS") or upper.endswith(".KQ"):
        return "^KS11"
    return "^GSPC"


def build_price_chart_data(symbol: str) -> pd.DataFrame:
    """3개월 종목 종가와 코스피 지수 비교 차트 데이터"""
    stock = fetch_chart(symbol, range_period="3mo")
    kospi = fetch_chart("^KS11", range_period="3mo")

    stock_df = pd.DataFrame(stock["history"]).set_index("date")
    kospi_df = pd.DataFrame(kospi["history"]).set_index("date")["close"].rename("코스피")

    chart_df = stock_df.join(kospi_df, how="inner").rename(columns={"close": "종가"})
    if chart_df.empty:
        raise ValueError("종목과 코스피 지수 데이터를 병합할 수 없습니다.")

    base_stock = chart_df["종가"].iloc[0]
    base_kospi = chart_df["코스피"].iloc[0]
    chart_df["종가"] = (chart_df["종가"] / base_stock * 100).round(2)
    chart_df["코스피"] = (chart_df["코스피"] / base_kospi * 100).round(2)
    return chart_df


def build_analysis_grid(symbol: str, days: int = ANALYSIS_DAYS) -> pd.DataFrame:
    """최근 N거래일 종가, RS지수, 10일 이동평균선 그리드 생성"""
    stock = fetch_chart(symbol, range_period="1y")
    benchmark = get_benchmark_symbol(symbol)
    index = fetch_chart(benchmark, range_period="1y")

    stock_df = pd.DataFrame(stock["history"]).rename(columns={"close": "종가"})
    index_df = pd.DataFrame(index["history"])[["date", "close"]].rename(
        columns={"close": "index_close"}
    )

    df = stock_df.merge(index_df, on="date", how="inner")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df["MA10"] = df["종가"].rolling(MA_WINDOW, min_periods=MA_WINDOW).mean().round(2)

    stock_ret = df["종가"] / df["종가"].shift(RS_WINDOW)
    index_ret = df["index_close"] / df["index_close"].shift(RS_WINDOW)
    df["RS지수"] = ((stock_ret / index_ret) * 100).round(2)

    df = df.tail(days).copy()
    df["날짜"] = df["date"].dt.strftime("%Y-%m-%d")
    return df[["날짜", "종가", "RS지수", "MA10"]].reset_index(drop=True)


def analyze_stock(symbol: str) -> dict:
    """주식 데이터 수집 및 AI 기반 기술적 분석"""
    chart = fetch_chart(symbol)
    summary = fetch_summary(symbol)
    grid = build_analysis_grid(symbol)
    price_chart = build_price_chart_data(symbol)

    history = chart["history"]
    current = history[-1]["close"]
    prev = history[-2]["close"] if len(history) > 1 else current
    change_pct = ((current - prev) / prev) * 100

    closes = [h["close"] for h in history]
    ma20 = sum(closes[-20:]) / min(20, len(closes))
    ma60 = sum(closes[-60:]) / min(60, len(closes)) if len(closes) >= 60 else None

    signals = []
    if current > ma20:
        signals.append("단기 상승 추세 (20일 이동평균선 상회)")
    else:
        signals.append("단기 하락 추세 (20일 이동평균선 하회)")

    if ma60 and current > ma60:
        signals.append("중기 상승 추세 (60일 이동평균선 상회)")
    elif ma60:
        signals.append("중기 하락 추세 (60일 이동평균선 하회)")

    if change_pct > 2:
        signals.append("전일 대비 강한 상승")
    elif change_pct < -2:
        signals.append("전일 대비 강한 하락")

    score = 50
    if current > ma20:
        score += 15
    if ma60 and current > ma60:
        score += 15
    if change_pct > 0:
        score += 10
    if change_pct < -3:
        score -= 10

    score = max(0, min(100, score))

    if score >= 70:
        recommendation = "매수 관심"
        sentiment = "positive"
    elif score >= 40:
        recommendation = "관망"
        sentiment = "neutral"
    else:
        recommendation = "주의"
        sentiment = "negative"

    currency = chart["currency"]
    prefix = "₩" if currency == "KRW" else "$"

    return {
        "symbol": chart["symbol"],
        "name": summary.get("name") or chart["name"],
        "price": current,
        "currency": currency,
        "price_prefix": prefix,
        "change_pct": round(change_pct, 2),
        "market_cap": summary.get("market_cap"),
        "pe_ratio": summary.get("pe_ratio"),
        "signals": signals,
        "score": score,
        "recommendation": recommendation,
        "sentiment": sentiment,
        "history": history,
        "grid": grid,
        "price_chart": price_chart,
    }


def render_analysis(data: dict) -> None:
    prefix = data["price_prefix"]
    change = data["change_pct"]
    change_label = f"{change:+.2f}%"

    st.subheader(f"{data['name']} ({data['symbol']})")
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("현재가", f"{prefix}{data['price']:,.2f}", change_label)
    metric_col2.metric("시가총액", format_market_cap(data["market_cap"], prefix))
    metric_col3.metric("PER", f"{data['pe_ratio']:.2f}" if data["pe_ratio"] else "-")

    st.markdown("### 100일 분석 그리드")
    st.caption(
        f"현재일 기준 최근 {ANALYSIS_DAYS}거래일 · "
        f"RS지수={RS_WINDOW}일 상대강도(벤치마크 대비 100) · MA10=10일 이동평균"
    )
    grid_df = data["grid"].sort_values("날짜", ascending=False).reset_index(drop=True)
    st.dataframe(
        grid_df,
        use_container_width=True,
        hide_index=True,
        height=min(600, 35 * len(grid_df) + 38),
    )

    csv = grid_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "그리드 CSV 다운로드",
        data=csv,
        file_name=f"{data['symbol']}_analysis_grid.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.markdown("### 3개월 가격 추이")
    st.caption("종목 종가 vs 코스피 지수 (3개월 시작일 = 100 기준 정규화)")
    st.line_chart(data["price_chart"], use_container_width=True)

    st.markdown("### AI 분석 결과")
    sentiment = data["sentiment"]
    if sentiment == "positive":
        st.success(f"점수 {data['score']} · {data['recommendation']}")
    elif sentiment == "neutral":
        st.warning(f"점수 {data['score']} · {data['recommendation']}")
    else:
        st.error(f"점수 {data['score']} · {data['recommendation']}")

    for signal in data["signals"]:
        st.markdown(f"- {signal}")


def render_page() -> None:
    """종목분석 Streamlit 페이지"""
    st.title("종목분석")
    st.caption("AI 기반 주식 분석")

    search_col, btn_col = st.columns([5, 1])
    with search_col:
        symbol_input = st.text_input(
            "종목 코드",
            value=st.session_state.get("symbol", ""),
            placeholder="종목 코드 입력 (예: AAPL, TSLA, 005930.KS)",
            label_visibility="collapsed",
        )
    with btn_col:
        analyze_clicked = st.button("AI 분석", type="primary", use_container_width=True)

    quick_cols = st.columns(len(QUICK_SYMBOLS))
    for col, (code, label) in zip(quick_cols, QUICK_SYMBOLS):
        if col.button(label, use_container_width=True):
            st.session_state["symbol"] = code
            symbol_input = code
            analyze_clicked = True

    symbol = (symbol_input or st.session_state.get("symbol", "")).strip().upper()

    if analyze_clicked and symbol:
        st.session_state["symbol"] = symbol
        with st.spinner("AI 분석 중..."):
            try:
                result = analyze_stock(symbol)
                render_analysis(result)
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"분석 중 오류: {e}")
    elif analyze_clicked:
        st.warning("종목 코드를 입력해 주세요.")
