# KOSPI/KOSDAQ 종목 목록 생성 (`kospilist_dataproc.py`)

코스피·코스닥 상장 종목과 ETF 정보를 수집·병합하고, ETF에는 섹터 분류와 **구성종목(`elements`)** 을 채운 뒤 `kospilist.json`으로 저장하는 스크립트입니다.

---

## 디렉터리 구조

```
data/kospilist/
├── kospilist_dataproc.py   # 종목 목록 수집·변환·섹터 분류·구성종목 수집 스크립트
├── kospilist.json          # 생성된 종목 목록 JSON (출력)
└── README.md               # 본 문서
```

---

## 입·출력 한눈에 보기

| 구분 | 내용 |
|------|------|
| **입력(Input)** | 외부 API/라이브러리 응답 (파일 입력 없음) |
| **중간 데이터** | `pandas.DataFrame` (Code, Name, Market, yahoo_symbol, ETF) + ETF 코드별 `elements` 맵 |
| **출력(Output)** | `data/kospilist/kospilist.json` |
| **콘솔** | 구성종목 수집 진행 로그 → `저장 완료: ... (KOSPI N개, KOSDAQ N개, ETF N개)` |

### 입력 소스

| 소스 | 역할 | 샘플 |
|------|------|------|
| **Naver Finance ETF API** | ETF 코드·종목명 | `{ "itemcode": "069500", "itemname": "KODEX 200" }` |
| **Naver Finance ETF 구성종목 API** | ETF별 편입 종목명 목록 | `{ "itemName": "삼성전자", ... }` (페이지네이션) |
| **FinanceDataReader `StockListing("KRX")`** | KOSPI/KOSDAQ 상장 종목 | `Code=005930`, `Name=삼성전자`, `Market=KOSPI` |
| **Yahoo 심볼 규칙** | 시장 접미사 | KOSPI → `.KS`, KOSDAQ → `.KQ` |

### 출력 샘플 (`kospilist.json` 일부)

```json
{
  "updated_at": "2026-09-07T07:16:41Z",
  "source": "FinanceDataReader(KRX) + Naver Finance ETF list + Naver Finance ETF constituent list + Yahoo Finance symbol mapping",
  "markets": {
    "KOSPI": [
      {
        "code": "005930",
        "name": "삼성전자",
        "yahoosymbol": "005930.KS",
        "ETF": "N",
        "sector": "",
        "elements": ""
      },
      {
        "code": "069500",
        "name": "KODEX 200",
        "yahoosymbol": "069500.KS",
        "ETF": "Y",
        "sector": "기타",
        "elements": ["삼성전자", "SK하이닉스", "SK스퀘어", "삼성바이오로직스", "현대차"]
      },
      {
        "code": "0000Z0",
        "name": "RISE 바이오TOP10액티브",
        "yahoosymbol": "0000Z0.KS",
        "ETF": "Y",
        "sector": "바이오",
        "elements": ["셀트리온", "삼성바이오로직스", "..."]
      }
    ],
    "KOSDAQ": [
      {
        "code": "035720",
        "name": "카카오",
        "yahoosymbol": "035720.KQ",
        "ETF": "N",
        "sector": "",
        "elements": ""
      }
    ]
  },
  "counts": {
    "KOSPI": 2110,
    "KOSDAQ": 1772,
    "ETF": 1167,
    "total": 3882
  }
}
```

> - 일반 주식(`ETF=N`): `sector=""`, `elements=""` (공백 문자열)
> - ETF(`ETF=Y`): `sector`는 섹터 문자열, `elements`는 구성종목명 **list** (조회 실패·없음이면 `[]`)

---

## 처리 흐름 (단계별)

```
1. Naver ETF API → ETF 코드 집합(set)
        ↓
2. FinanceDataReader(KRX) → KOSPI/KOSDAQ DataFrame + ETF 여부(Y/N)
        ↓
3. Naver ETF 목록 → DataFrame (Market=KOSPI, ETF=Y)
        ↓
4. KRX에 없는 ETF만 병합
        ↓
5. ETF 구성종목 수집 (Naver constituent API, 병렬)
        ↓
6. 시장별 레코드 생성 (ETF면 섹터 분류 + elements 매핑)
        ↓
7. JSON 페이로드 구성 → kospilist.json 저장
```

