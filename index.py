import streamlit as st

import ref_etf
import ref_stockanly

PAGE_ETF = "ETF 추세확인"
PAGE_STOCK = "종목분석"
PAGE_OPTIONS = [PAGE_ETF, PAGE_STOCK]


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {
            font-size: 12px !important;
        }
        /* Streamlit 기본 상단 헤더·사이드바 숨김 */
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        header[data-testid="stHeader"] {
            display: none !important;
        }
        /* top-bar를 최상단에 여백 없이 배치 */
        .block-container {
            font-size: 12px;
            padding-top: 0 !important;
            padding-bottom: 1rem;
            max-width: 100%;
        }
        div[data-testid="stAppViewContainer"] > .main {
            padding-top: 0 !important;
        }
        section.main > div {
            padding-top: 0 !important;
        }
        h1 { font-size: 20px !important; color: #38bdf8 !important; }
        h2 { font-size: 16px !important; }
        h3 { font-size: 13px !important; color: #94a3b8 !important; }
        p, label, span, div, input, button {
            font-size: 12px !important;
        }
        /* 상단 탭 메뉴 스타일 */
        .top-bar-title {
            font-size: 18px !important;
            font-weight: 700;
            color: #38bdf8;
            line-height: 2.4rem;
            margin: 0;
            white-space: nowrap;
        }
        div[data-testid="stRadio"] > label {
            display: none;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] {
            gap: 0 !important;
            border-bottom: 1px solid rgba(148, 163, 184, 0.35);
            flex-wrap: nowrap;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] label {
            display: inline-flex !important;
            align-items: center;
            justify-content: center;
            min-height: 2.4rem;
            margin: 0 !important;
            padding: 0.45rem 1.1rem !important;
            border: none !important;
            border-bottom: 2px solid transparent !important;
            border-radius: 0 !important;
            background: transparent !important;
            color: #94a3b8 !important;
            font-weight: 600;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] label:hover {
            color: #e2e8f0 !important;
            background: rgba(148, 163, 184, 0.08) !important;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] label[data-checked="true"],
        div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
            color: #38bdf8 !important;
            border-bottom-color: #38bdf8 !important;
            background: transparent !important;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] label p {
            font-size: 13px !important;
            font-weight: 600 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_top_bar() -> str:
    """상단 top-bar 탭 메뉴를 렌더하고 선택된 페이지명을 반환"""
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PAGE_ETF

    brand_col, tab_col = st.columns([1.2, 6])
    with brand_col:
        st.markdown('<p class="top-bar-title">AI Stock</p>', unsafe_allow_html=True)
    with tab_col:
        page = st.radio(
            "메뉴",
            options=PAGE_OPTIONS,
            horizontal=True,
            key="nav_page",
            label_visibility="collapsed",
        )
    return page


def main() -> None:
    st.set_page_config(
        page_title="AI Stock",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_styles()

    if "symbol" not in st.session_state:
        st.session_state["symbol"] = ""

    page = render_top_bar()

    if page == PAGE_ETF:
        ref_etf.render_page()
    elif page == PAGE_STOCK:
        ref_stockanly.render_page()


if __name__ == "__main__":
    main()
