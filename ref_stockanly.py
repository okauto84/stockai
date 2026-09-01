import json
import os
from datetime import datetime, timezone
from pathlib import Path

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
KOSPI_LIST_FILE = (
    Path(__file__).resolve().parent / "data" / "kospilist" / "kospilist.json"
)

ANALYSIS_DAYS = 150
GRID_VISIBLE_ROWS = 7
STOCK_LIST_VISIBLE_ROWS = 5
RS_WINDOW = 20
GRID_COLUMNS = [
    "날짜",
    "종가",
    "거래량",
    "코스피",
    "RS지수",
    "MA10",
    "MA20",
    "MA30",
    "MA50",
    "MA100",
    "MA150",
]
COLOR_GRID_UP = "#dc2626"
COLOR_GRID_DOWN = "#2563eb"
CHANGE_UP = "상승"
CHANGE_DOWN = "하락"
CHANGE_FLAT = "보합"
CHANGE_COLORS = [COLOR_GRID_UP, COLOR_GRID_DOWN, "#94a3b8"]
CHANGE_DOMAIN = [CHANGE_UP, CHANGE_DOWN, CHANGE_FLAT]
COLOR_STOCK = "#1e3a8a"
COLOR_KOSPI = "#991b1b"
COLOR_RS = "#2563eb"
MA_COLORS = {
    "종가": COLOR_GRID_UP,
    "MA10": "#22c55e",
    "MA20": "#eab308",
    "MA30": "#a855f7",
    "MA50": "#0d9488",
    "MA100": "#64748b",
    "MA150": "#8b5cf6",
}
MA_LABELS = ["종가", "MA10", "MA20", "MA30", "MA50", "MA100", "MA150"]
MA_WINDOWS = [10, 20, 30, 50, 100, 150]
CHART_HEIGHT = 373
CHART_MONTHS = 3
CLOSE_PANEL_HEIGHT = 240
VOLUME_PANEL_HEIGHT = 133
LEGEND_BOTTOM = alt.Legend(orient="bottom", direction="horizontal", title=None)
DATE_TOOLTIP = alt.Tooltip("date:T", title="날짜", format="%Y.%m.%d")


def chart_x_encoding(show_labels: bool = True) -> alt.X:
    """날짜 포맷 X축 (예: 08.31, 연도 미표시)"""
    axis = alt.Axis(format="%m.%d", labelAngle=-45, title=None)
    if not show_labels:
        axis = alt.Axis(labels=False, ticks=False, title=None)
    return alt.X("date:T", axis=axis)


def chart_zoom() -> alt.selection_interval:
    """X축 확대/이동 (드래그·휠·더블클릭)"""
    return alt.selection_interval(bind="scales", encodings=["x"])


def y_domain(values: pd.Series, padding_ratio: float = 0.05) -> list[float]:
    """데이터 최소·최대값 기준 Y축 범위"""
    series = values.dropna()
    if series.empty:
        return [0.0, 1.0]

    min_val = float(series.min())
    max_val = float(series.max())
    if min_val == max_val:
        margin = abs(min_val) * padding_ratio or 1.0
        return [min_val - margin, max_val + margin]

    padding = (max_val - min_val) * padding_ratio
    return [min_val, max_val + padding]


def y_encoding(
    field: str,
    title: str,
    values: pd.Series,
    *,
    orient: str | None = None,
) -> alt.Y:
    """최소·최대값 기준 Y축"""
    axis_kwargs: dict = {"format": ",.0f"}
    if orient:
        axis_kwargs["orient"] = orient

    return alt.Y(
        f"{field}:Q",
        title=title,
        scale=alt.Scale(domain=y_domain(values), nice=False),
        axis=alt.Axis(**axis_kwargs),
    )


def finalize_chart(chart: alt.TopLevelSpec) -> alt.TopLevelSpec:
    """차트 확대/이동 인터랙션 적용 (드래그·휠·더블클릭)"""
    return chart.interactive(bind_y=False)


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
    volumes = result[0]["indicators"]["quote"][0]["volume"]

    history = []
    for ts, close, volume in zip(timestamps, closes, volumes):
        if close is not None:
            date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            history.append(
                {
                    "date": date,
                    "close": round(close, 2),
                    "volume": int(volume) if volume is not None else None,
                }
            )

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


