"""ETF 추세확인 페이지"""

from __future__ import annotations

import html
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ref_stockanly

ROOT_DIR = Path(__file__).resolve().parent
KOSPI_LIST_FILE = ROOT_DIR / "data" / "kospilist" / "kospilist.json"
ETF_DATA_DIR = ROOT_DIR / "data" / "etf"
MAX_GRID_ROWS = 12
UPDATE_LOOKBACK_DAYS = 3
API_SLEEP_SECONDS = 1
SECTOR_FILE_SLEEP_SECONDS = 2
KOSPI_SYMBOL = "^KS11"
GRID_COLUMNS = list(ref_stockanly.GRID_COLUMNS)
CHART_LOOKBACK_DAYS = 70
CHART_X_TICK_COUNT = 14


def sector_to_filename(sector: str) -> str:
    """섹터명을 파일시스템 안전한 파일명으로 변환"""
    safe = (
        sector.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("*", "_")
        .replace("?", "_")
        .replace('"', "_")
        .replace("<", "_")
        .replace(">", "_")
        .replace("|", "_")
    )
    return f"{safe}.json"


def sector_json_path(sector: str) -> Path:
    """섹터 JSON 파일 경로"""
    return ETF_DATA_DIR / sector_to_filename(sector)


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


_CHART_COLORS = [
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#ca8a04",
    "#9333ea",
    "#0891b2",
    "#ea580c",
    "#4f46e5",
    "#db2777",
    "#059669",
    "#7c3aed",
    "#0284c7",
]


def _etf_color_map(names: list[str]) -> dict[str, str]:
    """ETF 종목명 → 범례/칩/차트 공통 색상"""
    return {
        name: _CHART_COLORS[idx % len(_CHART_COLORS)]
        for idx, name in enumerate(names)
    }


def _stock_chip(
    etf: dict[str, str],
    sector: str,
    *,
    color: str | None = None,
) -> str:
    """개별 종목 분석 탭 이동용 칩(동일 창) HTML 생성"""
    name = html.escape(etf["name"])
    symbol = html.escape(etf["yahoosymbol"], quote=True)
    sector_q = html.escape(sector, quote=True)
    keyword = html.escape(etf.get("code") or etf["name"], quote=True)
    swatch = ""
    if color:
        swatch = (
            f'<i class="chip-swatch" style="background:{html.escape(color, quote=True)}"></i>'
        )
    return (
        f'<span class="name-chip" role="button" tabindex="0" '
        f'data-symbol="{symbol}" data-sector="{sector_q}" '
        f'data-keyword="{keyword}" title="{symbol} 분석 보기">'
        f"{swatch}{name}</span>"
    )


def _name_chips_html(
    etfs: list[dict[str, str]],
    sector: str,
    *,
    color_map: dict[str, str] | None = None,
) -> str:
    """종목명을 네모박스(칩) HTML로 변환"""
    if not etfs:
        return '<span class="empty-msg">표시할 ETF가 없습니다.</span>'
    colors = color_map or {}
    return "".join(
        _stock_chip(etf, sector, color=colors.get(etf["name"])) for etf in etfs
    )


def _sector_toggle_cell_html(sector: str, expand_id: str) -> str:
    """섹터명 클릭 토글 셀 (목록·차트는 아래 전체 행에서 표시)"""
    if not sector:
        return '<td class="sector"></td>'

    return (
        f'<td class="sector">'
        f'<button type="button" class="sector-toggle" '
        f'data-expand="{html.escape(expand_id, quote=True)}" '
        f'data-sector="{html.escape(sector, quote=True)}" '
        f'aria-expanded="false">'
        f"{html.escape(sector)}"
        f"</button>"
        f"</td>"
    )


def _chips_from_payload(payload: dict, sector: str) -> list[dict[str, str]]:
    """섹터 JSON payload에서 칩용 ETF 목록 생성"""
    chips: list[dict[str, str]] = []
    for item in payload.get("items", []):
        name = str(item.get("name", "")).strip()
        symbol = str(item.get("yahoosymbol", "")).strip()
        code = str(item.get("code", "")).strip()
        if not name or not symbol:
            continue
        chips.append({"name": name, "yahoosymbol": symbol, "code": code})
    chips.sort(key=lambda row: row["name"])
    return chips


