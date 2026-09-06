"""ETF 추세확인 페이지"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

KOSPI_LIST_FILE = (
    Path(__file__).resolve().parent / "data" / "kospilist" / "kospilist.json"
)
MAX_GRID_ROWS = 12


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


def _name_chips_html(names: list[str]) -> str:
    """종목명을 가로 네모박스(칩) HTML로 변환"""
    if not names:
        return '<span class="empty-msg">표시할 ETF가 없습니다.</span>'
    return "".join(
        f'<span class="name-chip">{html.escape(name)}</span>' for name in names
    )


def build_sector_grid_html(
    grid_rows: list[dict], sector_names: dict[str, list[str]]
) -> str:
    """클릭 시 행이 펼쳐지는 HTML 섹터 그리드 생성"""
    body_rows: list[str] = []

    for idx, row in enumerate(grid_rows):
        left_sector = row["left_sector"]
        left_count = row["left_count"]
        right_sector = row["right_sector"]
        right_count = row["right_count"]

        left_cell = (
            f'<td class="sector clickable" data-detail="detail-{idx}-L" '
            f'title="클릭하여 종목 목록 펼치기">{html.escape(left_sector)}</td>'
            if left_sector
            else '<td class="sector"></td>'
        )
        left_count_cell = (
            f'<td class="count">{left_count}</td>'
            if left_count is not None
            else '<td class="count"></td>'
        )
        right_cell = (
            f'<td class="sector clickable" data-detail="detail-{idx}-R" '
            f'title="클릭하여 종목 목록 펼치기">{html.escape(right_sector)}</td>'
            if right_sector
            else '<td class="sector"></td>'
        )
        right_count_cell = (
            f'<td class="count">{right_count}</td>'
            if right_count is not None
            else '<td class="count"></td>'
        )

        left_names = sector_names.get(left_sector, []) if left_sector else []
        right_names = sector_names.get(right_sector, []) if right_sector else []

        body_rows.append(
            f"""
            <tr class="main-row" id="row-{idx}">
              {left_cell}
              {left_count_cell}
              {right_cell}
              {right_count_cell}
            </tr>
            <tr class="detail-row" id="detail-{idx}-L">
              <td colspan="4">
                <div class="detail-wrap">
                  <div class="detail-title">{html.escape(left_sector)} 종목</div>
                  <div class="chip-row">{_name_chips_html(left_names)}</div>
                </div>
              </td>
            </tr>
            <tr class="detail-row" id="detail-{idx}-R">
              <td colspan="4">
                <div class="detail-wrap">
                  <div class="detail-title">{html.escape(right_sector)} 종목</div>
                  <div class="chip-row">{_name_chips_html(right_names)}</div>
                </div>
              </td>
            </tr>
            """
        )

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  :root {{
    --border: #d0d7de;
    --header-bg: #f6f8fa;
    --hover: #eef6ff;
    --active: #dbeafe;
    --chip-bg: #f8fafc;
    --chip-border: #cbd5e1;
    --text: #0f172a;
    --muted: #64748b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 0;
    font-family: "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    font-size: 12px;
    color: var(--text);
    background: transparent;
  }}
  table.sector-grid {{
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    background: #fff;
    font-size: 12px;
  }}
  table.sector-grid th,
  table.sector-grid td {{
    border: 1px solid var(--border);
    padding: 8px 10px;
    vertical-align: middle;
    font-size: 12px;
  }}
  table.sector-grid thead th {{
    background: var(--header-bg);
    font-weight: 700;
    text-align: left;
    font-size: 12px;
  }}
  td.sector {{
    width: 34%;
  }}
  td.count {{
    width: 16%;
    text-align: left;
  }}
  td.clickable {{
    cursor: pointer;
    user-select: none;
    transition: background 0.15s ease;
  }}
  td.clickable:hover {{
    background: var(--hover);
  }}
  td.clickable.active {{
    background: var(--active);
    font-weight: 600;
  }}
  tr.detail-row {{
    display: none;
  }}
  tr.detail-row.open {{
    display: table-row;
  }}
  .detail-wrap {{
    padding: 6px 2px 4px;
  }}
  .detail-title {{
    font-size: 10px;
    color: var(--muted);
    margin-bottom: 8px;
    font-weight: 600;
  }}
  .chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    font-size: 10px;
  }}
  .name-chip {{
    display: inline-block;
    padding: 5px 10px;
    border: 1px solid var(--chip-border);
    border-radius: 6px;
    background: var(--chip-bg);
    white-space: nowrap;
    line-height: 1.3;
    font-size: 10px;
  }}
  .empty-msg {{
    color: var(--muted);
    font-size: 10px;
  }}
</style>
</head>
<body>
  <table class="sector-grid">
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
  <script>
    (function () {{
      function closeAll(exceptId) {{
        document.querySelectorAll("tr.detail-row.open").forEach(function (row) {{
          if (row.id !== exceptId) row.classList.remove("open");
        }});
        document.querySelectorAll("td.clickable.active").forEach(function (cell) {{
          if (cell.getAttribute("data-detail") !== exceptId) {{
            cell.classList.remove("active");
          }}
        }});
      }}

      document.querySelectorAll("td.clickable").forEach(function (cell) {{
        cell.addEventListener("click", function () {{
          var detailId = cell.getAttribute("data-detail");
          var detail = document.getElementById(detailId);
          if (!detail) return;

          var willOpen = !detail.classList.contains("open");
          closeAll(willOpen ? detailId : null);
          detail.classList.toggle("open", willOpen);
          cell.classList.toggle("active", willOpen);

          // iframe 높이를 내용에 맞게 요청 (Streamlit parent가 무시할 수 있음)
          var height = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
          window.parent.postMessage({{ isStreamlitMessage: true, type: "streamlit:setFrameHeight", height: height }}, "*");
        }});
      }});
    }})();
  </script>
</body>
</html>
"""


def render_sector_count_grid() -> None:
    """섹터별 ETF 종목 수 HTML 그리드 표시"""
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

    grid_rows = build_sector_grid_rows(sector_df, MAX_GRID_ROWS)
    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행 · "
        "섹터를 클릭하면 종목명이 가로로 펼쳐집니다"
    )

    # '기타'처럼 종목이 많은 섹터 펼침을 고려해 여유 높이 확보
    max_names = max((len(names) for names in sector_names.values()), default=0)
    estimated_height = 48 + len(grid_rows) * 38 + 120 + min(max_names, 40) * 4
    components.html(
        build_sector_grid_html(grid_rows, sector_names),
        height=max(estimated_height, 720),
        scrolling=True,
    )


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
