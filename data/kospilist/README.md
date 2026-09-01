# KOSPI/KOSDAQ 종목 목록 생성 (`dataprocessing.py`)

코스피·코스닥 상장 종목과 ETF 정보를 수집하여 `kospilist.json` 파일로 저장하는 데이터 처리 스크립트입니다.

---

## 디렉터리 구조

```
data/kospilist/
├── dataprocessing.py   # 종목 목록 수집·변환 스크립트
├── kospilist.json      # 생성된 종목 목록 JSON
└── README.md           # 본 문서
```

---

## 데이터 소스

| 소스 | 용도 |
|------|------|
| **FinanceDataReader (KRX)** | 코스피·코스닥 일반 상장 종목 코드·종목명 조회 |
| **Naver Finance ETF API** | ETF 전 종목 코드·종목명 조회 및 ETF 여부 판별 |
| **Yahoo Finance 심볼 규칙** | 시장별 접미사 매핑 (`.KS` / `.KQ`) |

> FinanceDataReader의 `StockListing("KRX")`에는 ETF 종목이 포함되지 않는 경우가 있어, Naver Finance ETF 목록을 별도로 조회하여 병합합니다.

---

## 처리 흐름

```
1. Naver Finance에서 ETF 코드 집합 조회
        ↓
2. FinanceDataReader로 KOSPI/KOSDAQ 종목 조회 + ETF 여부(Y/N) 표시
        ↓
3. KRX 목록에 없는 ETF 종목을 Naver 목록에서 추가
        ↓
4. 시장별(KOSPI/KOSDAQ) JSON 레코드 생성
        ↓
5. kospilist.json 저장
```

---

## 적용 로직 상세

### 1. `normalize_code(code)`

종목코드를 비교·저장용으로 정규화합니다.

- 공백 제거, 대문자 변환
- 숫자-only 코드: 6자리 zero-padding (예: `5930` → `005930`)
- 영문 혼합 코드: 그대로 유지 (예: `0167A0`)

### 2. `to_yahoo_symbol(code, market)`

Yahoo Finance 조회용 심볼을 생성합니다.

| 시장 | 접미사 | 예시 |
|------|--------|------|
| KOSPI | `.KS` | `005930.KS` |
| KOSDAQ | `.KQ` | `035720.KQ` |

### 3. `fetch_etf_code_set()`

Naver Finance ETF API에서 ETF 종목 코드 집합(`set`)을 수집합니다.

- API: `https://finance.naver.com/api/sise/etfItemList.nhn`
- 반환: 정규화된 ETF 코드 집합

### 4. `fetch_krx_listing(etf_codes)`

FinanceDataReader로 KRX 상장 종목을 조회합니다.

- 대상 시장: `KOSPI`, `KOSDAQ`만 필터링
- `yahoo_symbol` 컬럼 생성
- `ETF` 컬럼: 코드가 ETF 집합에 포함되면 `"Y"`, 아니면 `"N"`

### 5. `fetch_etf_listing(etf_codes)`

Naver Finance ETF 목록을 DataFrame으로 변환합니다.

- 모든 ETF 레코드: `Market = "KOSPI"`, `ETF = "Y"`
- Yahoo 심볼: `{code}.KS` 형식

> 국내 ETF는 Yahoo Finance 기준 대부분 `.KS`(KSC) 심볼을 사용합니다.

### 6. `merge_with_etf_listing(krx_listing, etf_listing)`

KRX 목록과 ETF 목록을 병합합니다.

- KRX 목록에 **이미 존재하는** ETF 코드: 중복 추가하지 않음
- KRX 목록에 **없는** ETF 코드: KOSPI 섹션에 추가
- 최종 DataFrame을 `Market`, `Code` 기준 정렬

### 7. `build_market_records(df, market)`

시장별 JSON 레코드 배열을 생성합니다.