def style_analysis_grid(grid_df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """종가·거래량 전일 대비 증감 색상 적용 (상승=빨강, 하락=파랑)"""
    display = format_grid_display(grid_df)
    chronological = grid_df.sort_values("날짜").reset_index(drop=True)

    color_map: dict[tuple[str, str], str] = {}
    for idx in range(1, len(chronological)):
        date = chronological.loc[idx, "날짜"]
        for column in ("종가", "거래량"):
            current = chronological.loc[idx, column]
            previous = chronological.loc[idx - 1, column]
            if pd.isna(current) or pd.isna(previous):
                continue
            if current > previous:
                color_map[(date, column)] = COLOR_GRID_UP
            elif current < previous:
                color_map[(date, column)] = COLOR_GRID_DOWN

    columns = list(display.columns)

    def highlight(row: pd.Series) -> list[str]:
        date = row["날짜"]
        return [
            f"color: {color_map[(date, column)]}"
            if (date, column) in color_map
            else ""
            for column in columns
        ]

    return display.style.apply(highlight, axis=1)


@st.cache_data
def load_stock_list() -> pd.DataFrame:
    """kospilist.json 종목 목록 DataFrame 로드"""
    with KOSPI_LIST_FILE.open(encoding="utf-8") as file:
        payload = json.load(file)

    records = []
    for market, items in payload.get("markets", {}).items():
        for item in items:
            records.append(
                {
                    "시장": market,
                    "종목코드": item["code"],
                    "종목명": item["name"],
                    "야후심볼": item["yahoosymbol"],
                    "ETF": item["ETF"],
                }
            )

    return pd.DataFrame(records)


def apply_stock_list_selection(
    stock_df: pd.DataFrame, selection_state
) -> None:
    """종목 목록 그리드 선택값을 종목 코드 입력란에 반영"""
    if not selection_state or not selection_state.selection.rows:
        return

    selected_row = stock_df.iloc[selection_state.selection.rows[0]]
    st.session_state["symbol"] = selected_row["야후심볼"]


def filter_stock_list(
    stock_df: pd.DataFrame, market_filter: str, keyword: str
) -> pd.DataFrame:
    """시장·키워드 조건으로 종목 목록 필터"""
    filtered_df = stock_df.copy()
    if market_filter == "ETF":
        filtered_df = filtered_df[filtered_df["ETF"] == "Y"]
    elif market_filter != "전체":
        filtered_df = filtered_df[filtered_df["시장"] == market_filter]

    if keyword:
        keyword_upper = keyword.upper()
        filtered_df = filtered_df[
            filtered_df["종목코드"].str.contains(keyword_upper, na=False)
            | filtered_df["종목명"].str.contains(keyword, na=False)
            | filtered_df["야후심볼"].str.contains(keyword_upper, na=False)
        ]

    return filtered_df.reset_index(drop=True)


def render_stock_list_grid() -> None:
    """코스피·코스닥 종목 목록 그리드"""
    if not KOSPI_LIST_FILE.exists():
        st.warning(f"종목 목록 파일을 찾을 수 없습니다: {KOSPI_LIST_FILE}")
        return

    try:
        stock_df = load_stock_list()
    except json.JSONDecodeError:
        st.warning("종목 목록 JSON 파일 형식이 올바르지 않습니다.")
        return

    if "stock_list_market_applied" not in st.session_state:
        st.session_state["stock_list_market_applied"] = "전체"
    if "stock_list_keyword_applied" not in st.session_state:
        st.session_state["stock_list_keyword_applied"] = ""

    market_options = ["전체", "KOSPI", "KOSDAQ", "ETF"]
    with st.form("stock_list_search_form", clear_on_submit=False):
        filter_col1, filter_col2, btn_col = st.columns([1, 3, 1])
        with filter_col1:
            market_filter = st.selectbox(
                "시장",
                options=market_options,
                index=market_options.index(
                    st.session_state["stock_list_market_applied"]
                ),
            )
        with filter_col2:
            keyword = st.text_input(
                "종목 검색",
                value=st.session_state["stock_list_keyword_applied"],
                placeholder="종목코드 또는 종목명 검색",
            )
        with btn_col:
            st.markdown("<div style='height: 1.6rem;'></div>", unsafe_allow_html=True)
            search_clicked = st.form_submit_button("검색", use_container_width=True)

    if search_clicked:
        st.session_state["stock_list_market_applied"] = market_filter
        st.session_state["stock_list_keyword_applied"] = keyword.strip()

    display_df = filter_stock_list(
        stock_df,
        st.session_state["stock_list_market_applied"],
        st.session_state["stock_list_keyword_applied"],
    )

    
    st.caption(
        f"코스피·코스닥 상장 종목 {len(stock_df):,}개 · "
        f"검색 결과 {len(display_df):,}개 · "
        "행을 선택하면 150일 분석 그리드 및 차트가 표시됩니다"
    )
    selection = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=35 * STOCK_LIST_VISIBLE_ROWS + 38,
        on_select="rerun",
        selection_mode="single-row",
        key="stock_list_selection",
    )
    apply_stock_list_selection(display_df, selection)


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