def build_normalized_close_chart_df(
    payload: dict,
    *,
    lookback_days: int = CHART_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """모든 ETF 종가를 종목별 0~1000으로 정규화 (최근 lookback_days일)"""
    rows: list[dict] = []
    for item in payload.get("items", []):
        name = str(item.get("name", "")).strip() or str(item.get("yahoosymbol", ""))
        grid = item.get("grid") or []
        if not grid:
            continue
        frame = pd.DataFrame(grid)
        if "날짜" not in frame.columns or "종가" not in frame.columns:
            continue
        frame = frame[["날짜", "종가"]].copy()
        frame["종가"] = pd.to_numeric(frame["종가"], errors="coerce")
        frame = frame.dropna(subset=["날짜", "종가"])
        if frame.empty:
            continue
        frame["ETF"] = name
        rows.extend(frame[["날짜", "ETF", "종가"]].to_dict(orient="records"))

    if not rows:
        return pd.DataFrame(columns=["날짜", "ETF", "종가_정규화", "date"])

    chart_df = pd.DataFrame(rows)
    chart_df["date"] = pd.to_datetime(chart_df["날짜"])
    max_date = chart_df["date"].max()
    cutoff = max_date - pd.Timedelta(days=lookback_days)
    chart_df = chart_df[chart_df["date"] >= cutoff].copy()
    if chart_df.empty:
        return pd.DataFrame(columns=["날짜", "ETF", "종가_정규화", "date"])

    normalized_rows: list[dict] = []
    for etf_name, group in chart_df.groupby("ETF", sort=False):
        frame = group.copy()
        lo = float(frame["종가"].min())
        hi = float(frame["종가"].max())
        if hi == lo:
            frame["종가_정규화"] = 500.0
        else:
            frame["종가_정규화"] = (frame["종가"] - lo) / (hi - lo) * 1000.0
        normalized_rows.extend(
            frame[["날짜", "ETF", "종가_정규화", "date"]].to_dict(orient="records")
        )

    out = pd.DataFrame(normalized_rows)
    return out.sort_values(["ETF", "date"]).reset_index(drop=True)


def normalized_close_chart_svg(
    payload: dict,
    *,
    color_map: dict[str, str] | None = None,
    width: int = 860,
    height: int = 320,
) -> str:
    """정규화 종가 라인 차트 SVG (최근 70일, 호버 툴팁용 포인트 포함)"""
    chart_df = build_normalized_close_chart_df(payload)
    if chart_df.empty:
        return '<p class="chart-empty">차트에 표시할 종가 데이터가 없습니다.</p>'

    left, right, top, bottom = 46, 12, 12, 40
    plot_w = width - left - right
    plot_h = height - top - bottom
    dates = sorted(chart_df["date"].dropna().unique())
    if not dates:
        return '<p class="chart-empty">차트에 표시할 종가 데이터가 없습니다.</p>'

    denom = max(len(dates) - 1, 1)
    x_of = {
        pd.Timestamp(d): left + (idx / denom) * plot_w for idx, d in enumerate(dates)
    }
    etfs = list(dict.fromkeys(chart_df["ETF"].tolist()))
    if color_map is None:
        color_map = _etf_color_map(sorted(etfs))

    polylines: list[str] = []
    hover_points: list[str] = []
    legend_items: list[str] = []
    for idx, etf in enumerate(etfs):
        color = color_map.get(etf) or _CHART_COLORS[idx % len(_CHART_COLORS)]
        sub = chart_df[chart_df["ETF"] == etf].sort_values("date")
        points: list[str] = []
        for _, row in sub.iterrows():
            x = x_of.get(pd.Timestamp(row["date"]))
            if x is None:
                continue
            y_val = float(row["종가_정규화"])
            y = top + plot_h * (1.0 - (y_val / 1000.0))
            points.append(f"{x:.2f},{y:.2f}")
            date_str = str(row.get("날짜") or pd.Timestamp(row["date"]).strftime("%Y-%m-%d"))
            tip = html.escape(f"{date_str}\n{etf}\n{y_val:.1f}")
            hover_points.append(
                f'<circle class="etf-hover-point" cx="{x:.2f}" cy="{y:.2f}" '
                f'r="6" fill="transparent" stroke="none" '
                f'data-date="{html.escape(date_str, quote=True)}" '
                f'data-name="{html.escape(str(etf), quote=True)}" '
                f'data-value="{y_val:.1f}" '
                f'data-color="{html.escape(color, quote=True)}">'
                f"<title>{tip}</title>"
                f"</circle>"
            )
        if len(points) < 2:
            continue
        polylines.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="1.4" '
            f'points="{" ".join(points)}" />'
        )
        legend_items.append(
            f'<span class="chart-legend-item">'
            f'<i style="background:{color}"></i>'
            f"{html.escape(str(etf))}"
            f"</span>"
        )

    # X축 눈금: 최근 70일 구간에 촘촘히 표시
    tick_count = min(CHART_X_TICK_COUNT, len(dates))
    if len(dates) <= 1:
        tick_idx = [0]
    else:
        tick_idx = sorted(
            {
                0,
                len(dates) - 1,
                *[
                    round(i * (len(dates) - 1) / (tick_count - 1))
                    for i in range(1, tick_count - 1)
                ],
            }
        )
    x_ticks: list[str] = []
    for i in tick_idx:
        d = pd.Timestamp(dates[i])
        x = x_of[d]
        label = d.strftime("%m.%d")
        x_ticks.append(
            f'<line x1="{x:.2f}" y1="{top + plot_h}" x2="{x:.2f}" '
            f'y2="{top + plot_h + 4}" stroke="#94a3b8" />'
            f'<text x="{x:.2f}" y="{height - 10}" text-anchor="middle" '
            f'font-size="9" fill="#64748b">{label}</text>'
        )

    y_ticks: list[str] = []
    for value in (0, 250, 500, 750, 1000):
        y = top + plot_h * (1.0 - value / 1000.0)
        y_ticks.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" '
            f'y2="{y:.2f}" stroke="#e2e8f0" stroke-width="1" />'
            f'<text x="{left - 6}" y="{y + 3:.2f}" text-anchor="end" '
            f'font-size="10" fill="#64748b">{value}</text>'
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto" class="etf-norm-svg" role="img" '
        f'aria-label="종가 정규화 차트">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#fff" />'
        f'<text x="8" y="14" font-size="11" fill="#64748b">종가</text>'
        f"{''.join(y_ticks)}"
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" '
        f'stroke="#94a3b8" />'
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="#94a3b8" />'
        f"{''.join(polylines)}"
        f"{''.join(hover_points)}"
        f"{''.join(x_ticks)}"
        f'<text x="{left + plot_w / 2:.1f}" y="{height - 2}" '
        f'text-anchor="middle" font-size="11" fill="#64748b">날짜</text>'
        f"</svg>"
    )
    legend = (
        f'<div class="etf-chart-legend">{"".join(legend_items)}</div>'
        if legend_items
        else ""
    )
    return (
        f'<div class="etf-chart-wrap">'
        f'<div class="etf-chart-title">종가 정규화 (0~1000) · 최근 {CHART_LOOKBACK_DAYS}일 · X=날짜 · Y=종가</div>'
        f'<div class="etf-chart-body">{svg}{legend}</div>'
        f"</div>"
    )


