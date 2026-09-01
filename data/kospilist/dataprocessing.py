"""코스피·코스닥 종목 목록을 수집해 JSON 파일로 저장"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = DATA_DIR / "kospilist.json"
NAVER_ETF_API = "https://finance.naver.com/api/sise/etfItemList.nhn"

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
SSL_VERIFY = False

MARKET_SUFFIX = {
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
}
TARGET_MARKETS = ("KOSPI", "KOSDAQ")


def normalize_code(code: str) -> str:
    """종목코드 비교용 정규화"""
    normalized = str(code).strip().upper()
    if normalized.isdigit():
        return normalized.zfill(6)
    return normalized


def to_yahoo_symbol(code: str, market: str) -> str:
    """종목코드를 Yahoo Finance 심볼로 변환"""
    suffix = MARKET_SUFFIX.get(market)
    if not suffix:
        raise ValueError(f"지원하지 않는 시장입니다: {market}")
    return f"{normalize_code(code)}{suffix}"


def fetch_etf_code_set() -> set[str]:
    """Naver Finance ETF 전 종목 코드 조회"""
    response = requests.get(
        NAVER_ETF_API,
        headers=YAHOO_HEADERS,
        verify=SSL_VERIFY,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("result", {}).get("etfItemList", [])
    if not items:
        raise ValueError("ETF 종목 목록을 가져오지 못했습니다.")

    return {normalize_code(item["itemcode"]) for item in items}


def fetch_etf_listing(etf_codes: set[str]) -> pd.DataFrame:
    """Naver Finance ETF 목록 DataFrame 생성"""
    response = requests.get(
        NAVER_ETF_API,
        headers=YAHOO_HEADERS,
        verify=SSL_VERIFY,
        timeout=30,
    )
    response.raise_for_status()
    items = response.json().get("result", {}).get("etfItemList", [])

    records = []
    for item in items:
        code = normalize_code(item["itemcode"])
        if code not in etf_codes:
            continue
        records.append(
            {
                "Code": code,
                "Name": str(item["itemname"]).strip(),
                "Market": "KOSPI",
                "yahoo_symbol": f"{code}.KS",
                "ETF": "Y",
            }
        )

    return pd.DataFrame(records).drop_duplicates(subset=["Code"]).reset_index(drop=True)


def fetch_krx_listing(etf_codes: set[str]) -> pd.DataFrame:
    """FinanceDataReader로 KRX 상장 종목 목록 조회"""
    listing = fdr.StockListing("KRX")
    listing = listing[listing["Market"].isin(TARGET_MARKETS)].copy()
    listing["Code"] = listing["Code"].astype(str).map(normalize_code)
    listing["Name"] = listing["Name"].astype(str).str.strip()
    listing["yahoo_symbol"] = listing.apply(
        lambda row: to_yahoo_symbol(row["Code"], row["Market"]),
        axis=1,
    )
    listing["ETF"] = listing["Code"].map(
        lambda code: "Y" if code in etf_codes else "N"
    )
    return listing.sort_values(["Market", "Code"]).reset_index(drop=True)


def merge_with_etf_listing(
    krx_listing: pd.DataFrame, etf_listing: pd.DataFrame
) -> pd.DataFrame:
    """KRX 종목과 ETF 목록 병합"""
    existing_codes = set(krx_listing["Code"])
    missing_etfs = etf_listing[~etf_listing["Code"].isin(existing_codes)].copy()
    if missing_etfs.empty:
        return krx_listing

    merged = pd.concat(
        [
            krx_listing,
            missing_etfs[["Code", "Name", "Market", "yahoo_symbol", "ETF"]],
        ],
        ignore_index=True,
    )
    return merged.sort_values(["Market", "Code"]).reset_index(drop=True)


def build_market_records(df: pd.DataFrame, market: str) -> list[dict]:
    """시장별 종목 레코드 생성"""
    market_df = df[df["Market"] == market]
    return [
        {
            "code": row["Code"],
            "name": row["Name"],
            "yahoosymbol": row["yahoo_symbol"],
            "ETF": row["ETF"],
        }
        for _, row in market_df.iterrows()
    ]


def build_stock_list_payload(df: pd.DataFrame) -> dict:
    """JSON 저장용 전체 페이로드 생성"""
    etf_count = int((df["ETF"] == "Y").sum())
    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": (
            "FinanceDataReader(KRX) + Naver Finance ETF list + "
            "Yahoo Finance symbol mapping"
        ),
        "markets": {
            "KOSPI": build_market_records(df, "KOSPI"),
            "KOSDAQ": build_market_records(df, "KOSDAQ"),
        },
        "counts": {
            "KOSPI": int((df["Market"] == "KOSPI").sum()),
            "KOSDAQ": int((df["Market"] == "KOSDAQ").sum()),
            "ETF": etf_count,
            "total": int(len(df)),
        },
    }


def save_stock_list(output_file: Path = OUTPUT_FILE) -> dict:
    """종목 목록을 조회해 JSON 파일로 저장"""
    etf_codes = fetch_etf_code_set()
    krx_listing = fetch_krx_listing(etf_codes)
    etf_listing = fetch_etf_listing(etf_codes)
    listing = merge_with_etf_listing(krx_listing, etf_listing)
    payload = build_stock_list_payload(listing)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    return payload


def main() -> None:
    payload = save_stock_list()
    print(
        f"저장 완료: {OUTPUT_FILE} "
        f"(KOSPI {payload['counts']['KOSPI']}개, "
        f"KOSDAQ {payload['counts']['KOSDAQ']}개, "
        f"ETF {payload['counts']['ETF']}개)"
    )


if __name__ == "__main__":
    main()
