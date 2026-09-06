"""ETF 추세확인 페이지"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

KOSPI_LIST_FILE = (
    Path(__file__).resolve().parent / "data" / "kospilist" / "kospilist.json"
)
MAX_GRID_ROWS = 12
PAGE_STOCK = "개별 종목 분석"


@st.cache_data
def load_etf_sector_data() -> tuple[pd.DataFrame, dict[str, list[dict[str, str]]]]:
    """kospilist.json에서 ETF 섹터 집계 및 섹터별 종목(이름·심볼) 목록 로드"""
    with KOSPI_LIST_FILE.open(encoding="utf-8") as file:
        payload = json.load(file)

    sector_etfs: dict[str, list[dict[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for items in payload.get("markets", {}).values():
        for item in items:
            if item.get("ETF") != "Y":
                continue
            sector = (item.get("sector") or "").strip() or "기타"
            name = str(item.get("name", "")).strip()
            symbol = str(item.get("yahoosymbol", "")).strip()
            if not name or not symbol:
                continue
            used = seen.setdefault(sector, set())
            if symbol in used:
                continue
            used.add(symbol)
            sector_etfs.setdefault(sector, []).append(
                {"name": name, "yahoosymbol": symbol}
            )

    for etfs in sector_etfs.values():
        etfs.sort(key=lambda row: row["name"])

    count_rows = [
        {"섹터": sector, "수": len(etfs)}
        for sector, etfs in sorted(
            sector_etfs.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]
    return pd.DataFrame(count_rows), sector_etfs


def build_sector_grid_rows(
    sector_df: pd.DataFrame, max_rows: int = MAX_GRID_ROWS
) -> list[dict]:
    """섹터·수 목록을 최대 max_rows행의 좌·우 쌍으로 변환"""
    items = [
        (str(sector), int(count))
        for sector, count in sector_df.itertuples(index=False, name=None)
    ]
    left = items[0::2]
    right = items[1::2]
    row_count = min(max_rows, max(len(left), len(right), 0))

    rows: list[dict] = []
    for idx in range(row_count):
        left_item = left[idx] if idx < len(left) else ("", None)
        right_item = right[idx] if idx < len(right) else ("", None)
        rows.append(
            {
                "left_sector": left_item[0],
                "left_count": left_item[1],
                "right_sector": right_item[0],
                "right_count": right_item[1],
            }
        )
    return rows


def open_stock_analysis(symbol: str) -> None:
    """개별 종목 분석 탭으로 이동하고 150일 분석 그리드/차트를 표시"""
    st.session_state["symbol"] = symbol.strip().upper()
    st.session_state["nav_page"] = PAGE_STOCK
    st.rerun()


def toggle_sector_expand(row_idx: int, side: str, sector: str) -> None:
    """섹터 행 펼침/접기 토글"""
    key = f"{row_idx}|{side}|{sector}"
    if st.session_state.get("etf_expanded_key") == key:
        st.session_state["etf_expanded_key"] = None
        st.session_state["etf_expanded_sector"] = None
    else:
        st.session_state["etf_expanded_key"] = key
        st.session_state["etf_expanded_sector"] = sector


def inject_etf_grid_styles() -> None:
    """섹터 그리드·종목 칩 스타일"""
    st.markdown(
        """
        <style>
        .etf-chip-wrap {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin: 0.35rem 0 0.75rem 0;
        }
        div[data-testid="stHorizontalBlock"] button[kind="secondary"] p,
        div[data-testid="stHorizontalBlock"] button[kind="primary"] p {
            font-size: 12px !important;
        }
        div.etf-chip-row button {
            font-size: 10px !important;
        }
        div.etf-chip-row button p {
            font-size: 10px !important;
            white-space: nowrap;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_etf_name_chips(etfs: list[dict[str, str]], sector: str) -> None:
    """펼쳐진 섹터의 ETF 종목명을 클릭 가능한 칩으로 표시"""
    st.caption(f"{sector} 종목 · 클릭 시 개별 종목 분석")
    if not etfs:
        st.info("표시할 ETF가 없습니다.")
        return

    # 한 줄에 여러 칩이 오도록 다열 배치
    cols_per_row = 4
    for start in range(0, len(etfs), cols_per_row):
        chunk = etfs[start : start + cols_per_row]
        cols = st.columns(cols_per_row, gap="small")
        for col, etf in zip(cols, chunk):
            with col:
                if st.button(
                    etf["name"],
                    key=f"etf_chip_{sector}_{etf['yahoosymbol']}",
                    use_container_width=True,
                    help=f"{etf['yahoosymbol']} 분석 보기",
                ):
                    open_stock_analysis(etf["yahoosymbol"])


def render_sector_count_grid() -> None:
    """섹터별 ETF 종목 수 그리드 및 종목 클릭 분석 이동"""
    if not KOSPI_LIST_FILE.exists():
        st.warning(f"종목 목록 파일을 찾을 수 없습니다: {KOSPI_LIST_FILE}")
        return

    try:
        sector_df, sector_etfs = load_etf_sector_data()
    except json.JSONDecodeError:
        st.warning("종목 목록 JSON 파일 형식이 올바르지 않습니다.")
        return
    except Exception as exc:
        st.error(f"섹터 집계 중 오류: {exc}")
        return

    if sector_df.empty:
        st.info("표시할 ETF 섹터 데이터가 없습니다.")
        return

    if "etf_expanded_key" not in st.session_state:
        st.session_state["etf_expanded_key"] = None
    if "etf_expanded_sector" not in st.session_state:
        st.session_state["etf_expanded_sector"] = None

    inject_etf_grid_styles()

    grid_rows = build_sector_grid_rows(sector_df, MAX_GRID_ROWS)
    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행 · "
        "섹터 클릭 시 종목 목록 · 종목 클릭 시 개별 종목 분석"
    )

    header = st.columns([3, 1, 3, 1], gap="small")
    header[0].markdown("**섹터**")
    header[1].markdown("**수**")
    header[2].markdown("**섹터**")
    header[3].markdown("**수**")

    for idx, row in enumerate(grid_rows):
        left_sector = row["left_sector"]
        left_count = row["left_count"]
        right_sector = row["right_sector"]
        right_count = row["right_count"]

        left_key = f"{idx}|L|{left_sector}" if left_sector else ""
        right_key = f"{idx}|R|{right_sector}" if right_sector else ""
        expanded_key = st.session_state.get("etf_expanded_key")

        c1, c2, c3, c4 = st.columns([3, 1, 3, 1], gap="small")
        with c1:
            if left_sector:
                if st.button(
                    left_sector,
                    key=f"etf_sector_left_{idx}",
                    use_container_width=True,
                    type="primary" if expanded_key == left_key else "secondary",
                ):
                    toggle_sector_expand(idx, "L", left_sector)
                    st.rerun()
        with c2:
            if left_count is not None:
                st.markdown(
                    f"<div style='padding-top:0.45rem; font-size:12px;'>{left_count}</div>",
                    unsafe_allow_html=True,
                )
        with c3:
            if right_sector:
                if st.button(
                    right_sector,
                    key=f"etf_sector_right_{idx}",
                    use_container_width=True,
                    type="primary" if expanded_key == right_key else "secondary",
                ):
                    toggle_sector_expand(idx, "R", right_sector)
                    st.rerun()
        with c4:
            if right_count is not None:
                st.markdown(
                    f"<div style='padding-top:0.45rem; font-size:12px;'>{right_count}</div>",
                    unsafe_allow_html=True,
                )

        if expanded_key == left_key and left_sector:
            render_etf_name_chips(sector_etfs.get(left_sector, []), left_sector)
        elif expanded_key == right_key and right_sector:
            render_etf_name_chips(sector_etfs.get(right_sector, []), right_sector)


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
