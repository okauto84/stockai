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


def is_korea_related_etf(name: str) -> bool:
    """한국(Korea) 관련 ETF 여부 판별"""
    name_upper = name.upper()

    korea_keywords = [
        "코리아",
        "한국",
        "KOREA",
        "KRX",
        "KOSPI",
        "KOSDAQ",
        "K방산",
        "K-방산",
        "K-컬처",
        "K컬처",
        "KPOP",
        "K-POP",
        "삼성",
        "현대차",
        "현대",
        "SK하이닉스",
        "하이닉스",
        "네이버",
        "카카오",
        "한화",
        "LG에너지",
        "LG화학",
        "기아",
        "포스코",
        "셀트리온",
        "대한전선",
        "일진전기",
    ]
    overseas_keywords = [
        "미국",
        "중국",
        "일본",
        "유럽",
        "글로벌",
        "월드",
        "WORLD",
        "GLOBAL",
        "나스닥",
        "NASDAQ",
        "S&P",
        "SP500",
        "S&P500",
        "필라델피아",
        "인도",
        "대만",
        "베트남",
        "브라질",
        "신흥",
        "MSCI",
        "차이나",
        "CHINA",
        "홍콩",
        "HONGKONG",
        "TAIWAN",
        "JAPAN",
        "EUROPE",
        "INDIA",
        "엔비디아",
        "NVIDIA",
        "테슬라",
        "TESLA",
        "애플",
        "APPLE",
        "아마존",
        "AMAZON",
        "구글",
        "GOOGLE",
        "메타플랫폼",
        "마이크로소프트",
        "MICROSOFT",
        "브로드컴",
        "BROADCOM",
        "팔란티어",
        "PALANTIR",
        "BYD",
        "TSMC",
        "달러",
        "엔화",
        "QQQ",
        "SOXX",
        "다우존스",
        "DOW",
        "러셀",
        "RUSSELL",
    ]

    has_korea = any(keyword.upper() in name_upper for keyword in korea_keywords)
    if has_korea:
        return True

    has_overseas = any(keyword.upper() in name_upper for keyword in overseas_keywords)
    if has_overseas:
        return False

    # 해외 표기가 없으면 국내 테마 ETF로 간주
    return True


