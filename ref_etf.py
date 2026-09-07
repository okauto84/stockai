"""ETF 추세확인 페이지"""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT_DIR = Path(__file__).resolve().parent
KOSPI_LIST_FILE = ROOT_DIR / "data" / "kospilist" / "kospilist.json"
ETF_DATA_DIR = ROOT_DIR / "data" / "etf"
MAX_GRID_ROWS = 12
CHART_LOOKBACK_DAYS = 70
CHART_X_TICK_COUNT = 14
# 차트 HTML 캐시 무효화용 (legend 제거·구성종목 툴팁 등 UI 변경 시 증가)
CHART_CACHE_VERSION = 8
EXCLUDED_MA_FILTER_SECTORS = {"", "기타"}
MA_FILTER_OPTIONS = ["전체", "MA10", "MA20", "MA30", "MA50", "MA100", "MA150"]


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
def load_etf_elements_by_symbol(mtime: float | None = None) -> dict[str, list[str]]:
    """야후심볼·종목코드 → ETF 구성종목명 목록 (mtime은 캐시 무효화용)"""
    if mtime is None:
        mtime = (
            KOSPI_LIST_FILE.stat().st_mtime if KOSPI_LIST_FILE.exists() else 0.0
        )
    del mtime  # cache key only
    with KOSPI_LIST_FILE.open(encoding="utf-8") as file:
        payload = json.load(file)

    elements_map: dict[str, list[str]] = {}
    for items in payload.get("markets", {}).values():
        for item in items:
            if item.get("ETF") != "Y":
                continue
            symbol = str(item.get("yahoosymbol", "")).strip()
            code = str(item.get("code", "")).strip()
            raw = item.get("elements")
            names = (
                [str(name).strip() for name in raw if str(name).strip()]
                if isinstance(raw, list)
                else []
            )
            if symbol:
                elements_map[symbol] = names
                elements_map[symbol.upper()] = names
            if code:
                elements_map[code] = names
                elements_map[code.upper()] = names
    return elements_map


def get_etf_elements_map() -> dict[str, list[str]]:
    """kospilist.json 기준 최신 구성종목 맵"""
    mtime = KOSPI_LIST_FILE.stat().st_mtime if KOSPI_LIST_FILE.exists() else 0.0
    return load_etf_elements_by_symbol(mtime)


def lookup_etf_elements(
    elements_map: dict[str, list[str]],
    *,
    symbol: str = "",
    code: str = "",
) -> list[str]:
    """심볼·코드로 구성종목 조회"""
    for key in (symbol, symbol.upper(), code, code.upper()):
        if key and key in elements_map:
            return elements_map[key]
    return []


@st.cache_data
def load_etf_sector_data(
    mtime: float | None = None,
) -> tuple[pd.DataFrame, dict[str, list[dict]]]:
    """kospilist.json에서 ETF 섹터 집계 및 섹터별 종목(이름·심볼) 목록 로드"""
    if mtime is None:
        mtime = (
            KOSPI_LIST_FILE.stat().st_mtime if KOSPI_LIST_FILE.exists() else 0.0
        )
    del mtime  # cache key only
    with KOSPI_LIST_FILE.open(encoding="utf-8") as file:
        payload = json.load(file)

    elements_map = get_etf_elements_map()
    sector_etfs: dict[str, list[dict]] = {}
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
                    "elements": lookup_etf_elements(
                        elements_map, symbol=symbol, code=code
                    ),
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


def get_etf_sector_data() -> tuple[pd.DataFrame, dict[str, list[dict]]]:
    """kospilist.json mtime 기준 최신 섹터 집계"""
    mtime = KOSPI_LIST_FILE.stat().st_mtime if KOSPI_LIST_FILE.exists() else 0.0
    return load_etf_sector_data(mtime)


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


def _format_elements_tooltip(elements) -> str:
    """구성종목 리스트 → 툴팁 문자열"""
    if not isinstance(elements, list):
        return ""
    names = [str(name).strip() for name in elements if str(name).strip()]
    return ", ".join(names)


