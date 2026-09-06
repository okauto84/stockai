"""ETF 섹터별 150일 분석 그리드 데이터 수집·저장

실행 순서:
1. kospilist.json 읽기
2. ETF='Y' 종목을 섹터별 그룹핑 ('기타' 제외)
3. ref_stockanly의 150일 분석 그리드와 동일 로직으로 API 조회
4. 종목 간 2초 간격(sleep)으로 API 부하 완화
5. 섹터별 JSON을 data/etf/{섹터명}.json 으로 저장
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT_DIR = Path(__file__).resolve().parents[2]
KOSPI_LIST_FILE = ROOT_DIR / "data" / "kospilist" / "kospilist.json"
OUTPUT_DIR = Path(__file__).resolve().parent

# ref_stockanly.py 150일 분석 그리드와 동일 설정
ANALYSIS_DAYS = 150
RS_WINDOW = 20
FETCH_PERIOD = "1y"
MA_WINDOWS = [10, 20, 30, 50, 100, 150]
GRID_COLUMNS = [
    "날짜",
    "종가",
    "거래량",
    "코스피",
    "RS지수",
    "MA10",
    "MA20",
    "MA30",
    "MA50",
    "MA100",
    "MA150",
]
API_SLEEP_SECONDS = 2
KOSPI_SYMBOL = "^KS11"
EXCLUDED_SECTORS = {"", "기타"}


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


def fetch_chart(
    symbol: str,
    range_period: str = FETCH_PERIOD,
    *,
    include_info: bool = False,
) -> dict:
    """yfinance로 주가 데이터 수집 (ref_stockanly.fetch_chart와 동일)"""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=range_period, interval="1d", auto_adjust=False)

    if hist.empty:
        raise ValueError(f"'{symbol}' 종목을 찾을 수 없습니다.")

    history = []
    for ts, row in hist.iterrows():
        close = row["Close"]
        if pd.notna(close):
            date = pd.Timestamp(ts).strftime("%Y-%m-%d")
            volume = row["Volume"]
            history.append(
                {
                    "date": date,
                    "close": round(float(close), 2),
                    "volume": int(volume) if pd.notna(volume) else None,
                }
            )

    if not history:
        raise ValueError(f"'{symbol}' 주가 데이터가 없습니다.")

    info: dict = {}
    if include_info:
        try:
            info = ticker.info or {}
        except Exception:
            info = {}

    return {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName") or symbol.upper(),
        "currency": info.get("currency", "USD"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "history": history,
    }


def build_analysis_grid(
    symbol: str,
    days: int = ANALYSIS_DAYS,
    *,
    stock_chart: dict | None = None,
    kospi_chart: dict | None = None,
) -> pd.DataFrame:
    """최근 N거래일 분석 그리드 DataFrame 생성 (ref_stockanly와 동일)"""
    stock = stock_chart or fetch_chart(symbol)
    kospi = kospi_chart or fetch_chart(KOSPI_SYMBOL, include_info=False)

    stock_df = pd.DataFrame(stock["history"]).rename(
        columns={"close": "종가", "volume": "거래량"}
    )
    kospi_df = pd.DataFrame(kospi["history"])[["date", "close"]].rename(
        columns={"close": "코스피"}
    )

    df = stock_df.merge(kospi_df, on="date", how="inner")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    for window in MA_WINDOWS:
        df[f"MA{window}"] = (
            df["종가"].rolling(window, min_periods=window).mean().round(2)
        )

    stock_ret = df["종가"] / df["종가"].shift(RS_WINDOW)
    kospi_ret = df["코스피"] / df["코스피"].shift(RS_WINDOW)
    df["RS지수"] = ((stock_ret / kospi_ret) * 100).round(2)

    df = df.tail(days).copy()
    df["날짜"] = df["date"].dt.strftime("%Y-%m-%d")
    return df[GRID_COLUMNS].reset_index(drop=True)


def load_etf_by_sector(kospilist_file: Path = KOSPI_LIST_FILE) -> dict[str, list[dict]]:
    """kospilist.json에서 ETF='Y' 종목을 섹터별 그룹핑 ('기타' 제외)"""
    with kospilist_file.open(encoding="utf-8") as file:
        payload = json.load(file)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for market, items in payload.get("markets", {}).items():
        for item in items:
            if item.get("ETF") != "Y":
                continue
            sector = (item.get("sector") or "").strip()
            if sector in EXCLUDED_SECTORS:
                continue
            grouped[sector].append(
                {
                    "market": market,
                    "code": item.get("code", ""),
                    "name": item.get("name", ""),
                    "yahoosymbol": item.get("yahoosymbol", ""),
                    "sector": sector,
                }
            )

    return {
        sector: sorted(items, key=lambda row: row["code"])
        for sector, items in sorted(grouped.items(), key=lambda item: item[0])
    }


def grid_to_records(grid_df: pd.DataFrame) -> list[dict]:
    """분석 그리드 DataFrame을 JSON 직렬화 가능한 레코드로 변환"""
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


def fetch_analysis_grid(symbol: str, *, kospi_chart: dict) -> list[dict]:
    """150일 분석 그리드 데이터 조회"""
    stock_chart = fetch_chart(symbol, include_info=False)
    grid_df = build_analysis_grid(
        symbol,
        days=ANALYSIS_DAYS,
        stock_chart=stock_chart,
        kospi_chart=kospi_chart,
    )
    return grid_to_records(grid_df)


def build_sector_payload(
    sector: str,
    etf_items: list[dict],
    *,
    kospi_chart: dict,
) -> dict:
    """섹터 내 모든 ETF 분석 그리드를 수집해 JSON 페이로드 생성"""
    results: list[dict] = []
    errors: list[dict] = []

    for index, item in enumerate(etf_items, start=1):
        symbol = item["yahoosymbol"]
        print(
            f"  [{index}/{len(etf_items)}] {sector} · {item['name']} ({symbol})",
            flush=True,
        )
        try:
            grid = fetch_analysis_grid(symbol, kospi_chart=kospi_chart)
            results.append(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "yahoosymbol": symbol,
                    "market": item["market"],
                    "grid": grid,
                }
            )
        except Exception as exc:
            print(f"    ! 실패: {exc}", flush=True)
            errors.append(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "yahoosymbol": symbol,
                    "market": item["market"],
                    "error": str(exc),
                }
            )

        if index < len(etf_items):
            time.sleep(API_SLEEP_SECONDS)

    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sector": sector,
        "source": "yfinance + ref_stockanly 150일 분석 그리드 로직",
        "analysis_days": ANALYSIS_DAYS,
        "grid_columns": GRID_COLUMNS,
        "counts": {
            "requested": len(etf_items),
            "success": len(results),
            "failed": len(errors),
        },
        "items": results,
        "errors": errors,
    }


def save_sector_json(payload: dict, output_dir: Path = OUTPUT_DIR) -> Path:
    """섹터별 JSON 파일 저장"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / sector_to_filename(payload["sector"])
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return output_file


