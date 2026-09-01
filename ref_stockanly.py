import pandas as pd
import streamlit as st

from ref_datatraker import fetch_chart, fetch_summary, format_market_cap

QUICK_SYMBOLS = [
    ("AAPL", "AAPL"),
    ("TSLA", "TSLA"),
    ("NVDA", "NVDA"),
    ("005930.KS", "삼성전자"),
]


def analyze_stock(symbol: str) -> dict:
    """주식 데이터 수집 및 AI 기반 기술적 분석"""
    chart = fetch_chart(symbol)
    summary = fetch_summary(symbol)

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

    col1, col2 = st.columns(2)

    with col1:
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

    with col2:
        st.markdown("### 3개월 가격 추이")
        chart_df = pd.DataFrame(data["history"]).set_index("date")
        st.line_chart(chart_df["close"], use_container_width=True)


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
