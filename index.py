import streamlit as st
import streamlit.components.v1 as components

import ref_etf
import ref_stockanly

PAGE_ETF = "ETF 추세확인"
PAGE_STOCK = "종목분석"
PAGE_OPTIONS = [PAGE_ETF, PAGE_STOCK]


def inject_styles() -> None:
    components.html(
        """
        <style>
        html, body, [class*="css"] {
            font-size: 12px !important;
        }
        .block-container {
            font-size: 12px;
            padding-top: 1rem;
        }
        h1 { font-size: 20px !important; color: #38bdf8 !important; }
        h2 { font-size: 16px !important; }
        h3 { font-size: 13px !important; color: #94a3b8 !important; }
        p, label, span, div, input, button {
            font-size: 12px !important;
        }
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        .top-bar {
            margin-bottom: 0.5rem;
        }
        </style>
        """,
        height=0,
    )


def render_top_bar() -> str:
    """상단 top-bar 메뉴를 렌더하고 선택된 페이지명을 반환"""
    if "sidebar_page" not in st.session_state:
        st.session_state["sidebar_page"] = PAGE_ETF

    st.markdown('<div class="top-bar">', unsafe_allow_html=True)
    st.header("AI Stock")
    for page_name in PAGE_OPTIONS:
        is_active = st.session_state["sidebar_page"] == page_name
        if st.button(
            page_name,
            key=f"nav_{page_name}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["sidebar_page"] = page_name
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    st.divider()

    return st.session_state["sidebar_page"]


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
        st.title(PAGE_ETF)
        ref_etf.render_page()
    elif page == PAGE_STOCK:
        st.title(PAGE_STOCK)
        ref_stockanly.render_page()

    st.divider()


if __name__ == "__main__":
    main()
