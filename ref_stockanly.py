import os
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import requests
import streamlit as st
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

ANALYSIS_DAYS = 150
GRID_VISIBLE_ROWS = 7
RS_WINDOW = 20
GRID_COLUMNS = [
    "날짜",
    "종가",
    "코스피",
    "RS지수",
    "MA10",
    "MA20",
    "MA30",
    "MA50",
    "MA100",
    "MA150",
]
COLOR_STOCK = "#1e3a8a"
COLOR_KOSPI = "#991b1b"
COLOR_RS = "#ea580c"
MA_COLORS = {
    "종가": COLOR_STOCK,
    "MA10": "#22c55e",
    "MA20": "#eab308",
    "MA30": "#a855f7",
    "MA50": "#0d9488",
    "MA100": "#64748b",
    "MA150": "#8b5cf6",
}
MA_LABELS = ["종가", "MA10", "MA20", "MA30", "MA50", "MA100", "MA150"]
MA_WINDOWS = [10, 20, 30, 50, 100, 150]
CHART_HEIGHT = 560
CHART_MONTHS = 3


def chart_x_encoding() -> alt.X:
    """날짜 포맷 X축 (예: 08.31, 연도 미표시)"""
    return alt.X(
        "date:T",
        title="날짜",
        axis=alt.Axis(format="%m.%d", labelAngle=-45),
    )


