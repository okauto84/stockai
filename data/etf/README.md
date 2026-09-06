# ETF 섹터별 150일 분석 그리드 (`etf_dataproc.py`)

`kospilist.json`에서 ETF(`ETF=Y`)를 섹터별로 모은 뒤, Yahoo Finance(`yfinance`)로 주가를 조회하고 `ref_stockanly.py`와 동일한 150일 분석 그리드를 만들어 `data/etf/{섹터명}.json`으로 저장합니다.

---

## 디렉터리 구조

```
data/etf/
├── etf_dataproc.py      # ETF 섹터별 분석 그리드 수집·저장
├── 바이오.json           # 섹터별 출력 예시
├── IT_플랫폼.json        # 섹터명 "/" → "_" 로 파일명 변환
├── 2차전지.json
├── ...
└── README.md            # 본 문서

의존 입력:
data/kospilist/kospilist.json   # kospilist_dataproc.py 출력
```

---

## 입·출력 한눈에 보기

| 구분 | 내용 |
|------|------|
| **입력(Input)** | `data/kospilist/kospilist.json` |
| **외부 API** | `yfinance` (개별 ETF + 코스피 `^KS11`) |
| **중간 데이터** | 섹터별 ETF 목록, OHLCV history, 분석 그리드 DataFrame |
| **출력(Output)** | `data/etf/{섹터명}.json` (섹터당 1파일) |
| **제외** | `sector`가 빈 문자열(`""`) 또는 `"기타"`인 ETF |

### 입력 샘플 (`kospilist.json` → ETF 행)

```json
{
  "code": "0000Z0",
  "name": "RISE 바이오TOP10액티브",
  "yahoosymbol": "0000Z0.KS",
  "ETF": "Y",
  "sector": "바이오"
}
```

### 출력 샘플 (`data/etf/바이오.json` 요약)

```json
{
  "updated_at": "2026-09-06T16:17:54Z",
  "sector": "바이오",
  "source": "yfinance + ref_stockanly 150일 분석 그리드 로직",
  "analysis_days": 150,
  "grid_columns": [
    "날짜", "종가", "거래량", "코스피", "RS지수",
    "MA10", "MA20", "MA30", "MA50", "MA100", "MA150"
  ],
  "counts": {
    "requested": 21,
    "success": 21,
    "failed": 0
  },
  "items": [
    {
      "code": "0000Z0",
      "name": "RISE 바이오TOP10액티브",
      "yahoosymbol": "0000Z0.KS",
      "market": "KOSPI",
      "grid": [
        {
          "날짜": "2026-01-26",
          "종가": 16735.0,
          "거래량": 1309777,
          "코스피": 4949.59,
          "RS지수": 95.21,
          "MA10": 14944.0,
          "MA20": 15316.25,
          "MA30": 15234.67,
          "MA50": 15511.3,
          "MA100": null,
          "MA150": null
        }
      ]
    }
  ],
  "errors": []
}
```

> `grid`는 종목당 **최근 150거래일** 행입니다. 초반에는 긴 이동평균(`MA100`, `MA150`)이 `null`일 수 있습니다.

---

## 처리 흐름 (단계별)

```
1. kospilist.json 로드
        ↓
2. ETF='Y'만 추출 → 섹터별 그룹핑 ('기타'/빈 섹터 제외)
        ↓
3. 코스피 지수(^KS11) 1회 조회 (RS·병합용 공통 데이터)
        ↓
4. 섹터 내 각 ETF에 대해:
     - yfinance로 1년 일봉 조회
     - 150일 분석 그리드 생성 (MA, RS)
     - 종목 간 2초 sleep
        ↓
5. 섹터별 JSON 저장 → data/etf/{섹터명}.json
```

---

## 단계별 상세 (샘플 포함)

### Step 1. `load_etf_by_sector()` — 입력 로드·그룹핑

**입력 파일:** `data/kospilist/kospilist.json`

**필터 규칙:**

| 조건 | 결과 |
|------|------|
| `ETF != "Y"` | 스킵 (일반 주식) |
| `sector == ""` 또는 `"기타"` | 스킵 |
| 그 외 ETF | 해당 섹터 리스트에 추가 |

