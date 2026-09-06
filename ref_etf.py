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
ETF_LIST_VISIBLE_ROWS = 8


@st.cache_data
def load_etf_sector_data() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """kospilist.json에서 ETF 섹터 집계 및 섹터별 종목 목록 로드"""
    with KOSPI_LIST_FILE.open(encoding="utf-8") as file:
        payload = json.load(file)

    sector_etfs: dict[str, list[dict]] = {}
    for market, items in payload.get("markets", {}).items():
        for item in items:
            if item.get("ETF") != "Y":
                continue
            sector = (item.get("sector") or "").strip() or "기타"
            sector_etfs.setdefault(sector, []).append(
                {
                    "시장": market,
                    "종목코드": item.get("code", ""),
                    "종목명": item.get("name", ""),
                    "야후심볼": item.get("yahoosymbol", ""),
                }
            )

    count_rows = [
        {"섹터": sector, "수": len(etfs)}
        for sector, etfs in sorted(
            sector_etfs.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]
    sector_df = pd.DataFrame(count_rows)

    etf_map: dict[str, pd.DataFrame] = {}
    for sector, etfs in sector_etfs.items():
        etf_df = pd.DataFrame(etfs)
        if etf_df.empty:
            etf_map[sector] = etf_df
            continue
        sort_cols = [col for col in ("종목코드", "종목명") if col in etf_df.columns]
        if sort_cols:
            etf_df = etf_df.sort_values(sort_cols)
        etf_map[sector] = etf_df.reset_index(drop=True)
    return sector_df, etf_map


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


def _toggle_sector_selection(row_idx: int, side: str, sector: str) -> None:
    """같은 섹터를 다시 클릭하면 접고, 아니면 해당 섹터를 펼침"""
    selected = f"{row_idx}|{side}|{sector}"
    if st.session_state.get("etf_sector_expand") == selected:
        st.session_state["etf_sector_expand"] = None
    else:
        st.session_state["etf_sector_expand"] = selected


def _parse_sector_selection() -> tuple[int, str, str] | None:
    """펼침 상태 문자열을 (행, 좌우, 섹터)로 파싱"""
    selected = st.session_state.get("etf_sector_expand")
    if not selected or not isinstance(selected, str):
        return None
    parts = selected.split("|", 2)
    if len(parts) != 3:
        return None
    try:
        row_idx = int(parts[0])
    except ValueError:
        return None
    return row_idx, parts[1], parts[2]


def render_etf_list_expander(sector: str, etf_map: dict[str, pd.DataFrame]) -> None:
    """선택한 섹터의 ETF 목록을 접이식으로 표시"""
    etf_df = etf_map.get(sector, pd.DataFrame())
    label = f"{sector} · ETF {len(etf_df):,}개"
    with st.expander(label, expanded=True):
        if etf_df.empty:
            st.info("해당 섹터에 표시할 ETF가 없습니다.")
            return
        st.dataframe(
            etf_df,
            use_container_width=True,
            hide_index=True,
            height=35 * min(len(etf_df), ETF_LIST_VISIBLE_ROWS) + 38,
        )


def render_sector_count_grid() -> None:
    """섹터별 ETF 종목 수 그리드 및 행별 ETF 목록 표시"""
    if not KOSPI_LIST_FILE.exists():
        st.warning(f"종목 목록 파일을 찾을 수 없습니다: {KOSPI_LIST_FILE}")
        return

    try:
        sector_df, etf_map = load_etf_sector_data()
    except json.JSONDecodeError:
        st.warning("종목 목록 JSON 파일 형식이 올바르지 않습니다.")
        return
    except Exception as exc:
        st.error(f"섹터 집계 중 오류: {exc}")
        return

    if sector_df.empty:
        st.info("표시할 ETF 섹터 데이터가 없습니다.")
        return

    grid_rows = build_sector_grid_rows(sector_df, MAX_GRID_ROWS)
    if "etf_sector_expand" not in st.session_state:
        st.session_state["etf_sector_expand"] = None

    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행 · "
        "섹터를 클릭하면 해당 ETF 목록을 펼칩니다"
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

        c1, c2, c3, c4 = st.columns([3, 1, 3, 1], gap="small")
        with c1:
            if left_sector:
                if st.button(
                    left_sector,
                    key=f"etf_sector_left_{idx}",
                    use_container_width=True,
                ):
                    _toggle_sector_selection(idx, "L", left_sector)
        with c2:
            if left_count is not None:
                st.markdown(
                    f"<div style='padding-top:0.45rem;'>{left_count}</div>",
                    unsafe_allow_html=True,
                )
        with c3:
            if right_sector:
                if st.button(
                    right_sector,
                    key=f"etf_sector_right_{idx}",
                    use_container_width=True,
                ):
                    _toggle_sector_selection(idx, "R", right_sector)
        with c4:
            if right_count is not None:
                st.markdown(
                    f"<div style='padding-top:0.45rem;'>{right_count}</div>",
                    unsafe_allow_html=True,
                )

        selected = _parse_sector_selection()
        if selected and selected[0] == idx:
            render_etf_list_expander(selected[2], etf_map)


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