| JSON Key | 설명 |
|----------|------|
| `code` | 종목코드 |
| `name` | 종목명 |
| `yahoosymbol` | Yahoo Finance 심볼 |
| `ETF` | ETF 여부 (`Y` / `N`) |

### 8. `build_stock_list_payload(df)`

최종 JSON 페이로드를 구성합니다.

- `updated_at`: UTC 기준 생성 시각
- `source`: 데이터 출처 설명
- `markets`: `KOSPI`, `KOSDAQ` 배열
- `counts`: 시장별·ETF·전체 종목 수

### 9. `save_stock_list()`

위 로직을 순서대로 실행하고 `kospilist.json` 파일로 저장합니다.

---

## JSON 출력 형식

```json
{
  "updated_at": "2026-09-01T06:52:37Z",
  "source": "FinanceDataReader(KRX) + Naver Finance ETF list + Yahoo Finance symbol mapping",
  "markets": {
    "KOSPI": [
      {
        "code": "005930",
        "name": "삼성전자",
        "yahoosymbol": "005930.KS",
        "ETF": "N"
      },
      {
        "code": "069500",
        "name": "KODEX 200",
        "yahoosymbol": "069500.KS",
        "ETF": "Y"
      }
    ],
    "KOSDAQ": [
      {
        "code": "035720",
        "name": "카카오",
        "yahoosymbol": "035720.KQ",
        "ETF": "N"
      }
    ]
  },
  "counts": {
    "KOSPI": 2106,
    "KOSDAQ": 1772,
    "ETF": 1163,
    "total": 3878
  }
}
```

---

## 실행 방법

### 1. 의존성 설치

프로젝트 루트(`stockai/`)에서 실행:

```powershell
cd d:\myproject\stockai
py -m pip install -r requirements.txt
```

필요 패키지:

- `finance-datareader`
- `pandas`
- `requests`
- `urllib3`

### 2. 스크립트 실행

```powershell
py data\kospilist\dataprocessing.py
```

### 3. 실행 결과 확인

- 출력 파일: `data/kospilist/kospilist.json`
- 콘솔에 KOSPI/KOSDAQ/ETF 종목 수가 출력됩니다.

---

## 실행 결과 (최근 실행 기준)

```
저장 완료: D:\myproject\stockai\data\kospilist\kospilist.json (KOSPI 2106개, KOSDAQ 1772개, ETF 1163개)
```

| 항목 | 종목 수 | 설명 |
|------|---------|------|
| KOSPI | 2,106 | 일반 종목 + ETF |
| KOSDAQ | 1,772 | 일반 종목 |
| ETF (`Y`) | 1,163 | ETF 상품 |
| **합계** | **3,878** | 전체 레코드 |

### 종목 유형별 분류

| 유형 | ETF 값 | 개수 | 설명 |
|------|--------|------|------|
| 일반 주식 | `N` | 2,715 | FinanceDataReader KRX 목록 |
| ETF | `Y` | 1,163 | Naver Finance ETF 목록에서 추가 |

---

## 참고 사항

- **SSL 검증**: Naver Finance API 호출 시 `SSL_VERIFY = False`로 설정되어 있습니다. (로컬 SSL 인증서 이슈 대응)
- **ETF 시장 분류**: Naver ETF API에는 시장(KOSPI/KOSDAQ) 정보가 없어, 추가된 ETF는 모두 `KOSPI` 섹션에 포함됩니다.
- **ETN 미포함**: ETN(Exchange Traded Note)은 본 스크립트 대상에서 제외됩니다.
- **재실행**: 스크립트 실행 시 `kospilist.json`이 덮어씌워지며, `updated_at`이 최신 시각으로 갱신됩니다.

---

## 관련 파일

| 파일 | 역할 |
|------|------|
| `dataprocessing.py` | 종목 수집·변환·저장 로직 |
| `kospilist.json` | 최종 종목 목록 데이터 |
| `../../requirements.txt` | 프로젝트 의존성 정의 |
