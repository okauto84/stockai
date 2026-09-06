"""ETF 추세확인 페이지"""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

KOSPI_LIST_FILE = (
    Path(__file__).resolve().parent / "data" / "kospilist" / "kospilist.json"
)
MAX_GRID_ROWS = 12


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
            code = str(item.get("code", "")).strip()
            if not name or not symbol:
                continue
            used = seen.setdefault(sector, set())
            if symbol in used:
                continue
            used.add(symbol)
            sector_etfs.setdefault(sector, []).append(
                {
                    "name": name,
                    "yahoosymbol": symbol,
                    "code": code,
                }
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


def _stock_link(etf: dict[str, str], sector: str) -> str:
    """개별 종목 분석 탭 이동용 링크 생성"""
    query = urlencode(
        {
            "goto": "stock",
            "symbol": etf["yahoosymbol"],
            "sector": sector,
            "keyword": etf.get("code") or etf["name"],
        }
    )
    name = html.escape(etf["name"])
    symbol = html.escape(etf["yahoosymbol"])
    return (
        f'<a class="name-chip" href="?{query}" '
        f'title="{symbol} 분석 보기">{name}</a>'
    )


def _name_chips_html(etfs: list[dict[str, str]], sector: str) -> str:
    """종목명을 네모박스(칩) 링크 HTML로 변환"""
    if not etfs:
        return '<span class="empty-msg">표시할 ETF가 없습니다.</span>'
    return "".join(_stock_link(etf, sector) for etf in etfs)


def _sector_cell_html(
    sector: str,
    sector_etfs: dict[str, list[dict[str, str]]],
) -> str:
    """섹터 클릭(details) 시 하단에 종목 칩 목록이 펼쳐지는 셀"""
    if not sector:
        return '<td class="sector"></td>'

    etfs = sector_etfs.get(sector, [])
    return (
        f'<td class="sector">'
        f"<details>"
        f"<summary>{html.escape(sector)}</summary>"
        f'<div class="detail-wrap">'
        f'<div class="detail-title">{html.escape(sector)} 종목 · 클릭 시 개별 분석</div>'
        f'<div class="chip-row">{_name_chips_html(etfs, sector)}</div>'
        f"</div>"
        f"</details>"
        f"</td>"
    )


def build_sector_grid_html(
    grid_rows: list[dict],
    sector_etfs: dict[str, list[dict[str, str]]],
) -> str:
    """HTML 섹터 그리드 (섹터 클릭 펼침 + 종목 링크)"""
    body_rows: list[str] = []
    for row in grid_rows:
        left_sector = row["left_sector"]
        left_count = row["left_count"]
        right_sector = row["right_sector"]
        right_count = row["right_count"]

        left_count_cell = (
            f'<td class="count">{left_count}</td>'
            if left_count is not None
            else '<td class="count"></td>'
        )
        right_count_cell = (
            f'<td class="count">{right_count}</td>'
            if right_count is not None
            else '<td class="count"></td>'
        )

        body_rows.append(
            "<tr>"
            f"{_sector_cell_html(left_sector, sector_etfs)}"
            f"{left_count_cell}"
            f"{_sector_cell_html(right_sector, sector_etfs)}"
            f"{right_count_cell}"
            "</tr>"
        )

    return f"""
<style>
  .etf-sector-grid-wrap {{
    width: 100%;
    overflow-x: auto;
    margin-bottom: 0.5rem;
  }}
  table.etf-sector-grid {{
    width: 100%;
    border-collapse: collapse;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    overflow: hidden;
    background: #fff;
    font-size: 12px;
    color: #0f172a;
  }}
  table.etf-sector-grid th,
  table.etf-sector-grid td {{
    border: 1px solid #d0d7de;
    padding: 8px 10px;
    vertical-align: top;
    font-size: 12px;
  }}
  table.etf-sector-grid thead th {{
    background: #f6f8fa;
    font-weight: 700;
    text-align: left;
  }}
  table.etf-sector-grid td.sector {{
    width: 34%;
  }}
  table.etf-sector-grid td.count {{
    width: 16%;
    vertical-align: middle;
  }}
  table.etf-sector-grid details > summary {{
    cursor: pointer;
    list-style: none;
    font-weight: 600;
    user-select: none;
  }}
  table.etf-sector-grid details > summary::-webkit-details-marker {{
    display: none;
  }}
  table.etf-sector-grid details > summary::before {{
    content: "▸ ";
    color: #64748b;
  }}
  table.etf-sector-grid details[open] > summary::before {{
    content: "▾ ";
  }}
  table.etf-sector-grid details[open] > summary {{
    color: #2563eb;
    margin-bottom: 6px;
  }}
  .detail-wrap {{
    padding: 4px 0 2px;
  }}
  .detail-title {{
    font-size: 10px;
    color: #64748b;
    margin-bottom: 8px;
    font-weight: 600;
  }}
  .chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }}
  a.name-chip {{
    display: inline-block;
    padding: 5px 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #f8fafc;
    color: #0f172a !important;
    text-decoration: none !important;
    white-space: nowrap;
    line-height: 1.3;
    font-size: 10px;
  }}
  a.name-chip:hover {{
    background: #dbeafe;
    border-color: #93c5fd;
  }}
  .empty-msg {{
    color: #64748b;
    font-size: 10px;
  }}
</style>
<div class="etf-sector-grid-wrap">
  <table class="etf-sector-grid">
    <thead>
      <tr>
        <th>섹터</th>
        <th>수</th>
        <th>섹터</th>
        <th>수</th>
      </tr>
    </thead>
    <tbody>
      {"".join(body_rows)}
    </tbody>
  </table>
</div>
"""


def render_sector_count_grid() -> None:
    """섹터별 ETF 종목 수 HTML 그리드 표시"""
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

    grid_rows = build_sector_grid_rows(sector_df, MAX_GRID_ROWS)
    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행 · "
        "섹터 클릭 시 종목 목록 · 종목 클릭 시 개별 종목 분석"
    )
    st.markdown(
        build_sector_grid_html(grid_rows, sector_etfs),
        unsafe_allow_html=True,
    )


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