`save_stock_list()`가 위 순서를 한 번에 실행합니다.

---

## 단계별 상세 (샘플 포함)

### Step 0. 공통 유틸

#### `normalize_code(code)` — 종목코드 정규화

| 입력 샘플 | 출력 샘플 | 설명 |
|-----------|-----------|------|
| `"5930"` | `"005930"` | 숫자만이면 6자리 zero-padding |
| `"005930"` | `"005930"` | 이미 6자리면 그대로 |
| `"0167A0"` | `"0167A0"` | 영문 포함 코드는 대문자만 유지 |
| `" 069500 "` | `"069500"` | 공백 제거 |

#### `to_yahoo_symbol(code, market)` — Yahoo 심볼 변환

| 입력 샘플 | 출력 샘플 |
|-----------|-----------|
| `("005930", "KOSPI")` | `"005930.KS"` |
| `("035720", "KOSDAQ")` | `"035720.KQ"` |

---

### Step 1. `fetch_etf_code_set()` — ETF 코드 집합 조회

**입력:** Naver Finance API  
`https://finance.naver.com/api/sise/etfItemList.nhn`

**API 응답 샘플 (개념):**

```json
{
  "result": {
    "etfItemList": [
      { "itemcode": "069500", "itemname": "KODEX 200" },
      { "itemcode": "0000Z0", "itemname": "RISE 바이오TOP10액티브" }
    ]
  }
}
```

**출력 샘플:**

```python
{"069500", "0000Z0", ...}  # normalize_code 적용된 set[str]
```

이후 단계에서 “이 코드가 ETF인가?”를 판별하는 기준 집합으로 쓰입니다.

---

### Step 2. `fetch_krx_listing(etf_codes)` — KRX 상장 종목 조회

**입력:**
- `fdr.StockListing("KRX")` (FinanceDataReader)
- Step 1의 ETF 코드 집합

**중간 데이터 샘플 (DataFrame 행):**

| Code | Name | Market | yahoo_symbol | ETF |
|------|------|--------|--------------|-----|
| `005930` | 삼성전자 | KOSPI | `005930.KS` | `N` |
| `069500` | KODEX 200 | KOSPI | `069500.KS` | `Y` |
| `035720` | 카카오 | KOSDAQ | `035720.KQ` | `N` |

**처리 요약:**
1. `Market`이 `KOSPI` / `KOSDAQ`인 행만 유지
2. `Code` 정규화, `Name` trim
3. `yahoo_symbol` 생성 (`.KS` / `.KQ`)
4. 코드가 ETF 집합에 있으면 `ETF="Y"`, 아니면 `"N"`
5. `Market`, `Code` 기준 정렬

> KRX 목록에 ETF가 빠지는 경우가 있어, 다음 단계에서 Naver ETF를 별도로 붙입니다.

---

### Step 3. `fetch_etf_listing(etf_codes)` — Naver ETF → DataFrame

**입력:** 동일 Naver ETF API + Step 1의 코드 집합

**출력 행 샘플:**

| Code | Name | Market | yahoo_symbol | ETF |
|------|------|--------|--------------|-----|
| `069500` | KODEX 200 | KOSPI | `069500.KS` | `Y` |
| `0000Z0` | RISE 바이오TOP10액티브 | KOSPI | `0000Z0.KS` | `Y` |

**규칙:**
- 모든 ETF 레코드의 `Market`은 `"KOSPI"` (API에 시장 구분 없음)
- Yahoo 심볼은 항상 `{code}.KS`
- `Code` 기준 중복 제거

---

### Step 4. `merge_with_etf_listing(krx_listing, etf_listing)` — 누락 ETF 병합

**입력 샘플 개념:**
- KRX에 이미 있음: `069500`
- KRX에 없음 (Naver에만 있음): `0000Z0`

**동작:**
1. KRX에 **이미 있는** ETF 코드 → 추가하지 않음 (중복 방지)
2. KRX에 **없는** ETF 코드 → KOSPI 쪽으로 append
3. 최종 DataFrame을 `Market`, `Code`로 재정렬

**출력:** 일반 주식 + (KRX에 있던) ETF + (Naver에서만 온) ETF가 합쳐진 하나의 DataFrame