@st.cache_data(show_spinner=False)
def _cached_sector_expand_content(sector: str, mtime: float) -> tuple[str, str]:
    """섹터 JSON 기준 칩 HTML·차트 SVG 캐시 (mtime으로 무효화)"""
    del mtime  # cache key only
    try:
        payload = load_sector_payload(sector)
    except FileNotFoundError:
        return (
            '<span class="empty-msg">섹터 JSON 파일이 없습니다.</span>',
            '<p class="chart-empty">data/etf 섹터 JSON이 없습니다.</p>',
        )
    except Exception as exc:
        msg = html.escape(str(exc))
        return (
            f'<span class="empty-msg">JSON 로드 오류: {msg}</span>',
            f'<p class="chart-empty">차트 생성 실패: {msg}</p>',
        )

    etf_items = _chips_from_payload(payload, sector)
    color_map = _etf_color_map([item["name"] for item in etf_items])
    chips = _name_chips_html(etf_items, sector, color_map=color_map)
    chart = normalized_close_chart_svg(payload, color_map=color_map)
    return chips, chart


def _sector_expand_content(sector: str) -> tuple[str, str]:
    """섹터 펼침 영역용 칩·차트 HTML"""
    path = sector_json_path(sector)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _cached_sector_expand_content(sector, mtime)


