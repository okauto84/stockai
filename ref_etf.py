"""ETF 추세확인 페이지"""

from __future__ import annotations

import html
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import altair as alt
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
CHART_HEIGHT = 360


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


def _sector_toggle_cell_html(
    sector: str, expand_id: str, *, open_sector: str | None
) -> str:
    """섹터명 클릭 토글 셀 (목록은 아래 전체 행에서 표시)"""
    if not sector:
        return '<td class="sector"></td>'

    is_open = bool(open_sector) and sector == open_sector
    expanded = "true" if is_open else "false"
    return (
        f'<td class="sector">'
        f'<button type="button" class="sector-toggle" '
        f'data-expand="{html.escape(expand_id, quote=True)}" '
        f'data-sector="{html.escape(sector, quote=True)}" '
        f'aria-expanded="{expanded}">'
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


def _sector_expand_row_html(
    sector: str,
    expand_id: str,
    sector_etfs: dict[str, list[dict[str, str]]],
    *,
    open_sector: str | None,
    open_payload: dict | None,
) -> str:
    """섹터 클릭 시 그리드 한 줄(row) 전체를 차지하는 ETF 목록 행"""
    if not sector:
        return ""

    is_open = bool(open_sector) and sector == open_sector
    if is_open and open_payload:
        etfs = _chips_from_payload(open_payload, sector)
    else:
        etfs = sector_etfs.get(sector, [])

    hidden_attr = "" if is_open else " hidden"
    return (
        f'<tr id="{html.escape(expand_id, quote=True)}" '
        f'class="etf-expand-row"{hidden_attr}>'
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
    *,
    open_sector: str | None = None,
    open_payload: dict | None = None,
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
            '<tr class="pair-row">'
            f"{_sector_toggle_cell_html(left_sector, left_expand_id, open_sector=open_sector)}"
            f"{left_count_cell}"
            f"{_sector_toggle_cell_html(right_sector, right_expand_id, open_sector=open_sector)}"
            f"{right_count_cell}"
            "</tr>"
        )
        body_rows.append(
            _sector_expand_row_html(
                left_sector,
                left_expand_id,
                sector_etfs,
                open_sector=open_sector,
                open_payload=open_payload,
            )
        )
        body_rows.append(
            _sector_expand_row_html(
                right_sector,
                right_expand_id,
                sector_etfs,
                open_sector=open_sector,
                open_payload=open_payload,
            )
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

    # 선택 섹터 캐시 무효화 (일괄 갱신 반영)
    st.session_state.pop("etf_sector_payload", None)

    return summary


def render_data_update_button() -> None:
    """그리드 상단 data update 버튼"""
    btn_col, info_col = st.columns([1.2, 6])
    with btn_col:
        clicked = st.button(
            "data update",
            use_container_width=True,
            help=(
                f"data/etf/*.json 전체 갱신 · "
                f"최근 {UPDATE_LOOKBACK_DAYS}일 이내는 API 생략 · "
                f"파일 간 {SECTOR_FILE_SLEEP_SECONDS}초 대기"
            ),
        )
    with info_col:
        st.caption(
            "data update: 모든 섹터 JSON을 API로 갱신·저장 "
            f"(최근 {UPDATE_LOOKBACK_DAYS}일 이내 스킵 · "
            f"파일 간 sleep {SECTOR_FILE_SLEEP_SECONDS}초)"
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


def build_normalized_close_chart_df(payload: dict) -> pd.DataFrame:
    """모든 ETF 종가를 종목별 0~1000으로 정규화한 long DataFrame"""
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
        lo = float(frame["종가"].min())
        hi = float(frame["종가"].max())
        if hi == lo:
            frame["종가_정규화"] = 500.0
        else:
            frame["종가_정규화"] = (frame["종가"] - lo) / (hi - lo) * 1000.0
        frame["ETF"] = name
        rows.extend(
            frame[["날짜", "ETF", "종가_정규화"]].to_dict(orient="records")
        )

    if not rows:
        return pd.DataFrame(columns=["날짜", "ETF", "종가_정규화", "date"])

    chart_df = pd.DataFrame(rows)
    chart_df["date"] = pd.to_datetime(chart_df["날짜"])
    return chart_df.sort_values(["ETF", "date"]).reset_index(drop=True)


def render_normalized_close_chart(payload: dict, sector: str) -> None:
    """정규화 종가 라인 차트 (X=날짜, Y=종가 0~1000)"""
    chart_df = build_normalized_close_chart_df(payload)
    if chart_df.empty:
        st.info("차트에 표시할 종가 데이터가 없습니다.")
        return

    st.markdown(f"#### {html.escape(sector)} · 종가 정규화(0~1000) 추이")
    st.caption(
        "섹터 JSON 기준 · ETF 종가 종목별 0~1000 정규화 · "
        "X축 날짜 · Y축 종가"
    )

    chart = (
        alt.Chart(chart_df)
        .mark_line(strokeWidth=1.5)
        .encode(
            x=alt.X("date:T", title="날짜", axis=alt.Axis(format="%m.%d")),
            y=alt.Y(
                "종가_정규화:Q",
                title="종가",
                scale=alt.Scale(domain=[0, 1000]),
            ),
            color=alt.Color("ETF:N", legend=alt.Legend(title="ETF", orient="bottom")),
            tooltip=[
                alt.Tooltip("날짜:N", title="날짜"),
                alt.Tooltip("ETF:N", title="ETF"),
                alt.Tooltip("종가_정규화:Q", title="종가", format=".1f"),
            ],
        )
        .properties(height=CHART_HEIGHT)
        .interactive(bind_y=False)
    )
    st.altair_chart(chart, use_container_width=True)


def _clear_query_keys(*keys: str) -> None:
    """쿼리 파라미터 키 제거"""
    for key in keys:
        if key in st.query_params:
            del st.query_params[key]


def consume_sector_query() -> None:
    """섹터 클릭 쿼리 파라미터를 세션 상태로 반영"""
    if str(st.query_params.get("etf_sector_clear", "")).strip() in {"1", "true", "True"}:
        st.session_state.pop("etf_selected_sector", None)
        st.session_state.pop("etf_sector_payload", None)
        _clear_query_keys("etf_sector_clear", "etf_sector")
        return

    sector = str(st.query_params.get("etf_sector", "")).strip()
    if not sector:
        return

    st.session_state["etf_selected_sector"] = sector
    # 섹터 변경 시 캐시된 payload 무효화 → JSON 재로드
    cached = st.session_state.get("etf_sector_payload")
    if not isinstance(cached, dict) or cached.get("sector") != sector:
        st.session_state.pop("etf_sector_payload", None)
    _clear_query_keys("etf_sector", "etf_sector_clear")


def ensure_selected_sector_payload() -> dict | None:
    """선택된 섹터 JSON만 읽어 payload 반환 (API 갱신 없음)"""
    sector = st.session_state.get("etf_selected_sector")
    if not sector:
        return None

    cached = st.session_state.get("etf_sector_payload")
    if isinstance(cached, dict) and cached.get("sector") == sector:
        return cached

    try:
        payload = load_sector_payload(sector)
    except FileNotFoundError as exc:
        st.warning(str(exc))
        return None
    except Exception as exc:
        st.error(f"섹터 JSON 로드 오류: {exc}")
        return None

    st.session_state["etf_sector_payload"] = payload
    return payload


def install_same_window_chip_navigation() -> None:
    """섹터 선택(쿼리) + 종목 칩 동일 창 이동 핸들러 설치"""
    components.html(
        """
        <script>
        (function () {
          const parentDoc = window.parent.document;
          const script = parentDoc.createElement('script');
          script.textContent = `
            (function () {
              if (window.__etfGridHandlersInstalledV2) return;
              window.__etfGridHandlersInstalledV2 = true;

              function bindSectorToggles(root) {
                root.querySelectorAll('button.sector-toggle[data-sector]').forEach(function (btn) {
                  if (btn.dataset.toggleBound === '1') return;
                  btn.dataset.toggleBound = '1';
                  btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const sector = btn.getAttribute('data-sector') || '';
                    if (!sector) return;
                    const url = new URL(window.location.href);
                    const current = url.searchParams.get('etf_sector') || '';
                    const selected = btn.getAttribute('aria-expanded') === 'true';
                    url.searchParams.delete('goto');
                    url.searchParams.delete('symbol');
                    url.searchParams.delete('keyword');
                    if (selected || current === sector) {
                      url.searchParams.delete('etf_sector');
                      url.searchParams.set('etf_sector_clear', '1');
                    } else {
                      url.searchParams.delete('etf_sector_clear');
                      url.searchParams.set('etf_sector', sector);
                    }
                    window.location.assign(url.toString());
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
                    url.searchParams.delete('etf_sector');
                    url.searchParams.delete('etf_sector_clear');
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
    """섹터별 ETF 종목 수 HTML 그리드 + 선택 섹터 차트 표시"""
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

    consume_sector_query()
    open_sector = st.session_state.get("etf_selected_sector")
    open_payload = ensure_selected_sector_payload() if open_sector else None

    grid_rows = build_sector_grid_rows(sector_df, MAX_GRID_ROWS)
    total_etf = int(sector_df["수"].sum())
    st.caption(
        f"ETF 섹터별 종목 수 · 섹터 {len(sector_df):,}개 · "
        f"ETF {total_etf:,}개 · 그리드 {len(grid_rows)}행 · "
        "섹터 클릭 시 JSON 로드·종목 목록·정규화 차트 · "
        "종목 클릭 시 개별 종목 분석"
    )
    st.markdown(
        build_sector_grid_html(
            grid_rows,
            sector_etfs,
            open_sector=open_sector,
            open_payload=open_payload,
        ),
        unsafe_allow_html=True,
    )
    install_same_window_chip_navigation()

    if open_sector and open_payload:
        render_normalized_close_chart(open_payload, open_sector)


def render_page() -> None:
    """ETF 추세확인 Streamlit 페이지"""
    render_sector_count_grid()
