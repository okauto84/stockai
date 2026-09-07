"""Data update 페이지: data/etf/*.json 일괄 갱신·저장"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

import ref_stockanly

ROOT_DIR = Path(__file__).resolve().parent
ETF_DATA_DIR = ROOT_DIR / "data" / "etf"
UPDATE_LOOKBACK_DAYS = 3
API_SLEEP_SECONDS = 1
SECTOR_FILE_SLEEP_SECONDS = 2
KOSPI_SYMBOL = "^KS11"
GRID_COLUMNS = list(ref_stockanly.GRID_COLUMNS)


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
    """섹터 JSON을 지정 경로에 원자적으로 저장 (임시 파일 → replace)"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
    return path


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


def _parse_grid_date(raw) -> date | None:
    """그리드 날짜 문자열 → date"""
    if not raw:
        return None
    try:
        return pd.Timestamp(raw).date()
    except Exception:
        return None


def _latest_grid_date(grid: list[dict]) -> date | None:
    """그리드 최신 날짜"""
    dates: list[date] = []
    for row in grid:
        row_date = _parse_grid_date(row.get("날짜"))
        if row_date is not None:
            dates.append(row_date)
    return max(dates) if dates else None


def _is_empty_close(value) -> bool:
    """종가 값이 비어 있는지"""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _period_has_valid_rows(
    grid: list[dict],
    *,
    compare_from: date,
    today: date,
) -> bool:
    """갱신 구간(compare_from~today)에 종가가 있는 행이 하나라도 있는지"""
    for row in grid:
        row_date = _parse_grid_date(row.get("날짜"))
        if row_date is None or row_date < compare_from or row_date > today:
            continue
        if not _is_empty_close(row.get("종가")):
            return True
    return False


def _missing_api_period_dates(
    grid: list[dict],
    api_grid: list[dict],
    *,
    compare_from: date,
    today: date,
) -> set[date]:
    """API가 가진 갱신 구간 거래일 중 grid에 없거나 종가가 비어 있는 날짜"""
    close_by_date: dict[date, object] = {}
    for row in grid:
        row_date = _parse_grid_date(row.get("날짜"))
        if row_date is None:
            continue
        close_by_date[row_date] = row.get("종가")

    missing: set[date] = set()
    for row in api_grid:
        row_date = _parse_grid_date(row.get("날짜"))
        if row_date is None or row_date < compare_from or row_date > today:
            continue
        if row_date not in close_by_date or _is_empty_close(close_by_date[row_date]):
            missing.add(row_date)
    return missing


def _should_replace_full_grid(
    existing: list[dict],
    api_grid: list[dict],
    *,
    compare_from: date,
    today: date,
) -> bool:
    """부분 병합 시 중간 날짜 공백이 생기면 150일 전체 교체"""
    del today
    if not api_grid:
        return False
    if not existing:
        return True

    latest = _latest_grid_date(existing)
    if latest is None or latest < compare_from:
        return True

    return False


def _merge_grid_by_date(
    existing: list[dict],
    api_grid: list[dict],
    *,
    compare_from: date,
) -> list[dict]:
    """
    날짜 key 기준 병합.

    - compare_from 미만: 기존 값 유지(스킵, API로 덮지 않음)
    - compare_from 이상 ~ 최근: API 값으로 모든 key 갱신/추가
    """
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


def _finalize_updated_grid(
    existing: list[dict],
    api_grid: list[dict],
    *,
    compare_from: date,
    today: date,
) -> list[dict]:
    """
    Data update 결과 그리드 확정.

    오늘/기간 날짜가 없거나 비어 공백이 생기면 etf_dataproc와 같이
    API 150일 전체 그리드로 채워 날짜 데이터가 비지 않게 한다.
    """
    if not api_grid:
        return list(existing)

    if _should_replace_full_grid(
        existing, api_grid, compare_from=compare_from, today=today
    ):
        return api_grid

    merged = _merge_grid_by_date(existing, api_grid, compare_from=compare_from)

    if not _period_has_valid_rows(merged, compare_from=compare_from, today=today):
        return api_grid
    if _missing_api_period_dates(
        merged, api_grid, compare_from=compare_from, today=today
    ):
        return api_grid
    return merged