def _stock_chip(
    etf: dict,
    sector: str,
    *,
    color: str | None = None,
) -> str:
    """개별 종목 분석 탭 이동용 칩(<a target=_top>) HTML"""
    name = html.escape(etf["name"])
    symbol = str(etf["yahoosymbol"]).strip()
    keyword = str(etf.get("code") or etf["name"]).strip()
    # iframe 상대경로(?...)가 아닌 앱 루트(/?)로 이동해야 탭 전환이 됨
    href = "/?" + urlencode(
        {
            "goto": "stock",
            "symbol": symbol,
            "sector": sector,
            "keyword": keyword,
        }
    )
    href_q = html.escape(href, quote=True)
    symbol_q = html.escape(symbol, quote=True)
    sector_q = html.escape(sector, quote=True)
    keyword_q = html.escape(keyword, quote=True)
    elements_tip = _format_elements_tooltip(etf.get("elements"))
    # title_q: kospilist.json elements 전체 목록 (없으면 기본 안내)
    title_q = html.escape(
        elements_tip or f"{symbol} 분석 보기",
        quote=True,
    )
    elements_attr = (
        f' data-elements="{html.escape(elements_tip, quote=True)}"'
        if elements_tip
        else ""
    )
    swatch = ""
    if color:
        swatch = (
            f'<i class="chip-swatch" style="background:{html.escape(color, quote=True)}"></i>'
        )
    return (
        f'<a class="name-chip" href="{href_q}" target="_top" rel="noopener" '
        f'data-symbol="{symbol_q}" data-sector="{sector_q}" '
        f'data-keyword="{keyword_q}"{elements_attr} title="{title_q}">'
        f"{swatch}{name}</a>"
    )


