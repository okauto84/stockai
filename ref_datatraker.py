import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
SSL_VERIFY = os.getenv("STOCKAI_SSL_VERIFY", "false").lower() == "true"


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


def collect_stock_data(symbol: str) -> dict:
    """종목 차트·요약 정보 일괄 수집"""
    chart = fetch_chart(symbol)
    summary = fetch_summary(symbol)
    prefix = "₩" if chart["currency"] == "KRW" else "$"

    return {
        "chart": chart,
        "summary": summary,
        "prefix": prefix,
    }


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


def render_page() -> None:
    """정보수집 Streamlit 페이지"""
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
                data = collect_stock_data(symbol)
                chart = data["chart"]
                summary = data["summary"]
                prefix = data["prefix"]

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