---

### Step 5. ETF 구성종목 수집 (`elements`)

병합 결과에서 `ETF == "Y"`인 코드만 대상으로, Naver 구성종목 API를 호출해 종목명 리스트를 만듭니다.

**API:**  
`https://m.stock.naver.com/front-api/stock/domestic/etf/constituent/list?code={종목코드}`

**응답 개념 샘플:**

```json
{
  "isSuccess": true,
  "result": {
    "totalCount": 202,
    "hasNext": true,
    "nextCursor": "...",
    "result": [
      { "itemCode": "005930", "itemName": "삼성전자", "constituentWeight": 33.46 },
      { "itemCode": "000660", "itemName": "SK하이닉스", "constituentWeight": 26.26 }
    ]
  }
}
```

#### 5-1. `fetch_etf_elements(code)` — 단일 ETF 구성종목

| 항목 | 내용 |
|------|------|
| 페이지 크기 | API 기본 약 10건/페이지 |
| 페이지네이션 | `hasNext` / `nextCursor`로 전체 수집 |
| 저장 값 | `itemName` 문자열 리스트 (코드가 없는 현금·채권명 등도 이름 있으면 포함) |
| 페이지 간 대기 | `ETF_ELEMENTS_SLEEP_SECONDS` (기본 `0.05`) |

**출력 샘플 (`069500` KODEX 200):**

```python
["삼성전자", "SK하이닉스", "SK스퀘어", "삼성바이오로직스", "현대차", ...]  # 예: 202건
```

#### 5-2. `fetch_etf_elements_map(etf_codes)` — 전체 ETF 병렬 수집

| 항목 | 내용 |
|------|------|
| 병렬 | `ThreadPoolExecutor` (`ETF_ELEMENTS_WORKERS`, 기본 `8`) |
| 실패 시 | 해당 코드는 `[]`로 넣고 경고 로그 후 계속 |
| 진행 로그 | `구성종목 수집 진행: N/총개수` (1·50단위·마지막) |

**출력 샘플:**

```python
{
  "069500": ["삼성전자", "SK하이닉스", ...],
  "0000Z0": ["셀트리온", ...],
  ...
}
```

> 구성종목 수집은 ETF 수·편입 종목 수에 따라 수 분 걸릴 수 있습니다.

---

### Step 6. 섹터 분류 (ETF만)

시장별 JSON을 만들 때 `ETF == "Y"`인 종목에만 `get_accurate_sector(code, name)`를 호출합니다.

#### 6-1. `get_accurate_sector(code, name)` 우선순위

| 순서 | 방식 | 샘플 입력 | 샘플 출력 |
|------|------|-----------|-----------|
| 1 | 전문가 하드코딩 맵 | `code="463250"` (TIGER K방산&우주) | `"방산"` |
| 2 | 세분화 테마 키워드 | 이름에 `"데이터센터"` | `"데이터센터"` |
| 3 | 16대 섹터 키워드 | 이름에 `"바이오"` | `"바이오"` |
| 4 | 매칭 실패 | 지수/채권형 등 | `"기타"` |

#### 6-2. `is_korea_related_etf(name)` — 해외 ETF 필터

섹터가 `"기타"`가 아닌데도 이름에 해외 키워드(미국, NASDAQ, 엔비디아 등)만 있고 한국 관련 키워드가 없으면 → 최종 `sector`를 `"기타"`로 바꿉니다.

| 종목명 샘플 | 결과 |
|-------------|------|
| `PLUS 한화그룹주` | 한국 관련 → 섹터 유지 (`지주사`) |
| `TIGER 엔비디아미국채커버드콜...` | 해외 중심 → `"기타"` |
| `RISE 바이오TOP10액티브` | 해외 표기 없음 → 국내 테마로 간주 |

#### 섹터 값 예시

`휴머노이드`, `데이터센터`, `광통신`, `원자력`, `화장품`, `전선`, `방산`, `반도체`, `2차전지`, `전력`, `에너지`, `인프라`, `기계`, `바이오`, `IT/플랫폼`, `금융`, `화학/소재`, `소비재`, `자동차`, `K-컬처`, `조선/해운`, `지주사`, `기타`

---

