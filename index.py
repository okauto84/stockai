import streamlit as st

PAGE_DATA_UPDATE = "Data update"
PAGE_ETF = "ETF 추세확인"
PAGE_STOCK = "개별 종목 분석"
PAGE_OPTIONS = [PAGE_DATA_UPDATE, PAGE_ETF, PAGE_STOCK]


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


def apply_query_navigation() -> None:
    """ETF 종목 클릭 시 개별 종목 분석 탭·검색 그리드로 전환"""
    goto = str(st.query_params.get("goto", "")).strip().lower()
    symbol = str(st.query_params.get("symbol", "")).strip().upper()
    if goto != "stock" or not symbol:
        return

    sector = str(st.query_params.get("sector", "")).strip()
    keyword = str(st.query_params.get("keyword", "")).strip()
    if not keyword:
        keyword = symbol.split(".")[0]

    st.session_state["symbol"] = symbol
    st.session_state["nav_page"] = PAGE_STOCK
    # radio 위젯 값과 쿼리 반영 타이밍이 어긋나도 이번 런에서 분석 탭을 강제
    st.session_state["_goto_stock"] = True

    # 종목 검색 그리드에 해당 ETF가 보이도록 필터 반영
    st.session_state["stock_list_market_ui"] = "ETF"
    st.session_state["stock_list_market_applied"] = "ETF"
    if sector:
        st.session_state["stock_list_sector_ui"] = sector
        st.session_state["stock_list_sector_applied"] = sector
    st.session_state["stock_list_keyword_ui"] = keyword
    st.session_state["stock_list_keyword_applied"] = keyword

    # 전체 clear 대신 네비 키만 제거 (다른 쿼리 유지, 재진입 방지)
    for key in ("goto", "symbol", "sector", "keyword"):
        if key in st.query_params:
            del st.query_params[key]


def render_top_bar() -> str:
    """상단 top-bar 탭 메뉴를 렌더하고 선택된 페이지명을 반환"""
    if st.session_state.get("nav_page") not in PAGE_OPTIONS:
        st.session_state["nav_page"] = PAGE_DATA_UPDATE

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


def clear_caches_and_reload_stock_list() -> None:
    """세션 최초 진입 시 캐시를 비우고 kospilist.json을 다시 로드"""
    if st.session_state.get("app_data_reloaded"):
        return

    st.cache_data.clear()
    st.cache_resource.clear()

    import ref_etf
    import ref_stockanly

    ref_etf.load_etf_sector_data.clear()
    ref_stockanly.load_stock_list.clear()
    ref_etf.load_etf_sector_data()
    ref_stockanly.load_stock_list()
    st.session_state["app_data_reloaded"] = True


def main() -> None:
    st.set_page_config(
        page_title="AI Stock",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # set_page_config 이후에 페이지 모듈을 불러와 Streamlit 초기화 충돌을 피함
    import ref_dataupdate
    import ref_etf
    import ref_stockanly

    clear_caches_and_reload_stock_list()
    apply_query_navigation()
    inject_styles()

    if "symbol" not in st.session_state:
        st.session_state["symbol"] = ""

    page = render_top_bar()
    if st.session_state.pop("_goto_stock", False):
        # radio 인스턴스화 이후 session_state[nav_page] 재설정은 금지 → 라우팅만 강제
        page = PAGE_STOCK

    if page == PAGE_DATA_UPDATE:
        ref_dataupdate.render_page()
    elif page == PAGE_ETF:
        ref_etf.render_page()
    elif page == PAGE_STOCK:
        ref_stockanly.render_page()


if __name__ == "__main__":
    main()