def compare_to_previous(values: pd.Series) -> pd.Series:
    """전일 대비 증감 구분"""
    diff = values.diff()
    return diff.map(
        lambda change: CHANGE_UP
        if change > 0
        else CHANGE_DOWN
        if change < 0
        else CHANGE_FLAT
    )


def build_price_line_segments(chart_df: pd.DataFrame) -> pd.DataFrame:
    """종가 선형 차트용 구간별 증감 데이터"""
    sorted_df = chart_df.sort_values("date").reset_index(drop=True)
    segments = []

    for idx in range(1, len(sorted_df)):
        previous = sorted_df.iloc[idx - 1]
        current = sorted_df.iloc[idx]
        change = compare_to_previous(sorted_df["종가"]).iloc[idx]
        segment_id = f"seg_{idx}"

        for row in (previous, current):
            segments.append(
                {
                    "date": row["date"],
                    "종가": row["종가"],
                    "segment": segment_id,
                    "증감": change,
                }
            )

    return pd.DataFrame(segments)


def build_volume_change_df(chart_df: pd.DataFrame) -> pd.DataFrame:
    """거래량 막대 차트용 증감 데이터"""
    volume_df = chart_df.dropna(subset=["거래량"]).sort_values("date").copy()
    volume_df["증감"] = compare_to_previous(volume_df["거래량"])
    return volume_df.iloc[1:].reset_index(drop=True)


def render_close_chart(chart_df: pd.DataFrame) -> None:
    """종목 종가(상단)·거래량(하단) 차트"""
    price_segments = build_price_line_segments(chart_df)
    volume_df = build_volume_change_df(chart_df)
    price_points = chart_df.sort_values("date")[["date", "종가"]]

    change_scale = alt.Scale(domain=CHANGE_DOMAIN, range=CHANGE_COLORS)
    zoom = chart_zoom()
    price_y = y_encoding("종가", "종가", chart_df["종가"])
    volume_y = y_encoding("거래량", "거래량", volume_df["거래량"])

    price_line = (
        alt.Chart(price_segments)
        .mark_line(strokeWidth=1)
        .encode(
            x=chart_x_encoding(show_labels=False),
            y=price_y,
            color=alt.Color("증감:N", scale=change_scale, legend=LEGEND_BOTTOM),
            detail="segment:N",
        )
    )
    price_hover = (
        alt.Chart(price_points)
        .mark_circle(opacity=0, size=80)
        .encode(
            x=chart_x_encoding(show_labels=False),
            y=price_y,
            tooltip=[
                DATE_TOOLTIP,
                alt.Tooltip("종가:Q", title="종가", format=",.0f"),
            ],
        )
    )
    price_chart = (
        alt.layer(price_line, price_hover)
        .add_params(zoom)
        .properties(height=CLOSE_PANEL_HEIGHT)
    )

    volume_chart = (
        alt.Chart(volume_df)
        .mark_bar(size=3)
        .encode(
            x=chart_x_encoding(show_labels=True),
            y=volume_y,
            color=alt.Color("증감:N", scale=change_scale, legend=LEGEND_BOTTOM),
            tooltip=[
                DATE_TOOLTIP,
                alt.Tooltip("거래량:Q", title="거래량", format=",.0f"),
                alt.Tooltip("증감:N", title="전일대비"),
            ],
        )
        .add_params(zoom)
        .properties(height=VOLUME_PANEL_HEIGHT)
    )

    chart = finalize_chart(
        alt.vconcat(price_chart, volume_chart).resolve_scale(x="shared")
    )
    st.altair_chart(chart, use_container_width=True)


