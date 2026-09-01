import streamlit as st
import streamlit.components.v1 as components

import ref_datatraker
import ref_stockanly


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


def render_sidebar() -> str:
    with st.sidebar:
        st.header("AI Stock")
        return st.radio(
            "메뉴",
            ["종목분석", "정보수집"],
            label_visibility="collapsed",
        )


def main() -> None:
    st.set_page_config(page_title="AI Stock", page_icon="📈", layout="wide")
    inject_styles()

    if "symbol" not in st.session_state:
        st.session_state["symbol"] = ""
    if "collect_symbol" not in st.session_state:
        st.session_state["collect_symbol"] = ""

    menu = render_sidebar()

    if menu == "종목분석":
        ref_stockanly.render_page()
    else:
        ref_datatraker.render_page()

    st.divider()
    st.caption("AI Stock — 투자 판단은 본인 책임입니다. 본 시스템은 참고용 분석만 제공합니다.")


if __name__ == "__main__":
    main()