def update_sector_payload_from_api(
    payload: dict,
    *,
    lookback_days: int = UPDATE_LOOKBACK_DAYS,
    show_progress: bool = True,
    progress_label: str = "",
) -> tuple[dict, dict]:
    """
    섹터 JSON의 모든 ETF에 대해 API로 날짜 key를 비교·갱신.

    입력 N (lookback_days) 기준:
    - 갱신 구간: (오늘 − N) ~ 오늘
    - 스킵: (오늘 − N) 미만 날짜는 기존 값 유지
    - 오늘 날짜: 최신일이 이미 오늘이어도 무조건 API로 재갱신
    - 오늘/기간 날짜가 없거나 중간 공백이 생기면 150일 전체 그리드로 채움
    """
    today = date.today()
    lookback_days = max(0, int(lookback_days))
    compare_from = today - timedelta(days=lookback_days)
    items = list(payload.get("items", []))
    errors = list(payload.get("errors", []))
    stats = {"requested": len(items), "updated": 0, "skipped": 0, "failed": 0}
    label_prefix = f"{progress_label} · " if progress_label else ""

    if not items:
        return payload, stats

    kospi_chart = None
    progress = None
    if show_progress:
        progress = st.progress(
            0.0,
            text=(
                f"{label_prefix}ETF 갱신 중 "
                f"({compare_from.isoformat()} ~ {today.isoformat()}, 오늘 포함 재갱신)"
            ),
        )

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
            item["grid"] = _finalize_updated_grid(
                grid,
                api_grid,
                compare_from=compare_from,
                today=today,
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
        "compare_from": compare_from.isoformat(),
        "compare_to": today.isoformat(),
        "lookback_days": lookback_days,
    }
    return payload, stats


def _invalidate_etf_chart_cache() -> None:
    """ETF 추세확인 화면 캐시 무효화"""
    st.session_state.pop("etf_sector_payload", None)
    try:
        import ref_etf

        ref_etf._cached_sector_expand_content.clear()
    except Exception:
        pass