def render_kospi_rs_chart(chart_df: pd.DataFrame) -> None:
    """코스피(좌측)·RS지수(우측) 이중 축 차트"""
    color_scale = alt.Scale(
        domain=["코스피", "RS지수"],
        range=[COLOR_KOSPI, COLOR_RS],
    )

    zoom = chart_zoom()
    kospi_y = y_encoding("코스피", "코스피", chart_df["코스피"], orient="left")
    rs_y = y_encoding("RS지수", "RS지수", chart_df["RS지수"], orient="right")

    kospi_line = (
        alt.Chart(chart_df.assign(구분="코스피"))
        .mark_line(strokeWidth=1)
        .encode(
            x=chart_x_encoding(),
            y=kospi_y,
            color=alt.Color("구분:N", scale=color_scale, legend=LEGEND_BOTTOM),
            tooltip=[
                DATE_TOOLTIP,
                alt.Tooltip("코스피:Q", title="코스피", format=",.0f"),
            ],
        )
    )

    rs_line = (
        alt.Chart(chart_df.assign(구분="RS지수"))
        .mark_line(strokeWidth=1)
        .encode(
            x=chart_x_encoding(),
            y=rs_y,
            color=alt.Color("구분:N", scale=color_scale, legend=None),
            tooltip=[
                DATE_TOOLTIP,
                alt.Tooltip("RS지수:Q", title="RS지수", format=",.0f"),
            ],
        )
    )

    chart = finalize_chart(
        alt.layer(kospi_line, rs_line)
        .add_params(zoom)
        .resolve_scale(y="independent")
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def render_ma_chart(chart_df: pd.DataFrame) -> None:
    """종가·이동평균선 차트 (종가>MA150 구간 빨간 체크 표시)"""
    zoom = chart_zoom()
    all_values = pd.concat([chart_df[col] for col in MA_LABELS], ignore_index=True)
    y_scale = alt.Scale(domain=y_domain(all_values), nice=False)
    price_y = alt.Y(
        "값:Q",
        title="가격",
        scale=y_scale,
        axis=alt.Axis(format=",.0f"),
    )
    close_y = alt.Y(
        "종가:Q",
        title="가격",
        scale=y_scale,
        axis=alt.Axis(format=",.0f"),
    )
    color_scale = alt.Scale(
        domain=MA_LABELS,
        range=[MA_COLORS[label] for label in MA_LABELS],
    )

    long_df = chart_df.melt(
        id_vars=["date"],
        value_vars=MA_LABELS,
        var_name="구분",
        value_name="값",
    ).dropna(subset=["값"])
    ma_only = long_df[long_df["구분"] != "종가"]
    close_only = long_df[long_df["구분"] == "종가"]

    ma_lines = (
        alt.Chart(ma_only)
        .mark_line(strokeWidth=1)
        .encode(
            x=chart_x_encoding(),
            y=price_y,
            color=alt.Color("구분:N", scale=color_scale, legend=LEGEND_BOTTOM),
            tooltip=[
                DATE_TOOLTIP,
                alt.Tooltip("구분:N", title="구분"),
                alt.Tooltip("값:Q", title="값", format=",.0f"),
            ],
        )
    )

    close_line = (
        alt.Chart(close_only)
        .mark_line(strokeWidth=3)
        .encode(
            x=chart_x_encoding(),
            y=price_y,
            color=alt.Color("구분:N", scale=color_scale, legend=None),
            tooltip=[
                DATE_TOOLTIP,
                alt.Tooltip("값:Q", title="종가", format=",.0f"),
            ],
        )
    )

    breakout_df = chart_df[
        chart_df["MA150"].notna() & (chart_df["종가"] > chart_df["MA150"])
    ].copy()
    breakout_df["signal"] = "MA150 상승"

    checks = (
        alt.Chart(breakout_df)
        .mark_text(text="✓", color=COLOR_GRID_UP, fontSize=13, fontWeight="bold", dy=-12)
        .encode(
            x=chart_x_encoding(),
            y=close_y,
            tooltip=[DATE_TOOLTIP, alt.Tooltip("signal:N", title="")],
        )
    )

    chart = finalize_chart(
        alt.layer(ma_lines, close_line, checks)
        .add_params(zoom)
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def build_analysis_grid(symbol: str, days: int = ANALYSIS_DAYS) -> pd.DataFrame:
    """최근 N거래일 분석 그리드 DataFrame 생성"""
    stock = fetch_chart(symbol, range_period="2y")
    kospi = fetch_chart("^KS11", range_period="2y")

    stock_df = pd.DataFrame(stock["history"]).rename(
        columns={"close": "종가", "volume": "거래량"}
    )
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


def get_stock_data(symbol: str) -> dict:
    """선택 종목의 기본 정보 및 150일 분석 그리드 데이터 수집"""
    chart = fetch_chart(symbol)
    summary = fetch_summary(symbol)
    grid = build_analysis_grid(symbol)

    history = chart["history"]
    current = history[-1]["close"]
    prev = history[-2]["close"] if len(history) > 1 else current
    change_pct = ((current - prev) / prev) * 100

    currency = chart["currency"]
    prefix = "₩" if currency == "KRW" else "$"

    return {
        "symbol": chart["symbol"],
        "name": summary.get("name") or chart["name"],
        "price": current,
        "price_prefix": prefix,
        "change_pct": round(change_pct, 2),
        "market_cap": summary.get("market_cap"),
        "pe_ratio": summary.get("pe_ratio"),
        "grid": grid,
    }


def render_stock_detail(data: dict) -> None:
    """선택 종목의 150일 분석 그리드 및 차트 출력"""
    prefix = data["price_prefix"]
    change = data["change_pct"]
    change_label = f"{change:+.2f}%"

    st.subheader(f"{data['name']} ({data['symbol']})")
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("현재가", f"{prefix}{data['price']:,.2f}", change_label)
    metric_col2.metric("시가총액", format_market_cap(data["market_cap"], prefix))
    metric_col3.metric("PER", f"{data['pe_ratio']:.2f}" if data["pe_ratio"] else "-")

    st.markdown("#### 150일 분석 그리드")
    st.caption(
        f"현재일 기준 최근 {ANALYSIS_DAYS}거래일 · "
        f"RS지수={RS_WINDOW}일 상대강도(코스피 대비 100) · "
        "MA10/20/30/50/100/150"
    )
    grid_df = data["grid"].sort_values("날짜", ascending=False).reset_index(drop=True)
    st.dataframe(
        style_analysis_grid(grid_df),
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

    st.markdown(f"#### {CHART_MONTHS}개월 종가 추이")
    st.caption(
        f"분석 그리드 기반 · 최근 {CHART_MONTHS}개월 · "
        "상단 종가 · 하단 거래량"
    )
    render_close_chart(chart_df)

    st.markdown(f"#### {CHART_MONTHS}개월 코스피·RS지수")
    st.caption(
        f"분석 그리드 기반 · 최근 {CHART_MONTHS}개월 · "
        f"코스피(좌측) · RS지수(우측, {RS_WINDOW}일 상대강도)"
    )
    render_kospi_rs_chart(chart_df)

    st.markdown(f"#### {CHART_MONTHS}개월 종가·이동평균선")
    st.caption(
        f"분석 그리드 기반 · 최근 {CHART_MONTHS}개월 · "
        "종가 · MA10/20/30/50/100/150"
    )
    render_ma_chart(chart_df)


def render_page() -> None:
    """종목분석 Streamlit 페이지"""
    st.caption("종목 선택 시 150일 분석 그리드 및 차트를 표시합니다")

    render_stock_list_grid()

    symbol = st.session_state.get("symbol", "").strip().upper()
    if symbol:
        with st.spinner("데이터 불러오는 중..."):
            try:
                result = get_stock_data(symbol)
                render_stock_detail(result)
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"데이터 조회 중 오류: {e}")
