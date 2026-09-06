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

# st.dataframe은 중복 컬럼명을 허용하지 않으므로, 표시는 동일하게 보이도록 ZWSP 사용
COL_SECTOR_L = "섹터"
COL_COUNT_L = "수"
COL_SECTOR_R = "섹터\u200b"
COL_COUNT_R = "수\u200b"


@st.cache_data
def load_etf_sector_data() -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """kospilist.json에서 ETF 섹터 집계 및 섹터별 종목명 목록 로드"""
    with KOSPI_LIST_FILE.open(encoding="utf-8") as file:
        payload = json.load(file)

    sector_names: dict[str, list[str]] = {}
    for items in payload.get("markets", {}).values():
        for item in items:
            if item.get("ETF") != "Y":
                continue
            sector = (item.get("sector") or "").strip() or "기타"
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            names = sector_names.setdefault(sector, [])
            if name not in names:
                names.append(name)

    for names in sector_names.values():
        names.sort()

    count_rows = [
        {"섹터": sector, "수": len(names)}
        for sector, names in sorted(
            sector_names.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]
    return pd.DataFrame(count_rows), sector_names


def build_sector_count_grid(
    sector_df: pd.DataFrame, max_rows: int = MAX_GRID_ROWS
) -> pd.DataFrame:
    """섹터·수 목록을 최대 max_rows행의 4열(섹터|수|섹터|수) 그리드로 변환"""
    items = [
        (str(sector), int(count))
        for sector, count in sector_df.itertuples(index=False, name=None)
    ]
    left = items[0::2]
    right = items[1::2]
    row_count = min(max_rows, max(len(left), len(right), 0))

    left_sectors: list[str] = []
    left_counts: list[int | None] = []
    right_sectors: list[str] = []
    right_counts: list[int | None] = []

    for idx in range(row_count):
        if idx < len(left):
            sector, count = left[idx]
            left_sectors.append(sector)
            left_counts.append(count)
        else:
            left_sectors.append("")
            left_counts.append(None)

        if idx < len(right):
            sector, count = right[idx]
            right_sectors.append(sector)
            right_counts.append(count)
        else:
            right_sectors.append("")
            right_counts.append(None)

    return pd.DataFrame(
        {
            COL_SECTOR_L: left_sectors,
            COL_COUNT_L: pd.Series(left_counts, dtype="Int64"),
            COL_SECTOR_R: right_sectors,
            COL_COUNT_R: pd.Series(right_counts, dtype="Int64"),
        }
    )


def render_sector_name_list(sector: str, names: list[str]) -> None:
    """섹터별 종목명만 나열하는 접이식 목록"""
    label = f"{sector} · {len(names):,}개"
    with st.expander(label, expanded=True):
        if not names:
            st.info("해당 섹터에 표시할 ETF가 없습니다.")
            return
        st.markdown("\n".join(f"- {name}" for name in names))


def render_sector_count_grid() -> None:
    """섹터별 ETF 종목 수 그리드 및 선택 행의 종목명 목록 표시"""
    if not KOSPI_LIST_FILE.exists():
        st.warning(f"종목 목록 파일을 찾을 수 없습니다: {KOSPI_LIST_FILE}")
        return

    try:
        sector_df, sector_names = load_etf_sector_data()
    except json.JSONDecodeError:
        st.warning("종목 목록 JSON 파일 형식이 올바르지 않습니다.")
        return
    except Exception as exc:
        st.error(f"섹터 집계 중 오류: {exc}")
        return

    if sector_df.empty:
        st.info("표시할 ETF 섹터 데이터가 없습니다.")
        return

    try:
        grid_df = build_sector_count_grid(sector_df, MAX_GRID_ROWS)
    except Exception as exc:
        st.error(f"섹터 그리드 생성 중 오류: {exc}")
        return

    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_df)}행 · "
        "행을 선택하면 해당 섹터 ETF 종목명을 펼칩니다"
    )

    selection = st.dataframe(
        grid_df,
        use_container_width=True,
        hide_index=True,
        height=35 * (len(grid_df) + 1) + 2,
        on_select="rerun",
        selection_mode="single-row",
        key="etf_sector_grid_selection",
        column_config={
            COL_SECTOR_L: st.column_config.TextColumn("섹터"),
            COL_COUNT_L: st.column_config.NumberColumn("수", format="%d"),
            COL_SECTOR_R: st.column_config.TextColumn("섹터"),
            COL_COUNT_R: st.column_config.NumberColumn("수", format="%d"),
        },
    )

    selected_rows = selection.selection.rows if selection and selection.selection else []
    if not selected_rows:
        return

    row = grid_df.iloc[selected_rows[0]]
    left_sector = str(row[COL_SECTOR_L]).strip()
    right_sector = str(row[COL_SECTOR_R]).strip()

    if left_sector:
        render_sector_name_list(left_sector, sector_names.get(left_sector, []))
    if right_sector:
        render_sector_name_list(right_sector, sector_names.get(right_sector, []))


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
