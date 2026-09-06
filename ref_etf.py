"""ETF 추세확인 페이지"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

KOSPI_LIST_FILE = (
    Path(__file__).resolve().parent / "data" / "kospilist" / "kospilist.json"
)


@st.cache_data
def load_etf_sector_counts() -> pd.DataFrame:
    """kospilist.json에서 ETF 섹터별 종목 수 집계"""
    with KOSPI_LIST_FILE.open(encoding="utf-8") as file:
        payload = json.load(file)

    counts: dict[str, int] = {}
    for items in payload.get("markets", {}).values():
        for item in items:
            if item.get("ETF") != "Y":
                continue
            sector = (item.get("sector") or "").strip() or "기타"
            counts[sector] = counts.get(sector, 0) + 1

    rows = [
        {"섹터": sector, "수": count}
        for sector, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    return pd.DataFrame(rows)


def build_sector_count_grid(sector_df: pd.DataFrame) -> pd.DataFrame:
    """섹터·수 목록을 4열(섹터|수|섹터|수) 그리드로 변환"""
    items = list(sector_df.itertuples(index=False, name=None))
    left = items[0::2]
    right = items[1::2]
    row_count = max(len(left), len(right))

    grid_rows = []
    for idx in range(row_count):
        left_sector, left_count = left[idx] if idx < len(left) else ("", None)
        right_sector, right_count = right[idx] if idx < len(right) else ("", None)
        grid_rows.append(
            [
                left_sector,
                "" if left_count is None else int(left_count),
                right_sector,
                "" if right_count is None else int(right_count),
            ]
        )

    return pd.DataFrame(grid_rows, columns=["섹터", "수", "섹터", "수"])


def render_sector_count_grid() -> None:
    """섹터별 ETF 종목 수 그리드 표시"""
    if not KOSPI_LIST_FILE.exists():
        st.warning(f"종목 목록 파일을 찾을 수 없습니다: {KOSPI_LIST_FILE}")
        return

    try:
        sector_df = load_etf_sector_counts()
    except json.JSONDecodeError:
        st.warning("종목 목록 JSON 파일 형식이 올바르지 않습니다.")
        return

    if sector_df.empty:
        st.info("표시할 ETF 섹터 데이터가 없습니다.")
        return

    grid_df = build_sector_count_grid(sector_df)
    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · ETF {total_etf:,}개"
    )
    st.dataframe(
        grid_df,
        use_container_width=True,
        hide_index=True,
        height=35 * (len(grid_df) + 1) + 2,
    )


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