### Step 7. `build_market_records(df, market, elements_map)` — 시장별 JSON 레코드

**입력:** 병합 DataFrame + `"KOSPI"` / `"KOSDAQ"` + Step 5의 `elements_map`

**출력 레코드 스키마:**

| JSON Key | 설명 | 샘플 |
|----------|------|------|
| `code` | 종목코드 | `"005930"` |
| `name` | 종목명 | `"삼성전자"` |
| `yahoosymbol` | Yahoo 심볼 | `"005930.KS"` |
| `ETF` | ETF 여부 | `"Y"` / `"N"` |
| `sector` | ETF만 분류, 일반주는 `""` | `"바이오"` / `""` |
| `elements` | ETF면 구성종목 **list**, 일반주면 `""` | `["삼성전자", ...]` / `""` |

---

### Step 8. `build_stock_list_payload(df, elements_map)` → `save_stock_list()`

**페이로드 구조:**

```json
{
  "updated_at": "UTC ISO8601",
  "source": "FinanceDataReader(KRX) + Naver Finance ETF list + Naver Finance ETF constituent list + Yahoo Finance symbol mapping",
  "markets": { "KOSPI": [...], "KOSDAQ": [...] },
  "counts": { "KOSPI": N, "KOSDAQ": N, "ETF": N, "total": N }
}
```

**저장:**
- 경로: `data/kospilist/kospilist.json` (`OUTPUT_FILE`)
- 인코딩: UTF-8, `indent=2`, `ensure_ascii=False`
- 기존 파일이 있으면 덮어씀

---

## 실행 방법

### 1. 의존성 설치

프로젝트 루트(`stockai/`)에서:

```powershell
cd d:\myproject\stockai
py -m pip install -r requirements.txt
```

필요 패키지: `finance-datareader`, `pandas`, `requests`, `urllib3`

### 2. 스크립트 실행

```powershell
py data\kospilist\kospilist_dataproc.py
```

### 3. 결과 확인

- 파일: `data/kospilist/kospilist.json`
- 콘솔 예:

```
ETF 구성종목 수집 시작 (1167개)
  구성종목 수집 진행: 1/1167
  구성종목 수집 진행: 50/1167
  ...
  구성종목 수집 진행: 1167/1167
저장 완료: D:\myproject\stockai\data\kospilist\kospilist.json (KOSPI 2110개, KOSDAQ 1772개, ETF 1167개)
```

---

## 실행 결과 (최근 생성 기준)

| 항목 | 종목 수 | 설명 |
|------|---------|------|
| KOSPI | 2,110 | 일반 종목 + ETF |
| KOSDAQ | 1,772 | 일반 종목 |
| ETF (`Y`) | 1,167 | ETF 상품 (`elements` list 포함) |
| **합계** | **3,882** | 전체 레코드 |

---

## 참고 사항

- **SSL 검증:** Naver API 호출 시 `SSL_VERIFY = False` (로컬 SSL 이슈 대응)
- **ETF 시장:** Naver API에 시장 정보가 없어, 병합으로 추가된 ETF는 모두 `KOSPI`에 넣음
- **섹터:** 일반 주식은 `sector=""`, ETF만 키워드/전문가맵으로 분류
- **구성종목(`elements`):** 일반 주식은 `""`, ETF는 종목명 list. 채권·현금성 자산 등은 코드 없이 이름만 올 수 있음
- **병렬·대기:** `ETF_ELEMENTS_WORKERS=8`, `ETF_ELEMENTS_SLEEP_SECONDS=0.05` (페이지·부하 조절용)
- **ETN:** 대상에서 제외
- **재실행:** `kospilist.json`을 덮어쓰며 `updated_at`을 갱신. 구성종목까지 다시 조회하므로 전체 실행 시간이 길어질 수 있음

---

## 관련 파일

| 파일 | 역할 |
|------|------|
| `kospilist_dataproc.py` | 종목 수집·병합·섹터 분류·구성종목 수집·저장 |
| `kospilist.json` | 최종 종목 목록 (`sector`, `elements` 포함) |
| `../../requirements.txt` | 프로젝트 의존성 |
| `../../ref_etf.py` / `../../ref_stockanly.py` | `elements`를 툴팁·그리드 표시에 사용 |