def _sector_expand_row_html(
    sector: str,
    expand_id: str,
    sector_etfs: dict[str, list[dict[str, str]]],
) -> str:
    """섹터 클릭 시 한 줄(row)에 ETF 목록 + 정규화 차트를 표시"""
    if not sector:
        return ""

    path = sector_json_path(sector)
    if path.exists():
        chips_html, chart_html = _sector_expand_content(sector)
    else:
        chips_html = _name_chips_html(sector_etfs.get(sector, []), sector)
        chart_html = (
            f'<div class="etf-chart-wrap">'
            f'<p class="chart-empty">섹터 JSON 없음: '
            f"{html.escape(path.name)}</p></div>"
        )

    return (
        f'<tr id="{html.escape(expand_id, quote=True)}" '
        f'class="etf-expand-row" hidden>'
        f'<td colspan="4" class="expand-cell">'
        f'<div class="detail-wrap">'
        f'<div class="detail-title">'
        f"{html.escape(sector)} 종목 · 클릭 시 개별 분석"
        f"</div>"
        f'<div class="chip-row">{chips_html}</div>'
        f"{chart_html}"
        f"</div>"
        f"</td>"
        f"</tr>"
    )


def build_sector_grid_html(
    grid_rows: list[dict],
    sector_etfs: dict[str, list[dict[str, str]]],
) -> str:
    """HTML 섹터 그리드 (섹터 클릭 시 종목 목록·차트를 같은 펼침 행에 표시)"""
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
            '<tr class="pair-row">'
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
    display: inline-flex;
    align-items: center;
    gap: 5px;
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
  span.name-chip .chip-swatch {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex: 0 0 auto;
  }}
  span.name-chip:hover {{
    background: #dbeafe;
    border-color: #93c5fd;
  }}
  .empty-msg, .chart-empty {{
    color: #64748b;
    font-size: 10px;
  }}
  .etf-chart-wrap {{
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid #e2e8f0;
  }}
  .etf-chart-title {{
    font-size: 11px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 8px;
  }}
  .etf-chart-body {{
    width: 100%;
    position: relative;
  }}
  .etf-norm-svg {{
    display: block;
    width: 100%;
    height: auto;
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
  }}
  .etf-hover-point {{
    cursor: crosshair;
  }}
  .etf-chart-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px 10px;
    margin-top: 8px;
    max-height: 120px;
    overflow-y: auto;
  }}
  .chart-legend-item {{
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    color: #334155;
    white-space: nowrap;
  }}
  .chart-legend-item i {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }}
  .etf-chart-tooltip {{
    position: fixed;
    z-index: 10000;
    pointer-events: none;
    display: none;
    min-width: 140px;
    padding: 8px 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: rgba(15, 23, 42, 0.92);
    color: #f8fafc;
    font-size: 11px;
    line-height: 1.45;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.2);
  }}
  .etf-chart-tooltip .tip-row {{
    display: flex;
    gap: 6px;
  }}
  .etf-chart-tooltip .tip-label {{
    color: #94a3b8;
    min-width: 3.2rem;
  }}
  .etf-chart-tooltip .tip-swatch {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 2px;
    margin-top: 4px;
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


def _grid_to_records(grid_df: pd.DataFrame) -> list[dict]:
    """분석 그리드 DataFrame을 JSON 직렬화 가능 레코드로 변환"""
    records: list[dict] = []
    for row in grid_df[GRID_COLUMNS].to_dict(orient="records"):
        clean: dict = {}
        for key, value in row.items():
            if value is None or (isinstance(value, float) and pd.isna(value)):
                clean[key] = None
            elif hasattr(value, "item"):
                try:
                    clean[key] = value.item()
                except Exception:
                    clean[key] = value
            else:
                clean[key] = value
        records.append(clean)
    return records


def _latest_grid_date(grid: list[dict]) -> date | None:
    """그리드 최신 날짜"""
    dates: list[date] = []
    for row in grid:
        raw = row.get("날짜")
        if not raw:
            continue
        try:
            dates.append(pd.Timestamp(raw).date())
        except Exception:
            continue
    return max(dates) if dates else None


def _needs_api_update(grid: list[dict], today: date) -> bool:
    """최신 데이터가 (오늘-3일)보다 오래되면 API 갱신 필요"""
    latest = _latest_grid_date(grid)
    if latest is None:
        return True
    return latest < (today - timedelta(days=UPDATE_LOOKBACK_DAYS))


def _merge_grid_by_date(
    existing: list[dict],
    api_grid: list[dict],
    *,
    compare_from: date,
) -> list[dict]:
    """날짜 key 기준 병합. compare_from 이전 날짜는 기존 값 유지(비교·갱신 안 함)."""
    merged: dict[str, dict] = {}
    for row in existing:
        raw = row.get("날짜")
        if not raw:
            continue
        merged[str(raw)] = dict(row)

    for row in api_grid:
        raw = str(row.get("날짜", "")).strip()
        if not raw:
            continue
        try:
            row_date = pd.Timestamp(raw).date()
        except Exception:
            continue
        if row_date < compare_from:
            continue
        updated = dict(merged.get(raw, {}))
        for key in GRID_COLUMNS:
            if key in row:
                updated[key] = row[key]
        updated["날짜"] = raw
        merged[raw] = updated

    ordered = sorted(merged.values(), key=lambda item: str(item.get("날짜", "")))
    return ordered[-ref_stockanly.ANALYSIS_DAYS :]


def list_etf_sector_json_files() -> list[Path]:
    """data/etf/*.json 섹터 파일 목록"""
    if not ETF_DATA_DIR.exists():
        return []
    return sorted(path for path in ETF_DATA_DIR.glob("*.json") if path.is_file())


def load_payload_from_path(path: Path) -> dict:
    """섹터 JSON 파일 경로에서 payload 로드"""
    if not path.exists():
        raise FileNotFoundError(f"섹터 JSON 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"섹터 JSON 형식이 올바르지 않습니다: {path}")
    return payload


def save_payload_to_path(path: Path, payload: dict) -> Path:
    """섹터 JSON을 지정 경로에 저장"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return path


def load_sector_payload(sector: str) -> dict:
    """data/etf/{섹터}.json 로드"""
    return load_payload_from_path(sector_json_path(sector))


def save_sector_payload(sector: str, payload: dict) -> Path:
    """섹터 JSON 저장"""
    return save_payload_to_path(sector_json_path(sector), payload)


def update_sector_payload_from_api(
    payload: dict,
    *,
    show_progress: bool = True,
    progress_label: str = "",
) -> tuple[dict, dict]:
    """
    섹터 JSON의 모든 ETF에 대해 API로 날짜 key를 비교·갱신.

    - 최신 그리드 날짜가 (오늘-3일) 이상이면 API 호출 생략
    - API 호출 시: (오늘-3일) 이전 날짜는 기존 값 유지, 이후 날짜는 모든 key 갱신
    - 기존 데이터가 없거나 (오늘-3일)보다 오래되면 API 그리드로 전체 교체
    """
    today = date.today()
    compare_from = today - timedelta(days=UPDATE_LOOKBACK_DAYS)
    items = list(payload.get("items", []))
    errors = list(payload.get("errors", []))
    stats = {"requested": len(items), "updated": 0, "skipped": 0, "failed": 0}
    label_prefix = f"{progress_label} · " if progress_label else ""

    if not items:
        return payload, stats

    kospi_chart = None
    progress = None
    if show_progress:
        progress = st.progress(0.0, text=f"{label_prefix}ETF 데이터 갱신 중...")

    for index, item in enumerate(items):
        symbol = str(item.get("yahoosymbol", "")).strip()
        name = str(item.get("name", "")).strip() or symbol
        grid = list(item.get("grid") or [])
        if progress is not None:
            progress.progress(
                (index + 1) / len(items),
                text=f"{label_prefix}ETF 갱신 [{index + 1}/{len(items)}] {name}",
            )

        if not symbol:
            stats["failed"] += 1
            continue

        if not _needs_api_update(grid, today):
            stats["skipped"] += 1
            continue

        try:
            if kospi_chart is None:
                kospi_chart = ref_stockanly.fetch_chart(
                    KOSPI_SYMBOL, include_info=False
                )
                time.sleep(API_SLEEP_SECONDS)

            stock_chart = ref_stockanly.fetch_chart(symbol, include_info=False)
            api_df = ref_stockanly.build_analysis_grid(
                symbol,
                days=ref_stockanly.ANALYSIS_DAYS,
                stock_chart=stock_chart,
                kospi_chart=kospi_chart,
            )
            api_grid = _grid_to_records(api_df)
            latest = _latest_grid_date(grid)
            if not grid or latest is None or latest < compare_from:
                # 공백·오래됨: 전체 교체 (중간 날짜 공백 방지)
                item["grid"] = api_grid
            else:
                item["grid"] = _merge_grid_by_date(
                    grid, api_grid, compare_from=compare_from
                )
            stats["updated"] += 1
            time.sleep(API_SLEEP_SECONDS)
        except Exception as exc:
            stats["failed"] += 1
            errors.append(
                {
                    "code": item.get("code", ""),
                    "name": name,
                    "yahoosymbol": symbol,
                    "market": item.get("market", ""),
                    "error": str(exc),
                }
            )

    if progress is not None:
        progress.empty()

    payload["items"] = items
    payload["errors"] = errors
    payload["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["counts"] = {
        "requested": stats["requested"],
        "success": len(items),
        "failed": stats["failed"],
        "updated": stats["updated"],
        "skipped": stats["skipped"],
    }
    return payload, stats


def update_all_sector_json_files() -> dict:
    """
    data/etf/*.json 전체 섹터 파일을 순회하며 ETF 그리드 갱신·저장.

    파일 단위 작업 사이에는 SECTOR_FILE_SLEEP_SECONDS(2초) 간격을 둔다.
    """
    files = list_etf_sector_json_files()
    summary = {
        "files": len(files),
        "file_ok": 0,
        "file_failed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "details": [],
    }
    if not files:
        st.warning(f"갱신할 섹터 JSON이 없습니다: {ETF_DATA_DIR}")
        return summary

    file_progress = st.progress(0.0, text="전체 섹터 JSON 갱신 중...")
    status = st.empty()

    for index, path in enumerate(files):
        sector_name = path.stem
        try:
            payload = load_payload_from_path(path)
            sector_name = str(payload.get("sector") or path.stem)
            label = f"[{index + 1}/{len(files)}] {sector_name}"
            status.info(f"{label} · {path.name} 갱신 중...")
            file_progress.progress(
                index / len(files),
                text=f"{label} 처리 중...",
            )
            payload, stats = update_sector_payload_from_api(
                payload,
                show_progress=True,
                progress_label=label,
            )
            save_payload_to_path(path, payload)
            summary["file_ok"] += 1
            summary["updated"] += int(stats.get("updated", 0))
            summary["skipped"] += int(stats.get("skipped", 0))
            summary["failed"] += int(stats.get("failed", 0))
            summary["details"].append(
                {
                    "file": path.name,
                    "sector": sector_name,
                    "ok": True,
                    **stats,
                }
            )
        except Exception as exc:
            summary["file_failed"] += 1
            summary["details"].append(
                {
                    "file": path.name,
                    "sector": sector_name,
                    "ok": False,
                    "error": str(exc),
                }
            )
            status.error(f"{path.name} 갱신 실패: {exc}")

        file_progress.progress(
            (index + 1) / len(files),
            text=f"[{index + 1}/{len(files)}] 완료",
        )
        if index < len(files) - 1:
            status.info(
                f"다음 섹터 파일까지 {SECTOR_FILE_SLEEP_SECONDS}초 대기..."
            )
            time.sleep(SECTOR_FILE_SLEEP_SECONDS)

    file_progress.empty()
    status.empty()

    # 선택 섹터·차트 캐시 무효화 (일괄 갱신 반영)
    st.session_state.pop("etf_sector_payload", None)
    _cached_sector_expand_content.clear()

    return summary


def render_data_update_button() -> None:
    """그리드 상단 data update 버튼"""
    btn_col, info_col = st.columns([1.2, 6])
    with btn_col:
        clicked = st.button(
            "Data update",
            use_container_width=True,
            help=(
                f"data/etf/*.json 전체 갱신 · "
                f"최근 {UPDATE_LOOKBACK_DAYS}일 이내는 API 생략"
            ),
        )
    with info_col:
        st.caption(
            "data update: 모든 섹터 JSON을 API로 갱신·저장 "
            f"(최근 {UPDATE_LOOKBACK_DAYS}일 이내 스킵)"
        )

    if not clicked:
        return

    with st.spinner("전체 섹터 ETF 데이터 갱신 중..."):
        summary = update_all_sector_json_files()

    st.success(
        f"전체 갱신 완료 · 파일 {summary['file_ok']}/{summary['files']} · "
        f"API 갱신 {summary['updated']} · "
        f"스킵 {summary['skipped']} · "
        f"종목 실패 {summary['failed']} · "
        f"파일 실패 {summary['file_failed']}"
    )


def install_same_window_chip_navigation() -> None:
    """섹터 펼침 + 차트 툴팁 + 종목 칩 이동 핸들러"""
    components.html(
        """
        <script>
        (function () {
          const parentDoc = window.parent.document;
          const script = parentDoc.createElement('script');
          script.textContent = `
            (function () {
              if (window.__etfGridHandlersInstalledV4) return;
              window.__etfGridHandlersInstalledV4 = true;

              if (!document.getElementById('etf-chart-tooltip-style')) {
                const style = document.createElement('style');
                style.id = 'etf-chart-tooltip-style';
                style.textContent = `
                  .etf-chart-tooltip {
                    position: fixed; z-index: 10000; pointer-events: none; display: none;
                    min-width: 140px; padding: 8px 10px; border: 1px solid #cbd5e1;
                    border-radius: 6px; background: rgba(15, 23, 42, 0.92); color: #f8fafc;
                    font-size: 11px; line-height: 1.45;
                    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.2);
                  }
                  .etf-chart-tooltip .tip-row { display: flex; gap: 6px; }
                  .etf-chart-tooltip .tip-label { color: #94a3b8; min-width: 3.2rem; }
                  .etf-chart-tooltip .tip-swatch {
                    display: inline-block; width: 8px; height: 8px;
                    border-radius: 2px; margin-top: 4px; flex: 0 0 auto;
                  }
                `;
                document.head.appendChild(style);
              }

              function ensureTooltip() {
                let tip = document.getElementById('etf-chart-tooltip');
                if (tip) return tip;
                tip = document.createElement('div');
                tip.id = 'etf-chart-tooltip';
                tip.className = 'etf-chart-tooltip';
                document.body.appendChild(tip);
                return tip;
              }

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
                    if (willOpen) {
                      row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    }
                  });
                });
              }

              function bindChartTooltips(root) {
                const tip = ensureTooltip();
                root.querySelectorAll('circle.etf-hover-point').forEach(function (pt) {
                  if (pt.dataset.tipBound === '1') return;
                  pt.dataset.tipBound = '1';
                  pt.addEventListener('mousemove', function (e) {
                    const date = pt.getAttribute('data-date') || '';
                    const name = pt.getAttribute('data-name') || '';
                    const value = pt.getAttribute('data-value') || '';
                    const color = pt.getAttribute('data-color') || '#94a3b8';
                    tip.innerHTML =
                      '<div class="tip-row"><span class="tip-swatch" style="background:' + color + '"></span>' +
                      '<div>' +
                      '<div class="tip-row"><span class="tip-label">날짜</span><span>' + date + '</span></div>' +
                      '<div class="tip-row"><span class="tip-label">종목</span><span>' + name + '</span></div>' +
                      '<div class="tip-row"><span class="tip-label">정규화</span><span>' + value + '</span></div>' +
                      '</div></div>';
                    tip.style.display = 'block';
                    tip.style.left = (e.clientX + 14) + 'px';
                    tip.style.top = (e.clientY + 14) + 'px';
                    pt.setAttribute('fill', color);
                    pt.setAttribute('fill-opacity', '0.35');
                    pt.setAttribute('stroke', color);
                    pt.setAttribute('stroke-width', '1.5');
                    pt.setAttribute('r', '5');
                  });
                  pt.addEventListener('mouseleave', function () {
                    tip.style.display = 'none';
                    pt.setAttribute('fill', 'transparent');
                    pt.setAttribute('fill-opacity', '1');
                    pt.setAttribute('stroke', 'none');
                    pt.setAttribute('r', '6');
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
                bindChartTooltips(document);
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
    """섹터별 ETF 종목 수 HTML 그리드 (펼침 행에 종목·차트 포함)"""
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

    render_data_update_button()

    grid_rows = build_sector_grid_rows(sector_df, MAX_GRID_ROWS)
    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행"
    )
    with st.spinner("섹터 차트 준비 중..."):
        grid_html = build_sector_grid_html(grid_rows, sector_etfs)
    st.markdown(grid_html, unsafe_allow_html=True)
    install_same_window_chip_navigation()


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