def update_all_sector_json_files(
    *, lookback_days: int = UPDATE_LOOKBACK_DAYS
) -> dict:
    """
    data/etf/*.json 전체 섹터 파일을 순회하며 ETF 그리드 갱신·저장.

    파일 단위 작업 사이에는 SECTOR_FILE_SLEEP_SECONDS(2초) 간격을 둔다.
    """
    lookback_days = max(0, int(lookback_days))
    files = list_etf_sector_json_files()
    summary = {
        "files": len(files),
        "file_ok": 0,
        "file_failed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "lookback_days": lookback_days,
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
                lookback_days=lookback_days,
                show_progress=True,
                progress_label=label,
            )
            saved_path = save_payload_to_path(path, payload)
            if not saved_path.exists() or saved_path.stat().st_size <= 0:
                raise OSError(f"저장 후 파일이 비어 있습니다: {saved_path}")
            status.success(
                f"{label} · 저장 완료 ({saved_path.name}, "
                f"{saved_path.stat().st_size:,} bytes)"
            )
            summary["file_ok"] += 1
            summary["updated"] += int(stats.get("updated", 0))
            summary["skipped"] += int(stats.get("skipped", 0))
            summary["failed"] += int(stats.get("failed", 0))
            summary["details"].append(
                {
                    "file": path.name,
                    "sector": sector_name,
                    "ok": True,
                    "saved_path": str(saved_path.resolve()),
                    "saved_bytes": int(saved_path.stat().st_size),
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
    _invalidate_etf_chart_cache()
    return summary


def _prompt_update_lookback_days() -> bool:
    """
    스킵 일수 입력 UI.

    Returns:
        True면 사용자가 '업데이트 실행'을 눌러 갱신을 시작해야 함.
    """
    today = date.today()
    days = st.number_input(
        "현재일로부터 며칠 전까지 갱신할까요? (이전 날짜는 스킵)",
        min_value=0,
        max_value=365,
        value=int(st.session_state.get("etf_update_lookback_ui", UPDATE_LOOKBACK_DAYS)),
        step=1,
        help=(
            "예: 오늘이 2026-09-07이고 5를 입력하면 "
            "2026-09-02 ~ 2026-09-07만 갱신하고, 그 이전은 스킵합니다. "
            "오늘 날짜는 항상 재갱신합니다."
        ),
        key="etf_update_lookback_input",
    )
    lookback = max(0, int(days))
    compare_from = today - timedelta(days=lookback)
    st.info(
        f"갱신 구간: **{compare_from.isoformat()} ~ {today.isoformat()}**  \n"
        f"스킵: **{compare_from.isoformat()} 미만** 날짜는 기존 값 유지  \n"
        f"오늘(**{today.isoformat()}**)은 최신 데이터가 있어도 무조건 재갱신"
    )
    run_col, cancel_col = st.columns(2)
    with run_col:
        run_clicked = st.button(
            "업데이트 실행",
            type="primary",
            use_container_width=True,
            key="etf_update_run_btn",
        )
    with cancel_col:
        cancel_clicked = st.button(
            "취소",
            use_container_width=True,
            key="etf_update_cancel_btn",
        )

    if cancel_clicked:
        st.session_state["etf_show_update_prompt"] = False
        st.session_state.pop("etf_pending_lookback_days", None)
        st.session_state["etf_do_update"] = False
        return False

    if run_clicked:
        st.session_state["etf_pending_lookback_days"] = lookback
        st.session_state["etf_update_lookback_ui"] = lookback
        st.session_state["etf_do_update"] = True
        st.session_state["etf_show_update_prompt"] = False
        return True

    return False


def render_data_update_panel() -> None:
    """Data update 입력·실행 패널"""
    btn_col, info_col = st.columns([1.2, 6])
    with btn_col:
        clicked = st.button(
            "Data update",
            use_container_width=True,
            help="클릭 후 스킵 일수를 입력하면 data/etf/*.json 전체를 갱신합니다.",
            key="etf_data_update_btn",
        )
    with info_col:
        st.caption(
            "Data update: 스킵 일수 입력 후 모든 섹터 JSON을 API로 갱신·저장 "
            f"({ETF_DATA_DIR})"
        )

    if clicked:
        st.session_state["etf_show_update_prompt"] = True
        st.session_state["etf_do_update"] = False

    if st.session_state.get("etf_show_update_prompt"):
        with st.container(border=True):
            st.markdown("**Data update · 스킵 일수 입력**")
            _prompt_update_lookback_days()

    if not st.session_state.get("etf_do_update"):
        return

    pending_lookback = st.session_state.get("etf_pending_lookback_days")
    if pending_lookback is None:
        st.session_state["etf_do_update"] = False
        return

    st.session_state["etf_do_update"] = False
    st.session_state.pop("etf_pending_lookback_days", None)
    st.session_state["etf_show_update_prompt"] = False

    lookback_days = max(0, int(pending_lookback))
    compare_from = date.today() - timedelta(days=lookback_days)
    with st.spinner(
        f"전체 섹터 ETF 데이터 갱신·저장 중... "
        f"({compare_from.isoformat()} ~ {date.today().isoformat()}, 오늘 포함 재갱신)"
    ):
        summary = update_all_sector_json_files(lookback_days=lookback_days)

    saved_dir = ETF_DATA_DIR.resolve()
    st.success(
        f"전체 갱신 완료 · "
        f"구간 {compare_from.isoformat()} ~ {date.today().isoformat()} "
        f"(입력 {lookback_days}일, 오늘 재갱신) · "
        f"저장 {summary['file_ok']}/{summary['files']} · "
        f"경로 `{saved_dir}` · "
        f"API 갱신 {summary['updated']} · "
        f"스킵 {summary['skipped']} · "
        f"종목 실패 {summary['failed']} · "
        f"파일 실패 {summary['file_failed']}"
    )
    if summary.get("file_failed"):
        failed = [
            f"{row.get('file')}: {row.get('error', '')}"
            for row in summary.get("details", [])
            if not row.get("ok")
        ]
        if failed:
            st.error("저장 실패 파일:\n- " + "\n- ".join(failed[:10]))


def render_page() -> None:
    """Data update Streamlit 페이지"""
    st.caption(
        "data/etf 섹터 JSON을 Yahoo Finance API로 갱신·저장합니다. "
        "갱신 구간 이전 날짜는 스킵하고, 오늘은 항상 재갱신합니다."
    )
    file_count = len(list_etf_sector_json_files())
    st.markdown(
        f"- 대상 디렉터리: `{ETF_DATA_DIR.resolve()}`  \n"
        f"- 섹터 JSON 파일: **{file_count}**개"
    )
    render_data_update_panel()
