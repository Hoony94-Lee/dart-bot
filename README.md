# dart-bot

DART 메자닌(CB/BW/EB) 및 유상증자 발행결정 공시를 실시간으로 텔레그램에 알림 발송하는 봇

## 기능

- **메자닌 (CB/BW/EB)** 발행결정 자동 수집 및 알림
- **유상증자** (사모 CPS/RCPS/CRPS/RPS, 공모) 발행결정 자동 수집 및 알림
- **공시 본문 자동 파싱**
  - 주식총수 대비 비율
  - Put Option / Call Option 행사기간
  - Call 비율, YTC
  - Refixing 한도
  - 인수인 / 대표주관회사
  - 우선배당률, 상환이율 (우선주)
  - 할증률 (교환사채), 할인율 (공모 유상증자)
  - 교환대상주식 (교환사채)
- **시가총액·종가 자동 조회** (NaverFinance → KRX → pykrx 다중 fallback)
- **종가 기준일 자동 판정**: 장 마감(15:30) 전 공시 → 전일 종가, 후 공시 → 당일 종가
- **영업시간 필터**: KST 06:00 ~ 20:30 외에는 발송 차단
- **중복 발송 방지**: `sent.json`에 발송 이력 기록

## 파일 구조

```
.
├── .github/workflows/
│   └── disclosure.yml        # GitHub Actions 워크플로우
├── send_disclosure.py        # 메인 스크립트 (텔레그램 발송)
├── disclosure_parser.py      # DART 공시 본문 파서 (document.xml 기반)
├── stock_data.py             # 주가/시가총액 조회 (NaverFinance/KRX/pykrx)
├── sent.json                 # 발송 이력 (최근 1000건)
└── README.md
```

## 환경변수 (GitHub Secrets)

GitHub 레포 → **Settings** → **Secrets and variables** → **Actions** 에 다음 3개 등록 필요:

| Secret | 설명 | 발급처 |
|--------|------|--------|
| `DART_API_KEY` | DART OpenAPI 인증키 | https://opendart.fss.or.kr |
| `TELEGRAM_TOKEN` | 텔레그램 봇 토큰 | @BotFather (텔레그램) |
| `TELEGRAM_CHAT_ID` | 알림 받을 채팅 ID | `getUpdates` API로 조회 |

## 실행 방식

### 자동 실행 (cron-job.org → GitHub Actions)

5분마다 cron-job.org가 GitHub Actions를 트리거하여 워크플로우가 실행됩니다.

**cron-job.org 설정값**

| 항목 | 값 |
|------|-----|
| URL | `https://api.github.com/repos/Hoony94-Lee/dart-bot/actions/workflows/disclosure.yml/dispatches` |
| Method | POST |
| Body | `{"ref":"main"}` |
| Schedule | 5분 |
| Headers | `Accept: application/vnd.github+json`<br>`Authorization: Bearer {GITHUB_PAT}`<br>`Content-Type: application/json`<br>`X-GitHub-Api-Version: 2022-11-28` |

### 수동 실행

GitHub Actions 탭 → DART Disclosure Alert → **Run workflow**

## 메시지 포맷

### CB / BW (사모 메자닌)
```
✅주요사항보고서(전환사채발행결정)
기업명: OO기업 (시가총액 XXX억원)
발행금액: 50억원
전환가액: 5,000원 (5/20 종가 4,820원)
주식총수 대비 비율: 7.94%

이사회결의일: 2026-05-20
발행일: 2026-05-28
만기일: 2031-05-28

Coupon/YTM: 0.0% / 2.0%
Refixing: 70%
Put Option: 발행일로부터 2년 후
Call Option: 발행일로부터 1년~2년
Call 비율: 60.0%
YTC: 3.0%
인수인: 코리아자산운용, ...

🔗 https://dart.fss.or.kr/...
```

### EB (교환사채)
CB/BW 포맷에서 다음 항목 추가:
- 교환가액 (전환가액/행사가액 대체)
- 할증률
- 교환대상주식 (자기주식 또는 회사명+보통주)

### 사모 유상증자 (CPS/RCPS)
```
✅주요사항보고서(유상증자결정)
기업명: OO기업 (시가총액 XXX억원)
신주의 종류: 상환전환우선주
발행금액: 50억원
전환가액: 5,000원 (5/20 종가 4,820원)
주식총수 대비 비율: 7.94%

이사회결의일: 2026-05-20
납입일: 2026-05-28

우선배당률: 1.0%(참가적, 누적적)
Refixing: 70%
Put Option: 발행일로부터 2년 후       ← RCPS/RPS만 표시
상환이율: 2.0%                        ← RCPS/RPS만 표시
Call Option: 발행일로부터 1년~2년
Call 비율: 60.0%
YTC: 3.0%
인수인: OO자산운용

🔗 ...
```

### 공모 유상증자
```
✅주요사항보고서(유상증자결정)
기업명: OO기업 (시가총액 XXX억원)
증자방식: 주주배정후 실권주 일반공모
발행금액: 500억원
신주의 종류와 수: 보통주 10,000,000주
예정 발행가액: 5,000원 (5/20 종가 5,500원)
주식총수 대비 비율: 25.00%
할인율: 25.0%

이사회결의일: 2026-05-20
구주주청약: 2026-07-15 ~ 2026-07-16
일반공모청약: 2026-07-21 ~ 2026-07-22
납입일: 2026-07-28
신주상장예정일: 2026-08-10
대표주관회사: 한국투자증권, 미래에셋증권

🔗 ...
```

## 의존성

- Python 3.11+
- `requests` (DART API, 텔레그램 API, NaverFinance)
- `lxml` (DART 공시 본문 XML 파싱)
- `pykrx` (선택사항, KRX 시세 fallback)

## 트러블슈팅

### 알림이 안 옴

1. **GitHub Actions 실행 로그 확인**: 레포 → Actions 탭 → 최근 실행 클릭
2. **영업시간 외 실행 여부 확인**: KST 06:00 ~ 20:30 외에는 의도적으로 차단됨
3. **cron-job.org 상태 확인**: 대시보드에서 마지막 실행 상태 (`204 No Content` = 정상)

### 일부 항목이 "-"로 표시됨

1. **공시 본문에 실제로 정보가 없는 경우**: 모든 메자닌이 Put/Call/Refixing을 가진 것은 아님
2. **새로운 공시 양식**: `disclosure_parser.py`에서 정규식 패턴 보강 필요

### 시가총액·종가가 "-"

1. **NaverFinance API 차단**: 짧은 시간 다수 호출 시 일시 차단 가능. KRX/pykrx fallback이 동작해야 함
2. **종목코드 미매핑**: DART `corp_code`와 매핑 안 되는 케이스 (신규 상장 등)

### 중복 알림 발송

1. **`sent.json` commit 실패**: GitHub Actions의 git push 단계에서 충돌 발생 시. 워크플로우 로그에서 `git pull --rebase` 부분 확인
2. **rcept_no 가 변경된 정정공시**: 별도 공시이므로 정상

## 라이선스

개인 사용 목적