**중간 데이터 샘플 (`dict[str, list[dict]]`):**

```python
{
  "바이오": [
    {
      "market": "KOSPI",
      "code": "0000Z0",
      "name": "RISE 바이오TOP10액티브",
      "yahoosymbol": "0000Z0.KS",
      "sector": "바이오"
    },
    # ...
  ],
  "반도체": [ ... ],
  "IT/플랫폼": [ ... ]
}
```

- 섹터 키는 이름 오름차순 정렬
- 섹터 안 종목은 `code` 오름차순 정렬

---

### Step 2. `fetch_chart(symbol)` — 주가 수집

**입력 샘플:**
- ETF: `"0000Z0.KS"`
- 코스피: `"^KS11"`
- 기간: `period="1y"`, `interval="1d"`

**출력 샘플 (개념):**

```python
{
  "symbol": "0000Z0.KS",
  "name": "0000Z0.KS",          # include_info=False면 심볼 그대로
  "currency": "USD",
  "market_cap": None,
  "pe_ratio": None,
  "history": [
    {"date": "2025-09-08", "close": 14200.0, "volume": 520000},
    {"date": "2025-09-09", "close": 14350.0, "volume": 480000},
    # ... 약 1년치 일봉
  ]
}
```

`main()`에서는 코스피 차트를 **한 번만** 조회해 모든 ETF RS 계산에 재사용합니다.

---

### Step 3. `build_analysis_grid()` — 150일 분석 그리드

`ref_stockanly.py`의 150일 그리드와 동일 로직입니다.

**처리 요약:**

1. ETF history + 코스피 history를 `date`로 inner join
2. 이동평균 계산: `MA10` ~ `MA150` (`min_periods=window`)
3. RS지수 = `(종가 20일 수익률 / 코스피 20일 수익률) * 100`
4. 최근 `ANALYSIS_DAYS=150`행만 남김

**그리드 컬럼 (`GRID_COLUMNS`):**

| 컬럼 | 의미 | 샘플 |
|------|------|------|
| `날짜` | 거래일 | `"2026-01-26"` |
| `종가` | ETF 종가 | `16735.0` |
| `거래량` | 거래량 | `1309777` |
| `코스피` | `^KS11` 종가 | `4949.59` |
| `RS지수` | 20일 상대강도 | `95.21` |
| `MA10` … `MA150` | 종가 이동평균 | `14944.0` / `null` |

**데이터 샘플 (1행):**

```json
{
  "날짜": "2026-01-26",
  "종가": 16735.0,
  "거래량": 1309777,
  "코스피": 4949.59,
  "RS지수": 95.21,
  "MA10": 14944.0,
  "MA20": 15316.25,
  "MA30": 15234.67,
  "MA50": 15511.3,
  "MA100": null,
  "MA150": null
}
```

`grid_to_records()`가 DataFrame → JSON 직렬화 가능 dict 리스트로 변환하며, NaN은 `null`로 바꿉니다.

---

### Step 4. `build_sector_payload()` — 섹터 단위 수집

**입력:**
- `sector="바이오"`
- 해당 섹터 ETF 목록
- 공통 `kospi_chart`

**동작:**
1. 종목마다 `fetch_analysis_grid(yahoosymbol)` 호출
2. 성공 → `items`에 `{code, name, yahoosymbol, market, grid}` 추가
3. 실패 → `errors`에 `{..., error: "메시지"}` 추가 (전체 중단하지 않음)
4. 다음 종목 전 `time.sleep(2)` (`API_SLEEP_SECONDS`)

**페이로드 골격:**

```json
{
  "updated_at": "UTC",
  "sector": "바이오",
  "source": "yfinance + ref_stockanly 150일 분석 그리드 로직",
  "analysis_days": 150,
  "grid_columns": ["날짜", "종가", "..."],
  "counts": { "requested": 21, "success": 21, "failed": 0 },
  "items": [ /* 성공 종목 */ ],
  "errors": [ /* 실패 종목 */ ]
}
```

**에러 레코드 샘플:**

