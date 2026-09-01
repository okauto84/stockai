import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
SSL_VERIFY = os.getenv("STOCKAI_SSL_VERIFY", "false").lower() == "true"
QUICK_SYMBOLS = [
    ("AAPL", "AAPL"),
    ("TSLA", "TSLA"),
    ("NVDA", "NVDA"),
    ("005930.KS", "삼성전자"),
]


def fetch_chart(symbol: str) -> dict:
    """Yahoo Finance 차트 API로 주가 데이터 수집"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "3mo", "interval": "1d"}

    res = requests.get(
        url, params=params, headers=YAHOO_HEADERS, verify=SSL_VERIFY, timeout=15
    )
    res.raise_for_status()
    data = res.json()

    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"'{symbol}' 종목을 찾을 수 없습니다.")

    meta = result[0]["meta"]
    timestamps = result[0]["timestamp"]
    closes = result[0]["indicators"]["quote"][0]["close"]

    history = []
    for ts, close in zip(timestamps, closes):
        if close is not None:
            date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            history.append({"date": date, "close": round(close, 2)})

    if not history:
        raise ValueError(f"'{symbol}' 주가 데이터가 없습니다.")

    return {
        "symbol": symbol.upper(),
        "name": meta.get("longName") or meta.get("shortName") or symbol.upper(),
        "currency": meta.get("currency", "USD"),
        "history": history,
    }


def fetch_summary(symbol: str) -> dict:
    """Yahoo Finance 요약 API로 기본 정보 수집"""
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    params = {"modules": "summaryDetail,price"}

    try:
        res = requests.get(
            url, params=params, headers=YAHOO_HEADERS, verify=SSL_VERIFY, timeout=15
        )
        res.raise_for_status()
        result = res.json().get("quoteSummary", {}).get("result")
        if not result:
            return {}

        detail = result[0].get("summaryDetail", {})
        price = result[0].get("price", {})
        return {
            "market_cap": detail.get("marketCap", {}).get("raw"),
            "pe_ratio": detail.get("trailingPE", {}).get("raw"),
            "name": price.get("longName") or price.get("shortName"),
        }
    except Exception:
        return {}


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


def inject_styles() -> None:
    components.html(
        """
        <style>
        html, body, [class*="css"] {
            font-size: 12px !important;
        }
        .block-container {
            font-size: 12px;
            padding-top: 1.5rem;
        }
        h1 { font-size: 20px !important; color: #38bdf8 !important; }
        h2 { font-size: 16px !important; }
        h3 { font-size: 13px !important; color: #94a3b8 !important; }
        p, label, span, div, input, button {
            font-size: 12px !important;
        }
        </style>
        """,
        height=0,
    )


def format_market_cap(value, prefix: str) -> str:
    if not value:
        return "-"
    if value >= 1e12:
        return f"{prefix}{(value / 1e12):.2f}T"
    if value >= 1e9:
        return f"{prefix}{(value / 1e9):.2f}B"
    if value >= 1e6:
        return f"{prefix}{(value / 1e6):.2f}M"
    return f"{prefix}{value:,.0f}"


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


def render_sidebar() -> str:
    with st.sidebar:
        st.header("AI Stock")
        return st.radio(
            "메뉴",
            ["종목분석", "정보수집"],
            label_visibility="collapsed",
        )


def render_stock_analysis_page() -> None:
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


def render_info_collection_page() -> None:
    st.title("정보수집")
    st.caption("종목 기본 정보 및 주가 데이터 수집")

    search_col, btn_col = st.columns([5, 1])
    with search_col:
        symbol_input = st.text_input(
            "수집 종목",
            value=st.session_state.get("collect_symbol", ""),
            placeholder="종목 코드 입력 (예: AAPL, TSLA, 005930.KS)",
            label_visibility="collapsed",
            key="collect_input",
        )
    with btn_col:
        collect_clicked = st.button("정보 수집", type="primary", use_container_width=True)

    symbol = symbol_input.strip().upper()

    if collect_clicked and symbol:
        st.session_state["collect_symbol"] = symbol
        with st.spinner("정보 수집 중..."):
            try:
                chart = fetch_chart(symbol)
                summary = fetch_summary(symbol)
                prefix = "₩" if chart["currency"] == "KRW" else "$"

                st.subheader(f"{summary.get('name') or chart['name']} ({chart['symbol']})")

                col1, col2, col3 = st.columns(3)
                col1.metric("통화", chart["currency"])
                col2.metric("시가총액", format_market_cap(summary.get("market_cap"), prefix))
                col3.metric("PER", f"{summary['pe_ratio']:.2f}" if summary.get("pe_ratio") else "-")

                st.markdown("### 수집 데이터")
                info_df = pd.DataFrame([{
                    "종목코드": chart["symbol"],
                    "종목명": summary.get("name") or chart["name"],
                    "통화": chart["currency"],
                    "시가총액": format_market_cap(summary.get("market_cap"), prefix),
                    "PER": summary.get("pe_ratio"),
                    "데이터 건수": len(chart["history"]),
                }])
                st.dataframe(info_df, use_container_width=True, hide_index=True)

                history_df = pd.DataFrame(chart["history"])
                st.markdown("### 주가 이력 (3개월)")
                st.dataframe(history_df, use_container_width=True, hide_index=True)

                csv = history_df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "CSV 다운로드",
                    data=csv,
                    file_name=f"{symbol}_history.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"수집 중 오류: {e}")
    elif collect_clicked:
        st.warning("종목 코드를 입력해 주세요.")


def main() -> None:
    st.set_page_config(page_title="AI Stock", page_icon="📈", layout="wide")
    inject_styles()

    if "symbol" not in st.session_state:
        st.session_state["symbol"] = ""
    if "collect_symbol" not in st.session_state:
        st.session_state["collect_symbol"] = ""

    menu = render_sidebar()

    if menu == "종목분석":
        render_stock_analysis_page()
    else:
        render_info_collection_page()

    st.divider()
    st.caption("AI Stock — 투자 판단은 본인 책임입니다. 본 시스템은 참고용 분석만 제공합니다.")


if __name__ == "__main__":
    main()