def _name_chips_html(
    etfs: list[dict],
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
    """섹터명 텍스트 토글 셀"""
    if not sector:
        return '<td class="sector"></td>'

    return (
        f'<td class="sector">'
        f'<span class="sector-toggle" data-expand="{html.escape(expand_id, quote=True)}" '
        f'data-sector="{html.escape(sector, quote=True)}" '
        f'aria-expanded="false">{html.escape(sector)}</span>'
        f"</td>"
    )


def _chips_from_payload(payload: dict, sector: str) -> list[dict]:
    """섹터 JSON payload에서 칩용 ETF 목록 생성"""
    del sector  # 호출 호환용
    elements_map = get_etf_elements_map()
    chips: list[dict] = []
    for item in payload.get("items", []):
        name = str(item.get("name", "")).strip()
        symbol = str(item.get("yahoosymbol", "")).strip()
        code = str(item.get("code", "")).strip()
        if not name or not symbol:
            continue
        chips.append(
            {
                "name": name,
                "yahoosymbol": symbol,
                "code": code,
                "elements": lookup_etf_elements(
                    elements_map, symbol=symbol, code=code
                ),
            }
        )
    chips.sort(key=lambda row: row["name"])
    return chips


def latest_grid_row(item: dict) -> dict | None:
    """ETF item grid의 최신(마지막) 행"""
    grid = item.get("grid") or []
    if not grid:
        return None
    return grid[-1] if isinstance(grid[-1], dict) else None


def is_close_ge_ma(item: dict, ma_field: str) -> bool:
    """최신 종가 >= 선택 MA 여부"""
    row = latest_grid_row(item)
    if not row:
        return False
    try:
        close = float(row.get("종가"))
        ma_value = float(row.get(ma_field))
    except (TypeError, ValueError):
        return False
    return close >= ma_value


def filter_payload_close_ge_ma(payload: dict, ma_field: str) -> dict:
    """종가 >= 선택 MA 인 ETF만 남긴 payload 복사본"""
    items = [
        item
        for item in (payload.get("items") or [])
        if isinstance(item, dict) and is_close_ge_ma(item, ma_field)
    ]
    filtered = dict(payload)
    filtered["items"] = items
    counts = dict(payload.get("counts") or {})
    counts["success"] = len(items)
    counts[f"filtered_close_ge_{ma_field}"] = len(items)
    filtered["counts"] = counts
    return filtered


def _etf_json_cache_key() -> str:
    """data/etf·kospilist 변경 감지용 캐시 키"""
    parts: list[str] = []
    if ETF_DATA_DIR.exists():
        for path in sorted(ETF_DATA_DIR.glob("*.json")):
            parts.append(f"{path.name}:{path.stat().st_mtime}")
    if KOSPI_LIST_FILE.exists():
        parts.append(f"kospilist:{KOSPI_LIST_FILE.stat().st_mtime}")
    parts.append(f"ver:{CHART_CACHE_VERSION}")
    return "|".join(parts)


@st.cache_data(show_spinner=False)
def collect_close_ge_ma_by_sector(
    cache_key: str,
    ma_field: str,
) -> tuple[pd.DataFrame, dict[str, list[dict]]]:
    """기타 제외 · 종가>=선택 MA ETF를 섹터별로 수집"""
    del cache_key
    elements_map = get_etf_elements_map()
    sector_etfs: dict[str, list[dict]] = {}

    if not ETF_DATA_DIR.exists():
        return pd.DataFrame(columns=["섹터", "수"]), sector_etfs

    for path in sorted(ETF_DATA_DIR.glob("*.json")):
        try:
            payload = load_payload_from_path(path)
        except Exception:
            continue
        sector = str(payload.get("sector") or path.stem).strip()
        if sector in EXCLUDED_MA_FILTER_SECTORS:
            continue

        matched: list[dict] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict) or not is_close_ge_ma(item, ma_field):
                continue
            name = str(item.get("name", "")).strip()
            symbol = str(item.get("yahoosymbol", "")).strip()
            code = str(item.get("code", "")).strip()
            if not name or not symbol:
                continue
            matched.append(
                {
                    "name": name,
                    "yahoosymbol": symbol,
                    "code": code,
                    "elements": lookup_etf_elements(
                        elements_map, symbol=symbol, code=code
                    ),
                }
            )
        if not matched:
            continue
        matched.sort(key=lambda row: row["name"])
        sector_etfs[sector] = matched

    count_rows = [
        {"섹터": sector, "수": len(etfs)}
        for sector, etfs in sorted(
            sector_etfs.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]
    return pd.DataFrame(count_rows), sector_etfs


def _ma_filter_expand_content(
    sector: str, etfs: list[dict], ma_field: str
) -> tuple[str, str]:
    """종가>=선택 MA 펼침용 칩·차트 HTML"""
    if not etfs:
        return (
            '<span class="empty-msg">조건에 맞는 ETF가 없습니다.</span>',
            '<p class="chart-empty">표시할 차트가 없습니다.</p>',
        )

    color_map = _etf_color_map([item["name"] for item in etfs])
    chips = _name_chips_html(etfs, sector, color_map=color_map)

    path = sector_json_path(sector)
    if not path.exists():
        return chips, (
            f'<div class="etf-chart-wrap">'
            f'<p class="chart-empty">섹터 JSON 없음: '
            f"{html.escape(path.name)}</p></div>"
        )

    try:
        payload = filter_payload_close_ge_ma(load_sector_payload(sector), ma_field)
        chart = normalized_close_chart_svg(payload, color_map=color_map)
    except Exception as exc:
        chart = (
            f'<div class="etf-chart-wrap">'
            f'<p class="chart-empty">차트 생성 실패: '
            f"{html.escape(str(exc))}</p></div>"
        )
    return chips, chart


def make_ma_filter_expand_row_html(ma_field: str):
    """선택 MA 기준 펼침 행 빌더 생성"""

    def _expand_row_html(
        sector: str,
        expand_id: str,
        sector_etfs: dict[str, list[dict]],
    ) -> str:
        if not sector:
            return ""
        etfs = sector_etfs.get(sector, [])
        chips_html, chart_html = _ma_filter_expand_content(sector, etfs, ma_field)
        return (
            f'<tr id="{html.escape(expand_id, quote=True)}" '
            f'class="etf-expand-row">'
            f'<td colspan="4" class="expand-cell">'
            f'<div class="detail-wrap">'
            f'<div class="detail-title">'
            f"{html.escape(sector)} · 종가 ≥ {html.escape(ma_field)} · "
            f"클릭 시 개별 분석"
            f"</div>"
            f'<div class="chip-row">{chips_html}</div>'
            f"{chart_html}"
            f"</div>"
            f"</td>"
            f"</tr>"
        )

    return _expand_row_html


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
            hover_points.append(
                f'<circle class="etf-hover-point" cx="{x:.2f}" cy="{y:.2f}" '
                f'r="6" fill="transparent" stroke="none" '
                f'data-date="{html.escape(date_str, quote=True)}" '
                f'data-name="{html.escape(str(etf), quote=True)}" '
                f'data-value="{y_val:.1f}" '
                f'data-color="{html.escape(color, quote=True)}" />'
            )
        if len(points) < 2:
            continue
        polylines.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="1.4" '
            f'points="{" ".join(points)}" />'
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
    return (
        f'<div class="etf-chart-wrap">'
        f'<div class="etf-chart-title">종가 정규화 (0~1000) · 최근 {CHART_LOOKBACK_DAYS}일 · X=날짜 · Y=종가</div>'
        f'<div class="etf-chart-body">{svg}</div>'
        f"</div>"
    )


@st.cache_data(show_spinner=False)
def _cached_sector_expand_content(
    sector: str,
    mtime: float,
    kospi_mtime: float,
    cache_version: int = CHART_CACHE_VERSION,
) -> tuple[str, str]:
    """섹터 JSON 기준 칩 HTML·차트 SVG 캐시 (mtime·kospilist·version으로 무효화)"""
    del mtime, kospi_mtime, cache_version  # cache key only
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
    kospi_mtime = (
        KOSPI_LIST_FILE.stat().st_mtime if KOSPI_LIST_FILE.exists() else 0.0
    )
    return _cached_sector_expand_content(
        sector, mtime, kospi_mtime, CHART_CACHE_VERSION
    )


def _sector_expand_row_html(
    sector: str,
    expand_id: str,
    sector_etfs: dict[str, list[dict]],
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
        f'class="etf-expand-row">'
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
    sector_etfs: dict[str, list[dict]],
    *,
    id_prefix: str = "etf-exp",
    expand_row_html=_sector_expand_row_html,
) -> str:
    """HTML 섹터 그리드 (섹터 클릭 시 종목 목록·차트를 같은 펼침 행에 표시)"""
    body_rows: list[str] = []
    for row_idx, row in enumerate(grid_rows):
        left_sector = row["left_sector"]
        left_count = row["left_count"]
        right_sector = row["right_sector"]
        right_count = row["right_count"]
        left_expand_id = f"{id_prefix}-{row_idx}-L"
        right_expand_id = f"{id_prefix}-{row_idx}-R"

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
            expand_row_html(left_sector, left_expand_id, sector_etfs)
        )
        body_rows.append(
            expand_row_html(right_sector, right_expand_id, sector_etfs)
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
  table.etf-sector-grid .sector-toggle {{
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
  table.etf-sector-grid .sector-toggle::before {{
    content: "▸ ";
    color: #64748b;
  }}
  table.etf-sector-grid .sector-toggle[aria-expanded="true"] {{
    color: #2563eb;
  }}
  table.etf-sector-grid .sector-toggle[aria-expanded="true"]::before {{
    content: "▾ ";
  }}
  table.etf-sector-grid tr.etf-expand-row {{
    display: none;
  }}
  table.etf-sector-grid tr.etf-expand-row.is-open {{
    display: table-row;
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
  span.name-chip,
  a.name-chip {{
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
  span.name-chip .chip-swatch,
  a.name-chip .chip-swatch {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex: 0 0 auto;
    pointer-events: none;
  }}
  span.name-chip:hover,
  a.name-chip:hover {{
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
  .etf-chart-legend,
  .chart-legend-item {{
    display: none !important;
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


def load_payload_from_path(path: Path) -> dict:
    """섹터 JSON 파일 경로에서 payload 로드"""
    if not path.exists():
        raise FileNotFoundError(f"섹터 JSON 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"섹터 JSON 형식이 올바르지 않습니다: {path}")
    return payload


def load_sector_payload(sector: str) -> dict:
    """data/etf/{섹터}.json 로드"""
    return load_payload_from_path(sector_json_path(sector))


def render_sector_grid_component(grid_html: str, *, pair_rows: int) -> None:
    """그리드 HTML + 클릭/툴팁 스크립트를 한 iframe에서 렌더"""
    height = min(1600, max(560, 100 + max(1, pair_rows) * 52))
    components.html(
        f"""
        <style>html,body{{margin:0;padding:0;background:transparent;}}</style>
        {grid_html}
        <script>
        (function () {{
          const doc = document;

          function closeOthers(exceptId) {{
            doc.querySelectorAll('tr.etf-expand-row.is-open').forEach(function (row) {{
              if (exceptId && row.id === exceptId) return;
              row.classList.remove('is-open');
            }});
            doc.querySelectorAll('.sector-toggle[aria-expanded="true"]').forEach(function (el) {{
              if (exceptId && el.getAttribute('data-expand') === exceptId) return;
              el.setAttribute('aria-expanded', 'false');
            }});
          }}

          function toggleSector(el) {{
            const id = el.getAttribute('data-expand') || '';
            const row = id ? doc.getElementById(id) : null;
            if (!row) return;
            const open = !row.classList.contains('is-open');
            closeOthers(open ? id : null);
            row.classList.toggle('is-open', open);
            el.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (open) {{
              try {{ row.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }}); }} catch (e) {{}}
            }}
          }}

          // Streamlit st.components.html iframe sandbox에는
          // allow-top-navigation 이 없어 location / <a target=_top> 이 차단됨.
          // allow-same-origin 으로 부모 document에 스크립트를 심어 우회.
          function buildGotoHref(symbol, sector, keyword) {{
            let url;
            try {{
              url = new URL((window.parent && window.parent.location.href) || window.location.href);
            }} catch (err) {{
              url = new URL(window.location.origin + '/');
            }}
            url.search = '';
            url.hash = '';
            url.searchParams.set('goto', 'stock');
            url.searchParams.set('symbol', symbol);
            if (sector) url.searchParams.set('sector', sector);
            if (keyword) url.searchParams.set('keyword', keyword);
            return url.toString();
          }}

          function installParentNav(win) {{
            if (!win || win === window) return;
            try {{
              const pdoc = win.document;
              if (!pdoc || pdoc.documentElement.getAttribute('data-stockai-nav') === '1') return;
              pdoc.documentElement.setAttribute('data-stockai-nav', '1');
              const s = pdoc.createElement('script');
              s.textContent = [
                'window.addEventListener("message", function (ev) {{',
                '  var d = ev.data || {{}};',
                '  if (d.type !== "stockai-goto-stock" || !d.symbol) return;',
                '  try {{',
                '    var url = new URL(window.location.href);',
                '    url.search = "";',
                '    url.hash = "";',
                '    url.searchParams.set("goto", "stock");',
                '    url.searchParams.set("symbol", d.symbol);',
                '    if (d.sector) url.searchParams.set("sector", d.sector);',
                '    if (d.keyword) url.searchParams.set("keyword", d.keyword);',
                '    window.location.assign(url.toString());',
                '  }} catch (e) {{}}',
                '}});'
              ].join('\\n');
              (pdoc.head || pdoc.documentElement).appendChild(s);
            }} catch (err) {{}}
          }}

          function goChip(el) {{
            const symbol = (el.getAttribute('data-symbol') || '').trim();
            if (!symbol) return false;
            const sector = el.getAttribute('data-sector') || '';
            const keyword = el.getAttribute('data-keyword') || '';
            const href = buildGotoHref(symbol, sector, keyword);
            const msg = {{
              type: 'stockai-goto-stock',
              symbol: symbol,
              sector: sector,
              keyword: keyword
            }};

            // 1) 부모(비sandbox) 스크립트가 location 변경
            try {{ window.parent.postMessage(msg, '*'); }} catch (err) {{}}
            try {{
              if (window.top && window.top !== window.parent) {{
                window.top.postMessage(msg, '*');
              }}
            }} catch (err) {{}}

            // 2) 부모 document의 <a> 클릭 (실패해도 throw 안 할 수 있음 → 계속 시도)
            try {{
              const pdoc = window.parent.document;
              const a = pdoc.createElement('a');
              a.href = href;
              a.style.display = 'none';
              pdoc.body.appendChild(a);
              a.click();
              a.remove();
            }} catch (err) {{}}

            // 3) allow-popups: window.open(..., '_top')
            try {{ window.open(href, '_top'); }} catch (err) {{}}

            // 4) 부모 location 직접 시도
            try {{
              if (window.parent && window.parent !== window) {{
                window.parent.location.href = href;
              }}
            }} catch (err) {{}}

            return true;
          }}

          installParentNav(window.parent);
          try {{ installParentNav(window.top); }} catch (err) {{}}

          doc.addEventListener('click', function (e) {{
            const t = e.target;
            const el = t && t.nodeType === 3 ? t.parentElement : t;
            if (!el || !el.closest) return;
            const sectorEl = el.closest('.sector-toggle[data-expand]');
            if (sectorEl) {{
              e.preventDefault();
              e.stopPropagation();
              toggleSector(sectorEl);
              return;
            }}
            const chip = el.closest('a.name-chip[data-symbol], .name-chip[data-symbol]');
            if (chip) {{
              e.preventDefault();
              e.stopPropagation();
              goChip(chip);
            }}
          }});

          const tip = doc.createElement('div');
          tip.id = 'etf-chart-tooltip';
          tip.style.cssText = 'position:fixed;z-index:10000;pointer-events:none;display:none;min-width:140px;max-width:360px;padding:8px 10px;border:1px solid #cbd5e1;border-radius:6px;background:rgba(15,23,42,0.92);color:#f8fafc;font-size:11px;line-height:1.45;box-shadow:0 4px 14px rgba(15,23,42,0.2);white-space:normal;word-break:keep-all';
          doc.body.appendChild(tip);

          function escapeHtml(text) {{
            return String(text || '')
              .replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;');
          }}

          function placeTip(x, y) {{
            tip.style.display = 'block';
            tip.style.left = '0px';
            tip.style.top = '0px';
            const r = tip.getBoundingClientRect();
            const vw = window.innerWidth || 0;
            const vh = window.innerHeight || 0;
            let left = x + 14;
            let top = y + 14;
            if (left + r.width + 8 > vw) left = x - r.width - 14;
            if (top + r.height + 8 > vh) top = y - r.height - 14;
            tip.style.left = Math.max(8, left) + 'px';
            tip.style.top = Math.max(8, top) + 'px';
          }}

          doc.addEventListener('mousemove', function (e) {{
            const pt = e.target && e.target.closest
              ? e.target.closest('circle.etf-hover-point') : null;
            if (pt) {{
              const color = pt.getAttribute('data-color') || '#94a3b8';
              tip.innerHTML =
                '<div style="display:flex;gap:6px"><span style="width:8px;height:8px;border-radius:2px;margin-top:4px;background:' + color + '"></span><div>' +
                '<div>날짜 ' + (pt.getAttribute('data-date') || '') + '</div>' +
                '<div>종목 ' + (pt.getAttribute('data-name') || '') + '</div>' +
                '<div>정규화 ' + (pt.getAttribute('data-value') || '') + '</div></div></div>';
              placeTip(e.clientX, e.clientY);
              pt.setAttribute('fill', color);
              pt.setAttribute('fill-opacity', '0.35');
              pt.setAttribute('stroke', color);
              pt.setAttribute('stroke-width', '1.5');
              pt.setAttribute('r', '5');
              return;
            }}

            const chip = e.target && e.target.closest
              ? e.target.closest('a.name-chip[data-symbol]') : null;
            if (chip) {{
              const elements = (chip.getAttribute('data-elements') || '').trim();
              const titleText = (chip.getAttribute('title') || '').trim();
              const text = elements || titleText;
              if (text) {{
                // 커스텀 툴팁 표시 중에는 브라우저 기본 title 중복을 막음
                if (!chip.getAttribute('data-title-backup')) {{
                  chip.setAttribute('data-title-backup', titleText);
                  chip.removeAttribute('title');
                }}
                tip.innerHTML =
                  '<div style="font-weight:600;margin-bottom:4px">구성종목</div>' +
                  '<div>' + escapeHtml(text) + '</div>';
                placeTip(e.clientX, e.clientY);
                return;
              }}
            }}

            tip.style.display = 'none';
            doc.querySelectorAll('a.name-chip[data-title-backup]').forEach(function (el) {{
              if (!el.getAttribute('title')) {{
                el.setAttribute('title', el.getAttribute('data-title-backup') || '');
              }}
              el.removeAttribute('data-title-backup');
            }});
          }});

          doc.addEventListener('mouseout', function (e) {{
            const pt = e.target && e.target.closest
              ? e.target.closest('circle.etf-hover-point') : null;
            if (!pt) return;
            tip.style.display = 'none';
            pt.setAttribute('fill', 'transparent');
            pt.setAttribute('fill-opacity', '1');
            pt.setAttribute('stroke', 'none');
            pt.setAttribute('r', '6');
          }});
        }})();
        </script>
        """,
        height=height,
        scrolling=True,
    )


def render_sector_count_grid() -> None:
    """섹터별 ETF 종목 수 HTML 그리드 (이동평균선 필터 포함)"""
    ma_col, _ = st.columns([1.2, 4.8])
    with ma_col:
        ma_filter = st.selectbox(
            "이동평균선",
            options=MA_FILTER_OPTIONS,
            key="etf_ma_filter",
        )

    if ma_filter == "전체":
        if not KOSPI_LIST_FILE.exists():
            st.warning(f"종목 목록 파일을 찾을 수 없습니다: {KOSPI_LIST_FILE}")
            return
        try:
            sector_df, sector_etfs = get_etf_sector_data()
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
            f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행"
        )
        with st.spinner("섹터 차트 준비 중..."):
            grid_html = build_sector_grid_html(
                grid_rows,
                sector_etfs,
                id_prefix="etf-exp",
                expand_row_html=_sector_expand_row_html,
            )
        render_sector_grid_component(grid_html, pair_rows=len(grid_rows))
        return

    if not ETF_DATA_DIR.exists():
        st.warning(f"ETF 데이터 폴더를 찾을 수 없습니다: {ETF_DATA_DIR}")
        return

    try:
        sector_df, sector_etfs = collect_close_ge_ma_by_sector(
            _etf_json_cache_key(), ma_filter
        )
    except Exception as exc:
        st.error(f"종가≥{ma_filter} 집계 중 오류: {exc}")
        return

    if sector_df.empty:
        st.info(
            f"기타를 제외한 섹터에서 종가 ≥ {ma_filter} 인 ETF가 없습니다."
        )
        return

    grid_rows = build_sector_grid_rows(sector_df, MAX_GRID_ROWS)
    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"기타 제외 · 최신 종가 ≥ {ma_filter} · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행"
    )
    with st.spinner(f"종가≥{ma_filter} 차트 준비 중..."):
        grid_html = build_sector_grid_html(
            grid_rows,
            sector_etfs,
            id_prefix=f"etf-{ma_filter}-exp",
            expand_row_html=make_ma_filter_expand_row_html(ma_filter),
        )
    render_sector_grid_component(grid_html, pair_rows=len(grid_rows))


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