def main() -> None:
    if not KOSPI_LIST_FILE.exists():
        raise FileNotFoundError(f"종목 목록 파일이 없습니다: {KOSPI_LIST_FILE}")

    print(f"1) kospilist 로드: {KOSPI_LIST_FILE}", flush=True)
    etf_by_sector = load_etf_by_sector(KOSPI_LIST_FILE)

    total_etf = sum(len(items) for items in etf_by_sector.values())
    print(
        f"2) ETF 그룹핑 완료 · 섹터 {len(etf_by_sector)}개 · "
        f"ETF {total_etf}개 ('기타' 제외)",
        flush=True,
    )
    if not etf_by_sector:
        print("저장할 ETF가 없습니다.", flush=True)
        return

    print(f"3) 코스피 지수 조회: {KOSPI_SYMBOL}", flush=True)
    kospi_chart = fetch_chart(KOSPI_SYMBOL, include_info=False)
    time.sleep(API_SLEEP_SECONDS)

    print(
        f"4~5) 섹터별 150일 분석 그리드 수집·저장 "
        f"(종목 간격 {API_SLEEP_SECONDS}초)",
        flush=True,
    )
    for sector, items in etf_by_sector.items():
        print(f"\n[섹터] {sector} · {len(items)}개", flush=True)
        payload = build_sector_payload(sector, items, kospi_chart=kospi_chart)
        output_file = save_sector_json(payload, OUTPUT_DIR)
        print(
            f"  저장: {output_file.name} "
            f"(성공 {payload['counts']['success']} / "
            f"실패 {payload['counts']['failed']})",
            flush=True,
        )
        time.sleep(API_SLEEP_SECONDS)

    print("\n완료.", flush=True)


if __name__ == "__main__":
    main()
