"""Data update 페이지: data/etf/*.json 일괄 갱신·저장 (로컬 + GitHub)"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

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

# GitHub 저장소 (로컬 갱신 후 origin으로 커밋·푸시)
GITHUB_DEFAULT_BRANCH = "main"
GITHUB_DATA_REL_DIR = "data/etf"
GITHUB_COMMIT_NAME = "stockai-dataupdate"
GITHUB_COMMIT_EMAIL = "stockai-dataupdate@users.noreply.github.com"


def _run_git(args: list[str], *, check: bool = True, mask: str | None = None) -> subprocess.CompletedProcess[str]:
    """git 명령 실행 (토큰 등 민감값은 stderr/stdout에서 마스킹용으로만 보관)"""
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        if mask and mask in err:
            err = err.replace(mask, "***")
        raise RuntimeError(err or f"git {' '.join(args)} failed ({result.returncode})")
    return result


def _secret_lookup(*keys: str) -> str:
    """st.secrets / 환경변수에서 문자열 값 조회"""
    # 1) 환경변수
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value

    # 2) Streamlit secrets (flat / nested github.*)
    try:
        secrets = st.secrets
    except Exception:
        return ""

    for key in keys:
        try:
            value = secrets.get(key, "")
            if value is not None and str(value).strip():
                return str(value).strip()
        except Exception:
            pass

    try:
        github = secrets.get("github", {})
        if hasattr(github, "get"):
            for key in ("token", "pat", "access_token", *keys):
                value = github.get(key, "")
                if value is not None and str(value).strip():
                    return str(value).strip()
    except Exception:
        pass
    return ""


def get_github_token() -> str:
    """GitHub push용 토큰 (GITHUB_TOKEN / STOCKAI_GITHUB_TOKEN / secrets)"""
    return _secret_lookup(
        "GITHUB_TOKEN",
        "STOCKAI_GITHUB_TOKEN",
        "GH_TOKEN",
    )


def get_github_branch() -> str:
    """푸시 대상 브랜치"""
    branch = _secret_lookup("GITHUB_BRANCH", "STOCKAI_GITHUB_BRANCH")
    if branch:
        return branch
    try:
        result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        name = (result.stdout or "").strip()
        if result.returncode == 0 and name and name != "HEAD":
            return name
    except Exception:
        pass
    return GITHUB_DEFAULT_BRANCH


def parse_github_repo_slug(remote_url: str) -> str | None:
    """origin URL → 'owner/repo'"""
    raw = (remote_url or "").strip()
    if not raw:
        return None
    raw = re.sub(r"\.git$", "", raw)
    # git@github.com:owner/repo
    m = re.match(r"git@github\.com:(.+)$", raw)
    if m:
        return m.group(1).strip("/")
    # https://github.com/owner/repo
    if "github.com" in raw:
        try:
            path = urlparse(raw).path.strip("/")
            if path.count("/") >= 1:
                parts = path.split("/")
                return f"{parts[0]}/{parts[1]}"
        except Exception:
            return None
    return None


def get_github_remote_info() -> dict:
    """현재 git origin 기준 GitHub 저장소 정보"""
    info = {
        "remote": "",
        "slug": "",
        "https_url": "",
        "web_url": "",
        "branch": get_github_branch(),
        "data_dir": GITHUB_DATA_REL_DIR,
        "token_configured": bool(get_github_token()),
    }
    # secrets로 저장소 지정 가능
    slug_override = _secret_lookup("GITHUB_REPO", "STOCKAI_GITHUB_REPO")
    try:
        result = _run_git(["remote", "get-url", "origin"], check=False)
        remote = (result.stdout or "").strip() if result.returncode == 0 else ""
    except Exception:
        remote = ""
    info["remote"] = remote
    slug = slug_override or (parse_github_repo_slug(remote) if remote else "")
    info["slug"] = slug or ""
    if slug:
        info["https_url"] = f"https://github.com/{slug}.git"
        info["web_url"] = f"https://github.com/{slug}"
    return info


def _git_has_changes(paths: list[str]) -> bool:
    """지정 경로에 커밋할 변경이 있는지"""
    result = _run_git(["status", "--porcelain", "--", *paths], check=False)
    return bool((result.stdout or "").strip())


def push_etf_data_to_github(
    *,
    message: str | None = None,
    rel_paths: list[str] | None = None,
) -> dict:
    """
    갱신된 data/etf/*.json 을 GitHub origin 저장소에 커밋·푸시.

    - 로컬 파일 저장 이후 호출
    - 토큰이 있으면 HTTPS + x-access-token 으로 푸시
    - 토큰이 없으면 기존 credential 로 push 시도
    """
    remote = get_github_remote_info()
    branch = remote["branch"]
    paths = rel_paths or [GITHUB_DATA_REL_DIR]
    commit_message = message or (
        f"chore(data): update ETF sector JSON ({date.today().isoformat()})"
    )
    result: dict = {
        "ok": False,
        "skipped": False,
        "committed": False,
        "pushed": False,
        "branch": branch,
        "slug": remote.get("slug") or "",
        "web_url": remote.get("web_url") or "",
        "files": paths,
        "commit": "",
        "message": commit_message,
        "error": "",
    }

    if not remote.get("slug"):
        result["error"] = (
            "GitHub 저장소를 확인할 수 없습니다. "
            "`git remote` 또는 secrets GITHUB_REPO(owner/repo)를 설정하세요."
        )
        return result

    try:
        if not _git_has_changes(paths):
            result["ok"] = True
            result["skipped"] = True
            result["message"] = "커밋할 data/etf 변경이 없습니다."
            return result

        _run_git(["add", "--", *paths])
        # git config를 바꾸지 않고 1회성 author 지정
        commit = _run_git(
            [
                "-c",
                f"user.name={GITHUB_COMMIT_NAME}",
                "-c",
                f"user.email={GITHUB_COMMIT_EMAIL}",
                "commit",
                "-m",
                commit_message,
                "--",
                *paths,
            ],
            check=False,
        )
        out = ((commit.stdout or "") + (commit.stderr or "")).strip()
        if commit.returncode != 0:
            if "nothing to commit" in out.lower():
                result["ok"] = True
                result["skipped"] = True
                result["message"] = "커밋할 변경이 없습니다."
                return result
            raise RuntimeError(out or "git commit failed")

        result["committed"] = True
        head = _run_git(["rev-parse", "--short", "HEAD"], check=False)
        result["commit"] = (head.stdout or "").strip()

        token = get_github_token()
        push_args: list[str]
        mask: str | None = None
        if token:
            # credential 없이 토큰으로 푸시 (remote URL은 변경하지 않음)
            auth_url = (
                f"https://x-access-token:{quote(token, safe='')}@github.com/"
                f"{remote['slug']}.git"
            )
            mask = token
            push_args = ["push", auth_url, f"HEAD:{branch}"]
        else:
            push_args = ["push", "-u", "origin", f"HEAD:{branch}"]

        _run_git(push_args, check=True, mask=mask)
        result["pushed"] = True
        result["ok"] = True
        result["message"] = (
            f"GitHub 푸시 완료 · {remote['slug']}@{branch}"
            + (f" ({result['commit']})" if result["commit"] else "")
        )
        return result
    except Exception as exc:
        err = str(exc)
        token = get_github_token()
        if token and token in err:
            err = err.replace(token, "***")
        result["error"] = err
        result["ok"] = False
        return result


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
    *,
    lookback_days: int = UPDATE_LOOKBACK_DAYS,
    push_to_github: bool = True,
) -> dict:
    """
    data/etf/*.json 전체 섹터 파일을 순회하며 ETF 그리드 갱신·로컬 저장 후
    (옵션) GitHub origin 저장소에 커밋·푸시.

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
        "github": None,
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
                f"{label} · 로컬 저장 완료 ({saved_path.name}, "
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

    if push_to_github and summary["file_ok"] > 0:
        remote = get_github_remote_info()
        status.info(
            f"GitHub 저장소에 푸시 중... "
            f"({remote.get('slug') or 'unknown'}@{remote.get('branch')})"
        )
        gh = push_etf_data_to_github(
            message=(
                f"chore(data): ETF sector JSON update "
                f"{date.today().isoformat()} "
                f"(lookback={lookback_days}d, files={summary['file_ok']})"
            ),
            rel_paths=[GITHUB_DATA_REL_DIR],
        )
        summary["github"] = gh
        if gh.get("ok"):
            if gh.get("skipped"):
                status.info(f"GitHub: {gh.get('message')}")
            else:
                status.success(f"GitHub: {gh.get('message')}")
        else:
            status.error(f"GitHub 푸시 실패: {gh.get('error') or 'unknown'}")
    elif push_to_github and summary["file_ok"] <= 0:
        summary["github"] = {
            "ok": False,
            "skipped": True,
            "message": "성공한 로컬 저장이 없어 GitHub 푸시를 건너뜁니다.",
        }

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
    remote = get_github_remote_info()
    btn_col, info_col = st.columns([1.2, 6])
    with btn_col:
        clicked = st.button(
            "Data update",
            use_container_width=True,
            help=(
                "클릭 후 스킵 일수를 입력하면 data/etf/*.json 전체를 갱신하고 "
                "GitHub 저장소에 푸시합니다."
            ),
            key="etf_data_update_btn",
        )
    with info_col:
        repo_label = remote.get("slug") or "(remote 미설정)"
        token_label = "토큰 설정됨" if remote.get("token_configured") else "토큰 없음(기존 credential 사용)"
        st.caption(
            f"Data update: 로컬 `{ETF_DATA_DIR.as_posix()}` 갱신 후 "
            f"GitHub `{repo_label}`@{remote.get('branch')} 푸시 · {token_label}"
        )

    if clicked:
        st.session_state["etf_show_update_prompt"] = True
        st.session_state["etf_do_update"] = False

    if st.session_state.get("etf_show_update_prompt"):
        with st.container(border=True):
            st.markdown("**Data update · 스킵 일수 입력**")
            if "etf_push_github" not in st.session_state:
                st.session_state["etf_push_github"] = True
            st.checkbox(
                "갱신 후 GitHub 저장소에 커밋·푸시",
                key="etf_push_github",
                help=(
                    "로컬 저장 후 origin(GitHub)에 data/etf 변경분을 푸시합니다. "
                    "권장: 환경변수/secrets에 GITHUB_TOKEN(repo 권한) 설정."
                ),
            )
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
    push_to_github = bool(st.session_state.get("etf_push_github", True))

    lookback_days = max(0, int(pending_lookback))
    compare_from = date.today() - timedelta(days=lookback_days)
    with st.spinner(
        f"전체 섹터 ETF 데이터 갱신·저장 중... "
        f"({compare_from.isoformat()} ~ {date.today().isoformat()}, 오늘 포함 재갱신)"
        + (" · 이후 GitHub 푸시" if push_to_github else "")
    ):
        summary = update_all_sector_json_files(
            lookback_days=lookback_days,
            push_to_github=push_to_github,
        )

    saved_dir = ETF_DATA_DIR.resolve()
    st.success(
        f"전체 갱신 완료 · "
        f"구간 {compare_from.isoformat()} ~ {date.today().isoformat()} "
        f"(입력 {lookback_days}일, 오늘 재갱신) · "
        f"로컬 저장 {summary['file_ok']}/{summary['files']} · "
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

    gh = summary.get("github")
    if push_to_github and isinstance(gh, dict):
        if gh.get("ok"):
            link = gh.get("web_url") or remote.get("web_url") or ""
            extra = f" · [저장소]({link})" if link else ""
            if gh.get("skipped"):
                st.info(f"GitHub: {gh.get('message')}{extra}")
            else:
                st.success(
                    f"GitHub 푸시 완료 · `{gh.get('slug')}@{gh.get('branch')}`"
                    + (f" · commit `{gh.get('commit')}`" if gh.get("commit") else "")
                    + extra
                )
        else:
            st.error(
                "GitHub 푸시 실패: "
                f"{gh.get('error') or 'unknown'}  \n"
                "환경변수 `GITHUB_TOKEN`(repo 권한) 또는 "
                "`secrets.github.token` / git credential을 확인하세요."
            )


def render_page() -> None:
    """Data update Streamlit 페이지"""
    remote = get_github_remote_info()
    st.caption(
        "data/etf 섹터 JSON을 Yahoo Finance API로 갱신합니다. "
        "로컬에 저장한 뒤 GitHub 저장소(origin)에 커밋·푸시합니다. "
        "갱신 구간 이전 날짜는 스킵하고, 오늘은 항상 재갱신합니다."
    )
    file_count = len(list_etf_sector_json_files())
    repo = remote.get("slug") or "(미설정)"
    web = remote.get("web_url") or ""
    token_ok = "설정됨" if remote.get("token_configured") else "미설정"
    st.markdown(
        f"- 로컬 디렉터리: `{ETF_DATA_DIR.resolve()}`  \n"
        f"- 섹터 JSON 파일: **{file_count}**개  \n"
        f"- GitHub 저장소: **{repo}**"
        + (f" ([열기]({web}))" if web else "")
        + f" · branch `{remote.get('branch')}` · token **{token_ok}**"
    )
    render_data_update_panel()