def get_accurate_sector(code: str, name: str) -> str:
    """ETF 종목코드·종목명 기반 섹터 분류"""
    # 1. [전문가 매핑] PDF(자산구성내역) 분석 기반 하드코딩
    expert_mapping = {
        "0040S0": "기계",  # HANARO 글로벌피지컬AI액티브 (로봇/자동화 중심)
        "433250": "IT/플랫폼",  # UNICORN R&D 액티브 (SK하이닉스, 네이버 등 대형 IT)
        "433220": "IT/플랫폼",  # 에셋플러스 글로벌대장장이액티브
        "0222F0": "데이터센터",  # 마이티 AI데이터센터밸류체인
        "0150K0": "전력",  # KoAct 수소전력ESS인프라액티브 (HD현대일렉트릭 등 전력기기)
        "491820": "전선",  # HANARO 전력설비투자 (LS, 일진전기, 대한전선 비중 높음)
        "487240": "전력",  # KODEX AI전력핵심설비 (변압기, 송배전 중심)
        "0173Y0": "광통신",  # KODEX 미국AI광통신네트워크
        "0215T0": "광통신",  # HANARO 미국AI광통신TOP10
        "0219B0": "광통신",  # KoAct 광통신&위성네트워크액티브
        "0051A0": "반도체",  # KoAct 브로드컴밸류체인액티브
        "0093D0": "IT/플랫폼",  # KoAct 팔란티어밸류체인액티브
        "0142D0": "데이터센터",  # TIGER 미국AI데이터센터TOP4Plus
        "0101N0": "전력",  # RISE AI전력인프라
        "0117V0": "전력",  # TIGER 코리아AI전력기기TOP3플러스
        "0079X0": "2차전지",  # ACE BYD밸류체인액티브
        "044091": "방산",  # WON 미국우주항공방산
        "463250": "방산",  # TIGER K방산&우주
        "0204D0": "기계",  # KODEX 현대차로보틱스밸류체인TOP3플러스
        "0115E0": "IT/플랫폼",  # KODEX 코리아소버린AI
        "474920": "IT/플랫폼",  # 에셋플러스 차이나일등기업포커스10액티브
    }

    if code in expert_mapping:
        sector = expert_mapping[code]
    else:
        name_upper = name.upper()

        # 2. [세분화된 주도 테마 우선 추출] (조건문 순서 엄수)
        if any(k in name_upper for k in ["휴머노이드"]):
            sector = "휴머노이드"
        elif any(k in name_upper for k in ["데이터센터", "DATACENTER"]):
            sector = "데이터센터"
        elif any(k in name_upper for k in ["광통신"]):
            sector = "광통신"
        elif any(k in name_upper for k in ["원자력", "SMR"]):
            sector = "원자력"
        elif any(k in name_upper for k in ["화장품", "뷰티", "COSMETIC", "BEAUTY"]):
            sector = "화장품"
        elif any(k in name_upper for k in ["전선"]):
            sector = "전선"
        # 3. [기존 16대 섹터 정밀 분류]
        elif any(
            k in name_upper
            for k in ["방산", "국방", "우주", "위성", "AEROSPACE", "DEFENSE"]
        ):
            sector = "방산"
        elif any(
            k in name_upper
            for k in [
                "반도체",
                "엔비디아",
                "TSMC",
                "필라델피아",
                "HBM",
                "팹리스",
                "파운드리",
                "ASIC",
                "CHIP",
            ]
        ):
            sector = "반도체"
        elif any(
            k in name_upper
            for k in ["2차전지", "2차 전지", "배터리", "전고체", "음극재", "양극재", "리튬"]
        ):
            sector = "2차전지"
        elif any(k in name_upper for k in ["전력", "그리드", "GRID", "변압기", "ESS"]):
            sector = "전력"
        elif any(
            k in name_upper
            for k in [
                "에너지",
                "태양광",
                "수소",
                "원유",
                "천연가스",
                "클린",
                "친환경",
                "탄소",
                "기후",
            ]
        ):
            sector = "에너지"
        elif any(k in name_upper for k in ["인프라", "통신", "NETWORK", "네트워크"]):
            sector = "인프라"
        elif any(k in name_upper for k in ["기계", "로봇", "로보틱스", "자동화", "장비"]):
            sector = "기계"  # 휴머노이드는 위에서 먼저 걸러짐
        elif any(
            k in name_upper
            for k in [
                "바이오",
                "의료",
                "헬스케어",
                "치료제",
                "신약",
                "메디컬",
                "제약",
                "건강",
                "CDMO",
            ]
        ):
            sector = "바이오"
        elif any(
            k in name_upper
            for k in [
                "IT",
                "소프트웨어",
                "플랫폼",
                "메타버스",
                "AI",
                "클라우드",
                "게임",
                "인터넷",
                "나스닥",
                "테크",
                "빅테크",
                "사이버보안",
                "웹툰",
            ]
        ):
            sector = "IT/플랫폼"
        elif any(
            k in name_upper
            for k in ["금융", "은행", "증권", "보험", "리츠", "REITS", "부동산", "배당"]
        ):
            sector = "금융"
        elif any(
            k in name_upper
            for k in [
                "화학",
                "소재",
                "희토류",
                "철강",
                "비철금속",
                "금선물",
                "은선물",
                "구리",
                "팔라듐",
                "농산물",
                "콩",
            ]
        ):
            sector = "화학/소재"
        elif any(
            k in name_upper
            for k in ["소비재", "여행", "레저", "푸드", "의류", "내수", "럭셔리"]
        ):
            sector = "소비재"  # 화장품은 위에서 먼저 걸러짐
        elif any(
            k in name_upper
            for k in ["자동차", "모빌리티", "자율주행", "전기차", "스마트카", "운송"]
        ):
            sector = "자동차"
        elif any(
            k in name_upper
            for k in ["K-컬처", "KPOP", "미디어", "엔터", "콘텐츠", "드라마"]
        ):
            sector = "K-컬처"
        elif any(k in name_upper for k in ["조선", "해운", "선박", "SHIPBUILDING"]):
            sector = "조선/해운"
        elif any(k in name_upper for k in ["지주사", "그룹", "기업지배구조", "탑픽"]):
            sector = "지주사"
        else:
            # 4. 범용 지수 및 채권 파생상품은 기타 처리
            sector = "기타"

    # 한국과 관련 없는 해외 ETF는 기타로 편입
    if sector != "기타" and not is_korea_related_etf(name):
        return "기타"
    return sector


def build_market_records(df: pd.DataFrame, market: str) -> list[dict]:
    """시장별 종목 레코드 생성"""
    market_df = df[df["Market"] == market]
    records = []
    for _, row in market_df.iterrows():
        is_etf = row["ETF"] == "Y"
        records.append(
            {
                "code": row["Code"],
                "name": row["Name"],
                "yahoosymbol": row["yahoo_symbol"],
                "ETF": row["ETF"],
                "sector": (
                    get_accurate_sector(row["Code"], row["Name"]) if is_etf else ""
                ),
            }
        )
    return records


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
