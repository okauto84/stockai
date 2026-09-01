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
STOCKEASY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://stockeasy.intellio.kr/stock-analysis/screener",
    "Origin": "https://stockeasy.intellio.kr",
}
SSL_VERIFY = os.getenv("STOCKAI_SSL_VERIFY", "false").lower() == "true"
STOCKEASY_API_BASE = os.getenv(
    "STOCKEASY_API_BASE",
    "https://stockeasy.intellio.kr/stockdata/api/v1/screener",
)
STOCKEASY_LOGIN_URL = os.getenv(
    "STOCKEASY_LOGIN_URL",
    "https://stockeasy.intellio.kr/api/v1/auth/login",
)
STOCKEASY_ID = os.getenv("STOCKEASY_ID", "")
STOCKEASY_PW = os.getenv("STOCKEASY_PW", "")

SCREENER_ITEMS = [
    {
        "label": "강세 선두",
        "preset": "momentum_leader",
        "url": "https://stockeasy.intellio.kr/stock-analysis/screener?preset=momentum_leader",
    },
    {
        "label": "추세 시작",
        "preset": "trend_template",
        "url": "https://stockeasy.intellio.kr/stock-analysis/screener?preset=trend_template",
    },
    {
        "label": "돌파 대기",
        "preset": "vcp_breakout",
        "url": "https://stockeasy.intellio.kr/stock-analysis/screener?preset=vcp_breakout",
    },
]


def _get_credentials() -> tuple[str, str]:
    user_id = os.getenv("STOCKEASY_ID", STOCKEASY_ID).strip()
    password = os.getenv("STOCKEASY_PW", STOCKEASY_PW)
    return user_id, password


def _login_stockeasy(session: requests.Session) -> None:
    """STOCKEASY_ID / STOCKEASY_PW 로 StockEasy 로그인"""
    user_id, password = _get_credentials()
    if not user_id or not password:
        raise PermissionError(
            "StockEasy 로그인 정보가 필요합니다. 환경변수 STOCKEASY_ID, STOCKEASY_PW를 설정하세요."
        )

    login_urls = [
        STOCKEASY_LOGIN_URL,
        "https://stockeasy.intellio.kr/api/v1/auth/login",
        "https://stockeasy.intellio.kr/api/auth/login",
        "https://stockeasy.intellio.kr/api/v1/users/login",
    ]
    payloads = [
        {"email": user_id, "password": password},
        {"username": user_id, "password": password},
        {"id": user_id, "password": password},
    ]

    last_error = "로그인에 실패했습니다."
    seen_urls = set()

    for url in login_urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)

        for payload in payloads:
            res = session.post(url, json=payload, timeout=20)
            if res.status_code in (200, 201, 204):
                if session.cookies or res.cookies:
                    return
                body = res.json() if res.content else {}
                token = body.get("access_token") or body.get("token")
                if token:
                    session.headers["Authorization"] = f"Bearer {token}"
                    return
            elif res.status_code not in (404, 405):
                try:
                    detail = res.json().get("detail", res.text[:120])
                except ValueError:
                    detail = res.text[:120]
                last_error = f"로그인 실패 ({res.status_code}): {detail}"

    raise PermissionError(last_error)


def _stockeasy_session() -> requests.Session:
    cache_key = "stockeasy_auth_session"
    user_id, _ = _get_credentials()

    if cache_key in st.session_state:
        cached_id = st.session_state.get("stockeasy_auth_user", "")
        if cached_id == user_id:
            return st.session_state[cache_key]

    session = requests.Session()
    session.verify = SSL_VERIFY
    session.headers.update(STOCKEASY_HEADERS)
    _login_stockeasy(session)

    st.session_state[cache_key] = session
    st.session_state["stockeasy_auth_user"] = user_id
    return session


def fetch_screener_results(preset: str, limit: int = 50) -> dict:
    """StockEasy 스크리너 API에서 preset별 종목 데이터 수집"""
    session = _stockeasy_session()
    session.get(
        f"https://stockeasy.intellio.kr/stock-analysis/screener?preset={preset}",
        timeout=15,
    )

    params = {
        "preset": preset,
        "offset": 0,
        "limit": limit,
        "fwd_basis": "fy1",
    }
    res = session.get(f"{STOCKEASY_API_BASE}/results", params=params, timeout=20)
    if res.status_code == 401:
        raise PermissionError(
            "StockEasy 인증이 만료되었습니다. STOCKEASY_ID, STOCKEASY_PW를 확인하세요."
        )
    res.raise_for_status()
    return res.json()


def screener_payload_to_dataframe(payload: dict) -> pd.DataFrame:
    """스크리너 API 응답을 DataFrame으로 변환"""
    stocks = payload.get("stocks") or []
    if not stocks:
        return pd.DataFrame()

    if isinstance(stocks[0], dict):
        return pd.DataFrame(stocks)

    columns = payload.get("display_columns") or []
    if columns and isinstance(columns[0], dict):
        headers = [col.get("label") or col.get("key") or f"col_{i}" for i, col in enumerate(columns)]
        return pd.DataFrame(stocks, columns=headers[: len(stocks[0])])

    return pd.DataFrame(stocks)


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


def render_screener_view(item: dict) -> None:
    """선택된 스크리너 항목 화면 표시"""
    st.subheader(item["label"])
    st.caption(item["url"])
    st.link_button("StockEasy에서 열기", item["url"], use_container_width=False)

    with st.spinner(f"{item['label']} 데이터 수집 중..."):
        try:
            payload = fetch_screener_results(item["preset"])
            df = screener_payload_to_dataframe(payload)
            total = payload.get("total_count", len(df))

            st.metric("수집 종목 수", f"{len(df)} / {total}")
            if payload.get("last_updated"):
                st.caption(f"기준 시각: {payload['last_updated']}")

            if df.empty:
                st.info("수집된 종목 데이터가 없습니다.")
            else:
                st.markdown("### 수집 데이터")
                st.dataframe(df, use_container_width=True, hide_index=True)

                csv = df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "CSV 다운로드",
                    data=csv,
                    file_name=f"{item['preset']}_screener.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
        except PermissionError as e:
            st.warning(str(e))
        except Exception as e:
            st.error(f"데이터 수집 오류: {e}")

    st.markdown("### 스크리너 화면")
    components.iframe(item["url"], height=820, scrolling=True)


def render_page() -> None:
    """정보수집 Streamlit 페이지"""
    st.title("정보수집")
    st.caption("StockEasy 스크리너 데이터 수집")

    if "screener_selected" not in st.session_state:
        st.session_state["screener_selected"] = SCREENER_ITEMS[0]["preset"]

    cols = st.columns(len(SCREENER_ITEMS))
    for col, item in zip(cols, SCREENER_ITEMS):
        if col.button(item["label"], use_container_width=True):
            st.session_state["screener_selected"] = item["preset"]

    selected = next(
        item for item in SCREENER_ITEMS
        if item["preset"] == st.session_state["screener_selected"]
    )
    render_screener_view(selected)