```json
{
  "code": "XXXXXX",
  "name": "예시 ETF",
  "yahoosymbol": "XXXXXX.KS",
  "market": "KOSPI",
  "error": "'XXXXXX.KS' 종목을 찾을 수 없습니다."
}
```

---

### Step 5. `save_sector_json()` / `sector_to_filename()` — 파일 저장

섹터명의 파일시스템 금지 문자를 `_`로 바꿉니다.

| 섹터명 (input) | 파일명 (output) |
|----------------|-----------------|
| `바이오` | `바이오.json` |
| `IT/플랫폼` | `IT_플랫폼.json` |
| `화학/소재` | `화학_소재.json` |
| `조선/해운` | `조선_해운.json` |
| `2차전지` | `2차전지.json` |

저장 경로: `data/etf/` (`OUTPUT_DIR`)

---

### Step 6. `main()` — 전체 오케스트레이션

콘솔 진행 로그 샘플:

```
1) kospilist 로드: D:\myproject\stockai\data\kospilist\kospilist.json
2) ETF 그룹핑 완료 · 섹터 22개 · ETF N개 ('기타' 제외)
3) 코스피 지수 조회: ^KS11
4~5) 섹터별 150일 분석 그리드 수집·저장 (종목 간격 2초)

[섹터] 바이오 · 21개
  [1/21] 바이오 · RISE 바이오TOP10액티브 (0000Z0.KS)
  ...
  저장: 바이오.json (성공 21 / 실패 0)

완료.
```

섹터 사이에도 2초 sleep을 둡니다.

---

## 주요 상수

| 상수 | 값 | 의미 |
|------|-----|------|
| `ANALYSIS_DAYS` | `150` | 그리드 행 수 |
| `RS_WINDOW` | `20` | RS 수익률 창 |
| `FETCH_PERIOD` | `"1y"` | yfinance 조회 기간 |
| `MA_WINDOWS` | `[10,20,30,50,100,150]` | 이동평균 창 |
| `API_SLEEP_SECONDS` | `2` | 종목/섹터 간 대기 |
| `KOSPI_SYMBOL` | `"^KS11"` | 코스피 지수 |
| `EXCLUDED_SECTORS` | `{"", "기타"}` | 분석 제외 섹터 |

---

## 실행 방법

### 1. 선행 조건

먼저 종목 목록을 생성해야 합니다.

```powershell
py data\kospilist\kospilist_dataproc.py
```

### 2. 의존성

프로젝트 루트에서:

```powershell
cd d:\myproject\stockai
py -m pip install -r requirements.txt
```

필요 패키지: `yfinance`, `pandas` (및 `kospilist.json` 생성에 쓰인 패키지)

### 3. 스크립트 실행

```powershell
py data\etf\etf_dataproc.py
```

> 섹터·종목 수에 비례해 시간이 오래 걸립니다 (종목당 약 2초 이상).

### 4. 결과 확인

- 출력 디렉터리: `data/etf/`
- 파일 예: `바이오.json`, `반도체.json`, `IT_플랫폼.json`, …

---

## 참고 사항

- **입력 의존:** `kospilist.json`이 없으면 `FileNotFoundError`로 종료
- **API 부하:** 종목마다 2초 sleep으로 Yahoo 요청 간격을 둠
- **부분 실패 허용:** 한 종목 실패해도 같은 섹터의 나머지·다른 섹터는 계속 처리
- **재실행:** 기존 `{섹터}.json`을 덮어씀 (`updated_at` 갱신)
- **로직 공유:** 그리드 계산은 `ref_stockanly.py`의 150일 분석 그리드와 동일

---

## 관련 파일

| 파일 | 역할 |
|------|------|
| `etf_dataproc.py` | ETF 섹터별 그리드 수집·저장 |
| `../kospilist/kospilist.json` | ETF 목록·섹터 입력 |
| `../kospilist/kospilist_dataproc.py` | 입력 JSON 생성 |
| `../../ref_stockanly.py` | 150일 분석 그리드 원본 로직 |
| `{섹터}.json` | 섹터별 출력 데이터 |
