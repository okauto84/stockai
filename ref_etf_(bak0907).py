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


def _stock_chip(etf: dict[str, str], sector: str) -> str:
    """개별 종목 분석 탭 이동용 칩(동일 창) HTML 생성"""
    name = html.escape(etf["name"])
    symbol = html.escape(etf["yahoosymbol"], quote=True)
    sector_q = html.escape(sector, quote=True)
    keyword = html.escape(etf.get("code") or etf["name"], quote=True)
    return (
        f'<span class="name-chip" role="button" tabindex="0" '
        f'data-symbol="{symbol}" data-sector="{sector_q}" '
        f'data-keyword="{keyword}" title="{symbol} 분석 보기">{name}</span>'
    )


def _name_chips_html(etfs: list[dict[str, str]], sector: str) -> str:
    """종목명을 네모박스(칩) HTML로 변환"""
    if not etfs:
        return '<span class="empty-msg">표시할 ETF가 없습니다.</span>'
    return "".join(_stock_chip(etf, sector) for etf in etfs)


def _sector_toggle_cell_html(sector: str, expand_id: str) -> str:
    """섹터명 클릭 토글 셀 (목록은 아래 전체 행에서 표시)"""
    if not sector:
        return '<td class="sector"></td>'

    return (
        f'<td class="sector">'
        f'<button type="button" class="sector-toggle" '
        f'data-expand="{html.escape(expand_id, quote=True)}" '
        f'aria-expanded="false">'
        f"{html.escape(sector)}"
        f"</button>"
        f"</td>"
    )


def _sector_expand_row_html(
    sector: str,
    expand_id: str,
    sector_etfs: dict[str, list[dict[str, str]]],
) -> str:
    """섹터 클릭 시 그리드 한 줄(row) 전체를 차지하는 ETF 목록 행"""
    if not sector:
        return ""

    etfs = sector_etfs.get(sector, [])
    return (
        f'<tr id="{html.escape(expand_id, quote=True)}" '
        f'class="etf-expand-row" hidden>'
        f'<td colspan="4" class="expand-cell">'
        f'<div class="detail-wrap">'
        f'<div class="detail-title">'
        f"{html.escape(sector)} 종목 · 클릭 시 개별 분석"
        f"</div>"
        f'<div class="chip-row">{_name_chips_html(etfs, sector)}</div>'
        f"</div>"
        f"</td>"
        f"</tr>"
    )


def build_sector_grid_html(
    grid_rows: list[dict],
    sector_etfs: dict[str, list[dict[str, str]]],
) -> str:
    """HTML 섹터 그리드 (섹터 클릭 시 전체 행으로 종목 목록 펼침)"""
    body_rows: list[str] = []
    for row_idx, row in enumerate(grid_rows):
        left_sector = row["left_sector"]
        left_count = row["left_count"]
        right_sector = row["right_sector"]
        right_count = row["right_count"]
        left_expand_id = f"etf-exp-{row_idx}-L"
        right_expand_id = f"etf-exp-{row_idx}-R"

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
            "<tr class=\"pair-row\">"
            f"{_sector_toggle_cell_html(left_sector, left_expand_id)}"
            f"{left_count_cell}"
            f"{_sector_toggle_cell_html(right_sector, right_expand_id)}"
            f"{right_count_cell}"
            "</tr>"
        )
        body_rows.append(
            _sector_expand_row_html(left_sector, left_expand_id, sector_etfs)
        )
        body_rows.append(
            _sector_expand_row_html(right_sector, right_expand_id, sector_etfs)
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
  table.etf-sector-grid button.sector-toggle {{
    display: inline;
    margin: 0;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    text-align: left;
    user-select: none;
  }}
  table.etf-sector-grid button.sector-toggle::before {{
    content: "▸ ";
    color: #64748b;
  }}
  table.etf-sector-grid button.sector-toggle[aria-expanded="true"] {{
    color: #2563eb;
  }}
  table.etf-sector-grid button.sector-toggle[aria-expanded="true"]::before {{
    content: "▾ ";
  }}
  table.etf-sector-grid tr.etf-expand-row td.expand-cell {{
    background: #f8fafc;
    padding: 10px 12px 12px;
  }}
  .detail-wrap {{
    padding: 2px 0;
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
  span.name-chip {{
    display: inline-block;
    padding: 5px 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #0f172a !important;
    text-decoration: none !important;
    white-space: nowrap;
    line-height: 1.3;
    font-size: 10px;
    cursor: pointer;
    user-select: none;
  }}
  span.name-chip:hover {{
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


def install_same_window_chip_navigation() -> None:
    """섹터 펼침 + 종목 칩 동일 창 이동 핸들러 설치"""
    components.html(
        """
        <script>
        (function () {
          const parentWin = window.parent;
          const parentDoc = parentWin.document;

          // 부모 문서에서 실행되는 핸들러를 주입해 동일 창 이동·섹터 펼침을 보장
          const script = parentDoc.createElement('script');
          script.textContent = `
            (function () {
              if (window.__etfGridHandlersInstalled) return;
              window.__etfGridHandlersInstalled = true;

              function closeAllExpands(exceptId) {
                document.querySelectorAll('tr.etf-expand-row').forEach(function (row) {
                  if (exceptId && row.id === exceptId) return;
                  row.hidden = true;
                });
                document.querySelectorAll('button.sector-toggle[aria-expanded="true"]')
                  .forEach(function (btn) {
                    if (exceptId && btn.getAttribute('data-expand') === exceptId) return;
                    btn.setAttribute('aria-expanded', 'false');
                  });
              }

              function bindSectorToggles(root) {
                root.querySelectorAll('button.sector-toggle[data-expand]').forEach(function (btn) {
                  if (btn.dataset.toggleBound === '1') return;
                  btn.dataset.toggleBound = '1';
                  btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const expandId = btn.getAttribute('data-expand') || '';
                    const row = expandId ? document.getElementById(expandId) : null;
                    if (!row) return;
                    const willOpen = row.hidden;
                    closeAllExpands(willOpen ? expandId : null);
                    row.hidden = !willOpen;
                    btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
                  });
                });
              }

              function bindChips(root) {
                root.querySelectorAll('span.name-chip[data-symbol]').forEach(function (chip) {
                  if (chip.dataset.navBound === '1') return;
                  chip.dataset.navBound = '1';
                  chip.style.cursor = 'pointer';
                  function go() {
                    const symbol = chip.getAttribute('data-symbol') || '';
                    const sector = chip.getAttribute('data-sector') || '';
                    const keyword = chip.getAttribute('data-keyword') || '';
                    if (!symbol) return;
                    const url = new URL(window.location.href);
                    url.searchParams.set('goto', 'stock');
                    url.searchParams.set('symbol', symbol);
                    url.searchParams.set('sector', sector);
                    url.searchParams.set('keyword', keyword);
                    window.location.assign(url.toString());
                  }
                  chip.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    go();
                  }, true);
                  chip.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      go();
                    }
                  });
                });
              }

              function bindAll() {
                bindSectorToggles(document);
                bindChips(document);
              }

              bindAll();
              new MutationObserver(function () { bindAll(); })
                .observe(document.body, { childList: true, subtree: true });
            })();
          `;
          parentDoc.head.appendChild(script);
        })();
        </script>
        """,
        height=0,
    )


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
    install_same_window_chip_navigation()


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