def fetch_chart(symbol: str, range_period: str = "3mo") -> dict:
    """Yahoo Finance 차트 API로 주가 데이터 수집"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_period, "interval": "1d"}

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


def format_with_comma(value, decimals: int = 0) -> str:
    if pd.isna(value):
        return "-"
    return f"{round(value):,.{decimals}f}" if decimals == 0 else f"{value:,.{decimals}f}"


def format_grid_display(df: pd.DataFrame) -> pd.DataFrame:
    """그리드 숫자 컬럼 천 단위 쉼표 포맷"""
    display = df.copy()
    for col in GRID_COLUMNS:
        if col == "날짜" or col not in display.columns:
            continue
        display[col] = display[col].apply(lambda x: format_with_comma(x))
    return display


def prepare_chart_df(grid_df: pd.DataFrame) -> pd.DataFrame:
    """그리드 DataFrame을 차트용 시계열로 변환"""
    df = grid_df.copy()
    df["date"] = pd.to_datetime(df["날짜"])
    return df.sort_values("date").reset_index(drop=True)


def slice_recent_months(df: pd.DataFrame, months: int = CHART_MONTHS) -> pd.DataFrame:
    """현재 날짜 기준 최근 N개월 데이터만 반환"""
    if df.empty:
        return df
    cutoff = df["date"].max() - pd.DateOffset(months=months)
    return df[df["date"] >= cutoff].reset_index(drop=True)


def render_close_chart(chart_df: pd.DataFrame) -> None:
    """종목 종가 차트"""
    chart = (
        alt.Chart(chart_df)
        .mark_line(color=COLOR_STOCK, strokeWidth=1)
        .encode(
            x=chart_x_encoding(),
            y=alt.Y("종가:Q", title="종가", axis=alt.Axis(format=",.0f")),
        )
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def render_kospi_rs_chart(chart_df: pd.DataFrame) -> None:
    """코스피(좌측)·RS지수(우측) 이중 축 차트"""
    base = alt.Chart(chart_df).encode(x=chart_x_encoding())

    kospi_line = base.mark_line(color=COLOR_KOSPI, strokeWidth=1).encode(
        y=alt.Y(
            "코스피:Q",
            title="코스피",
            axis=alt.Axis(format=",.0f", orient="left"),
        )
    )

    rs_line = base.mark_line(color=COLOR_RS, strokeWidth=1).encode(
        y=alt.Y(
            "RS지수:Q",
            title="RS지수",
            axis=alt.Axis(format=",.0f", orient="right"),
        )
    )

    chart = (
        alt.layer(kospi_line, rs_line)
        .resolve_scale(y="independent")
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def render_ma_chart(chart_df: pd.DataFrame) -> None:
    """종가·이동평균선 차트"""
    long_df = chart_df.melt(
        id_vars=["date"],
        value_vars=MA_LABELS,
        var_name="구분",
        value_name="값",
    ).dropna(subset=["값"])

    chart = (
        alt.Chart(long_df)
        .mark_line(strokeWidth=1)
        .encode(
            x=chart_x_encoding(),
            y=alt.Y("값:Q", title="가격", axis=alt.Axis(format=",.0f")),
            color=alt.Color(
                "구분:N",
                scale=alt.Scale(
                    domain=MA_LABELS,
                    range=[MA_COLORS[label] for label in MA_LABELS],
                ),
                legend=None,
            ),
        )
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def build_analysis_grid(symbol: str, days: int = ANALYSIS_DAYS) -> pd.DataFrame:
    """최근 N거래일 분석 그리드 DataFrame 생성"""
    stock = fetch_chart(symbol, range_period="2y")
    kospi = fetch_chart("^KS11", range_period="2y")

    stock_df = pd.DataFrame(stock["history"]).rename(columns={"close": "종가"})
    kospi_df = pd.DataFrame(kospi["history"])[["date", "close"]].rename(
        columns={"close": "코스피"}
    )

    df = stock_df.merge(kospi_df, on="date", how="inner")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    for window in MA_WINDOWS:
        df[f"MA{window}"] = (
            df["종가"].rolling(window, min_periods=window).mean().round(2)
        )

    stock_ret = df["종가"] / df["종가"].shift(RS_WINDOW)
    kospi_ret = df["코스피"] / df["코스피"].shift(RS_WINDOW)
    df["RS지수"] = ((stock_ret / kospi_ret) * 100).round(2)

    df = df.tail(days).copy()
    df["날짜"] = df["date"].dt.strftime("%Y-%m-%d")
    return df[GRID_COLUMNS].reset_index(drop=True)


def analyze_stock(symbol: str) -> dict:
    """주식 데이터 수집 및 AI 기반 기술적 분석"""
    chart = fetch_chart(symbol)
    summary = fetch_summary(symbol)
    grid = build_analysis_grid(symbol)

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

    st.markdown("### 150일 분석 그리드")
    st.caption(
        f"현재일 기준 최근 {ANALYSIS_DAYS}거래일 · "
        f"RS지수={RS_WINDOW}일 상대강도(코스피 대비 100) · "
        "MA10/20/30/50/100/150"
    )
    grid_df = data["grid"].sort_values("날짜", ascending=False).reset_index(drop=True)
    st.dataframe(
        format_grid_display(grid_df),
        use_container_width=True,
        hide_index=True,
        height=35 * GRID_VISIBLE_ROWS + 38,
    )

    csv = grid_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "그리드 CSV 다운로드",
        data=csv,
        file_name=f"{data['symbol']}_analysis_grid.csv",
        mime="text/csv",
        use_container_width=True,
    )

    chart_df = slice_recent_months(prepare_chart_df(data["grid"]), CHART_MONTHS)

    st.markdown(f"### {CHART_MONTHS}개월 종가 추이")
    st.caption(f"분석 그리드 기반 · 현재일 기준 최근 {CHART_MONTHS}개월 종가")
    render_close_chart(chart_df)

    st.markdown(f"### {CHART_MONTHS}개월 코스피·RS지수")
    st.caption(
        f"분석 그리드 기반 · 최근 {CHART_MONTHS}개월 · "
        f"코스피(좌측) · RS지수(우측, {RS_WINDOW}일 상대강도)"
    )
    render_kospi_rs_chart(chart_df)

    st.markdown(f"### {CHART_MONTHS}개월 종가·이동평균선")
    st.caption(
        f"분석 그리드 기반 · 최근 {CHART_MONTHS}개월 · "
        "종가 · MA10/20/30/50/100/150"
    )
    render_ma_chart(chart_df)

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
