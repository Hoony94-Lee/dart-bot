"""
DART 공시 본문 파서 (메자닌 발행내역 자동 정리 스크립트 최신 패턴 반영)
- document.xml API 사용
- 메자닌 정리 스케줄(dart_mezzanine_auto.py)의 검증된 파싱 함수 동기화
- 봇 전용: capital_ratio, refixing, dividend_rate, redemption_rate,
           discount_rate, lead_managers, exchange_target, summarize_underwriters
"""
import re
import io
import zipfile
import requests
import datetime
import calendar
from lxml import etree

DART_API_BASE = "https://opendart.fss.or.kr/api"


# 스케줄 스크립트(dart_mezzanine_auto.py)의 log.debug 등 호출 무력화용 더미 로거
class _NullLog:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


log = _NullLog()


# ============== 본문 조회 (document.xml) ==============
def fetch_document_xml(dart_key, rcept_no):
    """DART document.xml API 호출. ZIP 안에서 가장 큰 XML 추출.
    공시 직후 원문 미생성(status 014) 시 '__NOT_READY__' 반환."""
    try:
        r = requests.get(
            f"{DART_API_BASE}/document.xml",
            params={"crtfc_key": dart_key, "rcept_no": rcept_no},
            timeout=60,
        )
        r.raise_for_status()
        blob = r.content
        print(f"[document.xml] rcept={rcept_no} 응답 크기: {len(blob)} bytes")

        if blob[:2] != b"PK":  # ZIP 시그니처(PK)가 아니면 = 에러 응답(XML)
            head = blob[:500].decode("utf-8", errors="replace")
            status_m = re.search(r"<status>(\d+)</status>", head)
            status_code = status_m.group(1) if status_m else "?"
            print(f"[document.xml] 원문 미생성/에러 (status={status_code}) - 재시도 필요")
            return "__NOT_READY__"

        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = sorted(zf.namelist(), key=lambda n: zf.getinfo(n).file_size, reverse=True)
                if not names:
                    return ""
                content = zf.read(names[0])
        except zipfile.BadZipFile:
            print(f"[document.xml] ZIP 파싱 실패 - 재시도 필요")
            return "__NOT_READY__"

        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return content.decode(enc)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[document.xml] 실패 rcept={rcept_no}: {e}")
        return ""


# ==========================================================
# 이하 함수들은 dart_mezzanine_auto.py 에서 동기화된 검증 로직
# ==========================================================
FUND_PREFIX_TO_MANAGER = {
    "스카이워크": "스카이워크자산운용",
    "아이트러스트": "아이트러스트자산운용",
    "제이씨에셋": "제이씨에셋자산운용",
    "모비딕": "모비딕자산운용",
    "프라임": "프라임자산운용",
    "인트러스": "인트러스자산운용",
    "엘엔에스": "엘엔에스자산운용",
    "레이크": "레이크자산운용",
    "나이스": "나이스자산운용",
    "비엔비": "비엔비자산운용",
    "웰컴": "웰컴자산운용",
    "리운": "리운자산운용",
    "이가": "이가자산운용",
    "다인": "다인자산운용",
    "NH헤지": "NH헤지자산운용",
    "IBK": "IBK투자증권",
    "HYUN": "자산운용현",
    "현스테디": "자산운용현",
    "마일스톤": "마일스톤자산운용",
    "인터레이스": "인터레이스자산운용",
    "디에스": "디에스자산운용",
    "라이온": "라이온자산운용",
    "라이프": "라이프자산운용",
    "알파": "알파자산운용",
    "아샘": "아샘자산운용",
    "셀레니언": "셀레니언자산운용",
    "보고펀드": "보고펀드자산운용",
    "한국투자밸류": "한국투자밸류자산운용",
    "에스피": "에스피자산운용",
    "씨스퀘어": "씨스퀘어자산운용",
    "타이거": "타이거자산운용투자일임",
    "안다": "안다자산운용",
    "라이언": "라이언자산운용",
    "브이엠": "브이엠자산운용",
    "갤럭시": "갤럭시자산운용",
    "새봄": "새봄자산운용",
    "오라이언": "오라이언자산운용",
    "수성": "수성자산운용",
    "오름": "오름자산운용",
    "클라우드": "클라우드아이비인베스트먼트",
    "파로스": "파로스자산운용",
    "트러스톤": "트러스톤자산운용",
}


def _cells_of_tr(tr):
    cells = []
    for c in tr.iter():
        if c.tag.lower() in ("td", "te", "th"):
            t = "".join(c.itertext()).strip()
            t = re.sub(r"\s+", " ", t)
            cells.append(t)
    return cells


def _rows_of(table):
    rows = []
    for tr in table.iter("tr"):
        cs = _cells_of_tr(tr)
        if cs:
            rows.append(cs)
    return rows


def parse_subscribers(xml: str):
    """본문 XML 에서 '발행 대상자명' 헤더 있는 테이블 추출."""
    if not xml:
        return []
    try:
        root = etree.fromstring(xml.encode("utf-8"), etree.HTMLParser(recover=True))
    except Exception:
        return []
    out = []
    for t in root.iter("table"):
        rows = _rows_of(t)
        if not rows:
            continue
        header = " ".join(rows[0])
        if "발행 대상자명" in header or "발행대상자명" in header:
            for r in rows[1:]:
                if len(r) >= 1 and r[0] and r[0] not in ("-", "", "합계"):
                    out.append({
                        "name": r[0],
                        "relation": r[1] if len(r) > 1 else "",
                        "amount": r[-2] if len(r) >= 5 else "",
                    })
    return out


def _manager_from_fund_name(fund_name: str) -> str:
    """펀드명 앞부분(접두어)으로 운용사명 추출. FUND_PREFIX_TO_MANAGER 참조."""
    fname = fund_name.strip()
    # 긴 접두어 우선 매칭 (dict 정의 순서대로)
    for prefix, manager in FUND_PREFIX_TO_MANAGER.items():
        if fname.startswith(prefix):
            return manager
    return ""


def parse_fund_managers(xml: str):
    """'본건 펀드' 테이블에서 집합투자업자(운용사)명 추출.
    구조 예: [펀드번호, 펀드명, 신탁업자, 집합투자업자]
    - 마지막 열에 운용사명 명시 → 직접 사용
    - 명시 없으면 펀드명 앞부분(접두어)에서 운용사명 추출 (fallback)
    """
    if not xml:
        return []
    try:
        root = etree.fromstring(xml.encode("utf-8"), etree.HTMLParser(recover=True))
    except Exception:
        return []
    managers = []

    # ── (A) "본건 펀드" 전용 테이블에서 집합투자업자 추출 ──────────────
    for t in root.iter("table"):
        rows = _rows_of(t)
        if not rows:
            continue
        if not any(r and r[0].startswith("본건 펀드") for r in rows):
            continue
        for r in rows:
            if not r or not r[0].startswith("본건 펀드"):
                continue
            # (1순위) 마지막 셀에 운용사 키워드 있으면 직접 사용
            found = ""
            for cell in reversed(r):
                if any(kw in cell for kw in ["자산운용", "투자일임", "투자자문", "인베스트먼트"]):
                    found = re.sub(r"\s+", " ", cell).strip()
                    break
            # (2순위) 펀드명 셀(index 1)에서 접두어 매칭
            if not found and len(r) >= 2:
                fund_name = r[1]
                found = _manager_from_fund_name(fund_name)
                if found:
                    log.debug(f"  펀드명 접두어 매칭: '{fund_name}' → {found}")
            if found and found not in managers:
                managers.append(found)

    if managers:
        return managers

    # ── (B) "본건 펀드" 테이블 없는 경우: 발행대상자 테이블 펀드명에서 추출 ──
    for t in root.iter("table"):
        rows = _rows_of(t)
        if not rows:
            continue
        header = " ".join(rows[0])
        if "발행 대상자명" not in header and "발행대상자명" not in header:
            continue
        for r in rows[1:]:
            if not r or not r[0]:
                continue
            name = r[0]
            # 펀드명(신탁/투자신탁 포함)에서 운용사 접두어 매칭
            if any(kw in name for kw in ["신탁", "펀드", "투자조합", "사모"]):
                found = _manager_from_fund_name(name)
                if found and found not in managers:
                    managers.append(found)
                    log.debug(f"  발행대상자 펀드명 매칭: '{name}' → {found}")

    return managers


# ============== Put/Call 스케줄 파싱 ==============
def _parse_date_any(s: str):
    m = re.search(r"(\d{4})[\.\-/](\d{1,2})[\.\-/](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return datetime.date(y, mo, d)
        except ValueError:
            return None
    return None


def _add_months(d: datetime.date, n: int) -> datetime.date:
    """date d에 n개월 추가 (월말 처리 포함)."""
    import calendar
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _months_between(a: datetime.date, b: datetime.date):
    months = (b.year - a.year) * 12 + (b.month - a.month)
    diff = b.day - a.day
    if diff < -15:
        months -= 1
    elif diff > 15:
        months += 1
    return max(months, 0)


def _duration_str(start: datetime.date, end: datetime.date) -> str:
    if not start or not end:
        return ""
    months = _months_between(start, end)
    y, m = divmod(months, 12)
    if y > 0 and m > 0:
        return f"{y}Y{m}M"
    if y > 0:
        return f"{y}Y"
    return f"{m}M"


def _find_schedule_table(root, keyword_sets):
    for t in root.iter("table"):
        rs = []
        for tr in t.iter("tr"):
            cs = _cells_of_tr(tr)
            if cs:
                rs.append(cs)
        if len(rs) < 3:
            continue
        head_text = " ".join(" ".join(r) for r in rs[:2])
        for kws in keyword_sets:
            if all(k in head_text for k in kws):
                return rs
    return None


def _schedule_dates(rs, use_min=False):
    """데이터 행(첫셀이 '1차' '1' 등)에서 날짜 추출.
    use_min=True : 시기(始期)/종기 구조 테이블 — 가장 이른 날짜(시기)를 취한다.
    use_min=False: 행사일/지급일 구조 테이블 — 가장 늦은 날짜(행사일)를 취한다."""
    dates = []
    for r in rs:
        if not r:
            continue
        first = r[0].strip()
        if not re.match(r"^\d+(차|회|호)?$|^\d+\s*$", first):
            continue
        row_dates = [_parse_date_any(c) for c in r]
        row_dates = [x for x in row_dates if x]
        if row_dates:
            dates.append(min(row_dates) if use_min else max(row_dates))
    return sorted(set(dates))


def extract_put_schedule(xml: str):
    if not xml:
        return None
    try:
        root = etree.fromstring(xml.encode("utf-8"), etree.HTMLParser(recover=True, encoding="utf-8"))
    except Exception:
        return None
    rs = _find_schedule_table(root, [
        {"조기상환", "조기상환율"},
        {"조기상환", "지급일"},
        {"조기상환청구", "지급일"},
        {"조기상환청구", "행사기간"},
        {"중도상환청구권", "행사기간"},   # 시기(始期)/종기 구조 테이블
        {"중도상환청구권", "시기"},
        {"풋옵션"},
        {"투자자조기상환"},
    ])
    if not rs:
        return None
    # 시기(始期)/종기 구조이면 min(시기), 일반 지급일 구조이면 max(행사일)
    head_text = " ".join(" ".join(r) for r in rs[:2])
    use_min = any(k in head_text for k in ["시기", "始期"])
    dates = _schedule_dates(rs, use_min=use_min)
    if not dates:
        return None
    return {
        "first": dates[0],
        "last": dates[-1],
        "interval_months": _months_between(dates[0], dates[1]) if len(dates) >= 2 else None,
    }


def extract_put_text(xml: str, pymd):
    """테이블 없이 텍스트로 기술된 Put 일정 파싱.
    패턴: '발행일로부터 N년이 되는 날 ... 매 M개월에 해당되는 날'
    예) 인산가: '발행일로부터 2년이 되는 날 및 그 이후 매 3개월에 해당되는 날'
    """
    if not xml or not pymd:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)

    # 조기상환청구권 섹션만 추출 (최대 1000자)
    m_sec = re.search(r"조기상환청구권.{0,1000}", text)
    if not m_sec:
        return None
    section = m_sec.group(0)

    # 발행일로부터 N년이 되는 날
    m_year = re.search(r"발행일로부터\s*(\d+)년이?\s*되는\s*날", section)
    if not m_year:
        return None
    start_years = int(m_year.group(1))

    # 매 M개월에 해당되는 날 (인터벌) — "개월 에" 공백 포함 대응
    m_iv = re.search(r"매\s*(\d+)개월\s*에?\s*해당되는\s*날", section)
    interval_months = int(m_iv.group(1)) if m_iv else None

    # 첫 Put일 = 납입일 + N년
    try:
        first = pymd.replace(year=pymd.year + start_years)
    except ValueError:
        first = pymd.replace(year=pymd.year + start_years, day=28)

    return {
        "first": first,
        "last": first,
        "interval_months": interval_months,
    }


def extract_call_text(xml: str, pymd):
    """테이블 없이 텍스트로 기술된 Call 일정 파싱.
    패턴1: '발행일로부터 N년이 경과한 날 ... 1회' (단발 Call)
    패턴2: '발행일로부터 N년에 해당하는 날부터 M년까지 매 K개월'
    패턴3: '발행일로부터 N년이 되는 날' (단발)
    """
    if not xml or not pymd:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)

    # 매도청구권 또는 콜옵션 섹션 탐색
    # 키워드 앞 1000자도 포함 (발행일로부터... 콜옵션 순서 공시 대응)
    m_kw = re.search(r"(?:매도청구권|콜옵션)", text)
    if not m_kw:
        return None
    sec_start = max(0, m_kw.start() - 1000)
    section = text[sec_start: m_kw.start() + 3000]
    # 인터벌 탐색용: 키워드 이후 텍스트만 (Put 섹션 오염 방지)
    section_post = text[m_kw.start(): m_kw.start() + 3000]

    # (-1) '발행일로 N년이 되는 날(DATE)부터 N년 M개월(DATE)이 되는 날까지' 형식 (이엔플러스 유형)
    # 예: 발행일로 1년이 되는 날(2027년 05월 28일)부터 1년 6개월(2027년 11월 28일)이 되는 날까지
    _ENP_PAT = (
        r"발행일로\s*(\d+)년이?\s*되는\s*날"
        r"(?:\([^)]+\))?"             # (DATE) 괄호 선택
        r"\s*부터"
        r".{0,400}?"
        r"(\d+)년\s*(\d+)개월"
        r"(?:\([^)]+\))?"             # (DATE) 괄호 선택
        r"\s*이?\s*되는\s*날\s*까지"
    )
    m_enp = re.search(_ENP_PAT, section_post, re.DOTALL)
    if m_enp:
        try:
            start_yrs = int(m_enp.group(1))
            end_yrs   = int(m_enp.group(2))
            end_mos   = int(m_enp.group(3))
            _s = _add_months(pymd, start_yrs * 12)
            _e = _add_months(pymd, end_yrs * 12 + end_mos)
            return {"first": _s, "last": _e, "interval_months": None}
        except (ValueError, TypeError):
            pass

    # (0) '익일인 YYYY년 MM월 DD일부터 ... 익일인 YYYY년 MM월 DD일까지' 형식 (빛과전자 유형)
    # 발행일로부터 N년이 되는 날의 익일인 DATE부터 ... N년M개월이 되는 날의 익일인 DATE까지
    _IKIL_PAT = (
        r"익일인\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})\s*일\s*부터"
        r".{0,500}?"
        r"익일인\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})\s*일\s*까지"
    )
    m_ikil = re.search(_IKIL_PAT, section_post, re.DOTALL)
    if m_ikil:
        try:
            first = datetime.date(
                int(m_ikil.group(1)), int(m_ikil.group(2)), int(m_ikil.group(3))
            )
            last = datetime.date(
                int(m_ikil.group(4)), int(m_ikil.group(5)), int(m_ikil.group(6))
            )
            return {"first": first, "last": last, "interval_months": None}
        except ValueError:
            pass

    # 시작 파싱 — section_post(키워드 이후) 우선, 없으면 section(pre-amble 포함) fallback
    # 한국어 숫자+아라비아 병기 유형 (예: 일(1)년, 일(1)년 육(6)개월) 도 지원
    _START_PAT = (
        r"발행일로부터\s*"
        r"(?:"
        r"[가-힣]*\((\d+)\)년|"   # 일(1)년, 이(2)년 … 형식
        r"(\d+)년이?"              # 기존 숫자만 표기
        r")"
        r"(?:\s*[가-힣]*\(\d+\)개월)?"  # 육(6)개월 같은 추가 개월 수 (start 계산에는 무시)
        r"\s*(?:이?되는|경과한|에\s*해당하는)\s*날?(?:의\s*익일)?"
    )
    m_start = re.search(_START_PAT, section_post) or re.search(_START_PAT, section)
    if not m_start:
        return None
    if m_start.group(1):            # 한국어+아라비아 병기 年 단위
        start_months = int(m_start.group(1)) * 12
    elif m_start.group(2):          # 기존 숫자만 표기 年 단위
        start_months = int(m_start.group(2)) * 12
    else:
        return None

    # 종료 파싱 — section_post 우선 탐색으로 Put 섹션 오염 방지
    end_months = start_months      # 단발 Call 기본값
    # (A) 'YYYY년 MM월 DD일[괄호]까지' 명시 날짜
    m_end_date = re.search(
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일(?:\([^)]*\))?\s*까지",
        section_post,
    )
    if m_end_date:
        try:
            end_date = datetime.date(
                int(m_end_date.group(1)),
                int(m_end_date.group(2)),
                int(m_end_date.group(3)),
            )
            end_months = _months_between(pymd, end_date)
        except ValueError:
            pass
    else:
        # (B) 'N년이 되는 날까지' 유형
        m_end = re.search(
            r"(\d+)년이?\s*(?:되는|에\s*해당하는)\s*날(?:[^까지]{0,40})?까지",
            section_post,
        )
        if m_end:
            end_months = int(m_end.group(1)) * 12
        else:
            # (C) '이후 N개월이 되는날까지' — start 기준 상대 종료 (제이에스링크 유형)
            m_rel = re.search(r"이후\s*(\d+)개월이?\s*되는\s*날", section_post)
            if m_rel:
                end_months = start_months + int(m_rel.group(1))

    # 인터벌 — '매월의 N일...마다'(=1M)를 먼저 체크해야 함 (머큐리 유형 우선)
    # Put 섹션 참조로 인한 '매 N개월에 해당되는 날' 오염 방지
    if re.search(r"매월[^。]{0,300}마다", section_post):
        interval_months = 1     # '매월의 N일... 마다' = 1개월 (머큐리 유형)
    else:
        m_iv = re.search(
            r"매\s*\[?(\d+)개월\]?\s*(?:이?\s*(?:되는|해당되는)|에?\s*해당(?:되는|하는)|마다)\s*(?:날)?",
            section_post,
        )
        interval_months = int(m_iv.group(1)) if m_iv else None

    # 날짜 계산 (개월 단위 가산)
    first = _add_months(pymd, start_months)
    last = _add_months(pymd, end_months)

    return {"first": first, "last": last, "interval_months": interval_months}


def detect_no_put(xml: str) -> bool:
    """본문 텍스트에서 Put(조기상환청구권/중도상환청구)이 없음을 명시한 경우 True.
    - "조기상환청구권 및 매도청구권 ... 해당사항 없습니다"
    - "사채권자는 어떠한 경우에도 ... 조기상환/중도상환 ... 요구할 수 없다"
    """
    if not xml:
        return False
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    if re.search(r"조기상환청구권.{0,80}(해당사항\s*없|해당\s*없|없습니다|없음)", text):
        return True
    if re.search(
        r"(사채권자|인수인).{0,40}(어떠한\s*경우에도|어떠한경우에도|어떠한\s*경우라도).{0,40}(조기상환|중도상환).{0,40}(요구할\s*수\s*없)",
        text,
    ):
        return True
    return False


def extract_call_schedule(xml: str):
    if not xml:
        return None
    try:
        root = etree.fromstring(xml.encode("utf-8"), etree.HTMLParser(recover=True))
    except Exception:
        return None
    rs = _find_schedule_table(root, [
        {"매도청구권", "매매대금"},
        {"매도청구권", "행사기간"},
        {"매매대금", "지급기일"},
        {"콜옵션"},
        {"매도청구", "지급기일"},
    ])
    if not rs:
        return None
    dates = _schedule_dates(rs)
    if not dates:
        return None
    return {
        "first": dates[0],
        "last": dates[-1],
        "interval_months": _months_between(dates[0], dates[1]) if len(dates) >= 2 else None,
    }


def extract_premium_rate(xml: str):
    """할증(할인)율 추출. 소수 반환 (0.15 = 15% 할증, -0.10 = 10% 할인).
    1) '기준주가의 N%(를) (최초) 전환/행사/교환가액' → (N - 100)/100
    2) 'N% 할증' → N/100
    3) 'N% 할인' → -N/100 (단, '할인발행' 제외)
    4) '전환가액 결정방법' 또는 '교환가액 결정방법' 섹션이 있으나 위 패턴 없음 → 0 (기준주가 이상, 할증 없음)
    """
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)

    # 결정방법 섹션 존재 여부
    has_section = bool(re.search(r"(전환|행사|교환)가액\s*결정방법", text))

    # (1) 기준주가의 N% → 전환/교환/행사가액
    m = re.search(
        r"기준주가의?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:를|에)?\s*(?:해당하는?\s*가액을?\s*)?(?:최초\s*)?(?:전환|행사|교환)\s*가액",
        text,
    )
    if m:
        pct = float(m.group(1))
        return round((pct - 100.0) / 100.0, 4)

    # (1b) '동 가격의 N%에 해당하는 가액' 형태
    m = re.search(
        r"동\s*가격의?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:에\s*해당하는)?\s*가액",
        text,
    )
    if m:
        pct = float(m.group(1))
        return round((pct - 100.0) / 100.0, 4)

    # (1c) '가장 높은 가액의 N%에 해당하는 가액' / '~ 가액의 N%에 해당하는 가액으로 하되' 형태
    #      (PS일렉트로닉스 EB 유형: 기준가 중 최고가의 120% → 할증 20%)
    m = re.search(
        r"(?:가장\s*높은\s*)?가액의?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*에?\s*해당하는\s*가액(?:으로\s*하되)?",
        text,
    )
    if m:
        pct = float(m.group(1))
        if pct != 100.0:  # 100%는 할증 없음
            return round((pct - 100.0) / 100.0, 4)

    # (2) 명시적 N% 할증
    m = re.search(r"\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:를)?\s*할증", text)
    if m:
        pct = float(m.group(1))
        return round(pct / 100.0, 4)

    # (3) 명시적 N% 할인 (단, '할인발행'은 제외)
    for m in re.finditer(r"\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:를)?\s*할인(\w*)", text):
        if "발행" not in m.group(2):
            pct = float(m.group(1))
            return round(-pct / 100.0, 4)

    # (4) 결정방법 섹션 있으나 N% 명시 없으면 0 (기준주가 default)
    if has_section:
        return 0.0
    return None


def extract_call_ratio(xml: str):
    """Call 대상 비율.
    패턴:
      - 'Call Option N%' / '콜옵션 N%'
      - '발행가액의 N% 초과/한도'
      - '전자등록총액의 N%를 초과하여 콜옵션' (태웅로직스 유형)
      - '전자등록금액의 전부 또는 일부' → 100%
      - '인수금액/권면금액의 N/100'
      - '발행가액의 N%를 총 한도로' (피엔티엠에스 유형)
    """
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)

    # 명시적 비율 패턴 우선 검색 (전부/일부보다 앞에 처리)
    # ※ \d+(?:\.\d+)? 로 소수점 비율(예: 24.62%) 도 매칭
    NUM = r"\d+(?:\.\d+)?"
    patterns = [
        rf"Call\s*Option\s*\[?({NUM})\]?\s*%",
        rf"콜옵션\s*\[?({NUM})\]?\s*%",
        rf"발행가액의?\s*\[?({NUM})\]?\s*%\s*를?\s*(?:초과|한도)",
        rf"발행가액\s*총액[^.{{}}]{{0,50}}?\[?({NUM})\]?\s*%",     # 발행가액 총액의 N%
        rf"주식\s*수량의?\s*\[?({NUM})\]?\s*%",                    # 주식 수량의 N%
        rf"\[?({NUM})\]?\s*%\s*의?\s*범위\s*내에서",               # N%의 범위 내에서
        rf"(?:전자등록총액|등록총액)의?\s*\[?({NUM})\]?\s*%\s*를?\s*초과하여\s*(?:콜옵션|Call)",
        rf"본\s*사채\s*원금\s*기준\s*\[?({NUM})\]?\s*%",           # 아이티센글로벌 유형
        rf"인수한[^\n]{{0,30}}?(?:권면)?금액의?\s*({NUM})\s*/\s*100",
        rf"본\s*사채\s*총\s*권면금액의?\s*({NUM})\s*/\s*100",
        rf"인수금액의?\s*\[?({NUM})\]?\s*%\s*를?\s*(?:한도|초과)",
        rf"원금(?:에\s*해당되는\s*금액)?의?\s*\[?({NUM})\]?\s*%\s*를?\s*초과하지\s*않는",  # 빛과전자 유형
        rf"사채\s*원금의?\s*\[?({NUM})\]?\s*%",                    # 이엔플러스 유형: 사채원금의 70%
        rf"대상채권.{{0,20}}사채\s*원금의?\s*\[?({NUM})\]?\s*%",   # 이엔플러스 유형: 대상채권의 사채원금의 N%
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            v = float(m.group(1))
            if 0 < v <= 100:
                return round(v / 100.0, 6)

    # 명시적 비율 없고 '전부 또는 일부' 문구가 매도청구권 맥락에 있으면 → Call 100%
    # 예) 전자등록금액의 전부 또는 일부, 매매목적물의 전부 또는 일부에 대하여 매도청구
    if re.search(
        r"(?:전자등록금액|전자등록총액|권면금액|매매목적물|본\s*사채)의?\s*전부\s*또는\s*일부"
        r"(?:에\s*대하여)?[^。.]{0,120}?(?:매도\s*청구권?|매도하여\s*줄\s*것을\s*청구|콜옵션)",
        text,
    ):
        return 1.0

    return None


def extract_ytc_text(xml: str):
    """매도청구권 섹션 내 YTC 명시 텍스트 파싱.
    패턴 우선순위:
      1) '연 복리 N% 수익률'
      2) 'N% 수익률' (이자율/지연/조기상환 문맥 제외)
      3) '매도청구권행사금액의 연 N%의 이율을 적용한 금액을 매매금액' (인산가 유형)
      4) 공식 표기 '(1+0.NN)^' 에서 직접 추출
    """
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m_call = re.search(r"(?:매도청구권|콜옵션|매도청구)", text)
    if not m_call:
        return None
    # YTC는 키워드 이후만 탐색 (이전 Put 섹션 오염 방지)
    section = text[m_call.start(): m_call.start() + 5000]

    # (1) 연 복리 N% 수익률
    m = re.search(r"연\s*복리?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:의?\s*)?수익(?:률|율)", section)
    if m:
        return float(m.group(1)) / 100.0

    # (1b) '매도청구수익률 연 복리 N%' / '연 복리 N%(이하 Call 수익률)' 유형 (엑스페릭스 유형)
    m = re.search(
        r"(?:매도청구수익률|Call\s*수익률)[^\d%]{0,30}연\s*복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%",
        section,
    )
    if not m:
        m = re.search(r"연\s*복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*\(이하", section)
    if m:
        return float(m.group(1)) / 100.0

    # (2) N% 수익률 (지연이율 등 제외)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*수익(?:률|율)", section)
    if m:
        around = section[max(0, m.start() - 30):m.end()]
        if not re.search(r"이자율|지연|조기상환", around):
            return float(m.group(1)) / 100.0

    # (3) '연 N%의 이율을 적용하여 계산한 금액' 유형 (인산가·아이씨디·인콘 등)
    #     이율 뒤 괄호 설명 허용: 이율(표면이자 2% 제외 후 순액 2% 지급)을 적용하여
    m = re.search(
        r"(?:행사금액의?\s*)?\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*이율(?:\([^)]*\))?\s*(?:을?\s*적용한\s*금액을?\s*매매금액|을?\s*적용하여\s*계산한\s*금액)",
        section,
    )
    if m:
        return float(m.group(1)) / 100.0

    # (4) '연 N%(M개월 단위 복리)' / '연 N%(분기단위 연복리)' 유형 (나무기술·지아이에스 유형)
    m = re.search(
        r"연\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*\([^)]*(?:\d+개월\s*단위\s*복리|분기단위\s*연복리)[^)]*\)",
        section,
    )
    if m:
        return float(m.group(1)) / 100.0

    # (4e) '복리 연 N%의 수익률이 보장' / '연 N%의 수익률 보장' (제이에스링크 유형)
    #      — 수익률 보장 명시 패턴이므로 (4d)보다 우선 처리
    m = re.search(
        r"복리\s*연\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*수익률",
        section,
    )
    if not m:
        m = re.search(
            r"연\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*수익률(?:이?\s*보장|을?\s*적용)",
            section,
        )
    if m:
        v = float(m.group(1))
        if v > 0:
            return v / 100.0

    # (4b) '연 단리 N%의 이율' 유형 (TS트릴리온 유형)
    m = re.search(r"연\s*단리\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*이율", section)
    if m:
        return float(m.group(1)) / 100.0

    # (4c) '연복리 N%의 이자율을 적용한 이자' 유형 (아이티센글로벌 유형)
    m = re.search(
        r"연복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*이자율을?\s*적용",
        section,
    )
    if m:
        return float(m.group(1)) / 100.0

    # (4d) 'N개월 단위 연복리 M%' / '분기 단위 연복리 M%' 유형 (블루산업개발·대성하이텍 유형)
    #      — 0%는 Put 수익률 오인 가능성 있어 제외
    m = re.search(
        r"(?:\d+개월|분기)\s*단위\s*연\s*복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%",
        section,
    )
    if m:
        v = float(m.group(1))
        if v > 0:
            return v / 100.0

    # (5) 공식 (1+0.NN)^ 형태에서 직접 추출
    m = re.search(r"\(1\s*\+\s*(0\.\d+)\)\s*\^", section)
    if m:
        v = float(m.group(1))
        if 0 < v < 1:
            return round(v, 4)

    # (6) '연 N%의 금리를 가산한 금액' 유형 (이엔플러스 유형)
    # 예: 사채권면액에 발행일로부터 매도(예정)일까지 연 3%의 금리를 가산한 금액
    m = re.search(r"연\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*금리를?\s*가산", section)
    if m:
        v = float(m.group(1))
        if v > 0:
            return v / 100.0

    # (7) '연 N%(M개월 단위 복리)의 이율을 적용한 금액' 유형 (율촌 유형)
    # 예: 연 0.1%(3개월 단위 복리)의 이율을 적용한 금액
    m = re.search(
        r"연\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*\(\s*\d+개월\s*단위\s*복리\s*\)의?\s*이율을?\s*적용",
        section,
    )
    if m:
        v = float(m.group(1))
        if v >= 0:
            return v / 100.0

    return None


def extract_ytc_reverse(xml: str, pymd):
    """매도청구권 스케줄 표 1차 '매매가액/매매대금 지급율/콜옵션 행사금액' 에서 역산.
    공식: YTC = (P/100)^(1/t) - 1, t=납입일~1차 지급일(년)."""
    if not xml or not pymd:
        return None
    try:
        root = etree.fromstring(xml.encode("utf-8"), etree.HTMLParser(recover=True))
    except Exception:
        return None
    rs = _find_schedule_table(root, [
        {"매도청구권", "매매대금"},
        {"매도청구권", "행사기간"},
        {"매매대금", "지급기일"},
        {"콜옵션"},
    ])
    if not rs:
        return None
    # 1차 데이터 행에서 마지막 % 셀 추출 + 행의 가장 늦은 날짜
    for r in rs:
        if not r or not r[0].strip():
            continue
        first_cell = r[0].strip()
        if not re.match(r"^\d+(차|회|호)?$|^\d+\s*$", first_cell):
            continue
        # 가장 늦은 날짜 = 1차 지급일
        row_dates = [_parse_date_any(c) for c in r]
        row_dates = [x for x in row_dates if x]
        if not row_dates:
            continue
        pay_date = max(row_dates)
        # 마지막 % 셀
        pct = None
        for c in reversed(r):
            m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$", c)
            if m:
                pct = float(m.group(1))
                break
        if pct is None:
            continue
        # 역산
        t_days = (pay_date - pymd).days
        if t_days <= 0:
            continue
        t_years = t_days / 365.25
        try:
            ytc = (pct / 100.0) ** (1.0 / t_years) - 1.0
        except (ValueError, ZeroDivisionError):
            continue
        if ytc <= 0.0 or ytc >= 1.0:  # 비현실적 값 거르기 (0.0 = 100% 테이블 역산 오류)
            continue
        # 소수점 첫째자리 반올림 (소수로 저장 - 예: 0.010 = 1.0%)
        return round(ytc, 3)  # 0.020 = 2.0% 수준 정확도
    return None


def extract_ytc(xml: str, pymd=None):
    """우선순위: (1) 매도청구권 섹션 내 '연 복리 X% 수익률' 텍스트  (2) 매매가액 표 역산."""
    v = extract_ytc_text(xml)
    if v is not None:
        return v
    return extract_ytc_reverse(xml, pymd)


def format_put(sched, pymd):
    if not sched or not pymd:
        return ""
    fd = _duration_str(pymd, sched["first"])
    iv = f"({sched['interval_months']}M)" if sched.get("interval_months") else ""
    return f"{fd}{iv}"


def format_call(sched, pymd):
    if not sched or not pymd:
        return ""
    fd = _duration_str(pymd, sched["first"])
    ld = _duration_str(pymd, sched["last"])
    iv = f"({sched['interval_months']}M)" if sched.get("interval_months") else ""
    if fd == ld:
        return f"{fd}{iv}"
    return f"{fd}~{ld}{iv}"



# ==========================================================
# 봇 전용 추가 함수 (스케줄 스크립트엔 없는 항목)
# ==========================================================
def summarize_underwriters(subs, managers):
    """인수인 요약: 운용사 우선, 신탁사 제외, 최대 5개 + 외 N곳."""
    if not subs and not managers:
        return "-"
    trustee_pattern = re.compile(
        r"(삼성증권|미래에셋증권|엔에이치투자증권|NH투자증권|케이비증권|KB증권|"
        r"신한투자증권|한국투자증권|유진투자증권|DB증권|BNK투자증권|아이엠증권|"
        r"하나증권|메리츠증권|한국증권금융)"
    )

    def _clean_name(n):
        n = re.sub(r"\(.*?\)", "", n)
        n = re.sub(r"주식회사", "", n)
        n = re.sub(r"㈜", "", n)
        n = re.sub(r"\(주\)", "", n)
        return re.sub(r"\s+", " ", n).strip()

    names = []
    if managers:
        for m in managers:
            c = _clean_name(m)
            if c and c not in names:
                names.append(c)
    for s in subs or []:
        name = s["name"]
        is_trustee = trustee_pattern.search(name) and ("신탁업자" in name or "펀드" in name)
        if is_trustee:
            continue
        c = _clean_name(name)
        if c and c not in names:
            names.append(c)

    if not names:
        return "-"
    if len(names) > 5:
        return ", ".join(names[:5]) + f" 외 {len(names)-5}곳"
    return ", ".join(names)


def extract_capital_ratio(xml):
    """주식총수 대비 비율(%) 추출. 소수 반환."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"주식총수\s*대비\s*비율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)", text)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except ValueError:
            pass
    return None


def extract_refixing(xml, base_price):
    """Refixing 한도: (최저 조정가액 / base_price) 소수 반환."""
    if not xml or not base_price:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"최저\s*조정\s*가액\s*\(?\s*원?\s*\)?\s*([0-9,]+|\-)", text)
    if not m:
        return None
    raw = m.group(1).strip().replace(",", "")
    if raw == "-" or not raw.isdigit():
        return None
    try:
        min_price = int(raw)
    except ValueError:
        return None
    if min_price <= 0 or base_price <= 0:
        return None
    return min_price / base_price


def extract_exchange_target(xml):
    """교환사채 교환대상주식."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    if re.search(r"자기주식.*?교환", text) or re.search(r"교환[^.]*?자기주식", text):
        return "자기주식"
    patterns = [
        r"교환대상\s*주식의?\s*종류\s*[:：]?\s*([가-힣A-Za-z0-9㈜().\s]+?(?:보통주|우선주))",
        r"교환대상\s*[:：]\s*([가-힣A-Za-z0-9㈜().\s]+?(?:보통주|우선주))",
        r"교환의?\s*대상(?:이\s*되는)?\s*주식\s*[:：]?\s*([가-힣A-Za-z0-9㈜().\s]+?(?:보통주|우선주))",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = re.sub(r"\s+", " ", m.group(1).strip())
            raw = raw.replace("㈜", "").replace("주식회사", "").strip()
            if len(raw) > 50:
                raw = raw[:50] + "..."
            return raw if raw else None
    return None


def extract_dividend_rate(xml):
    """우선배당률 + 참가/누적 속성."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    rate = None
    for pat in [
        r"우선배당률\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"우선배당율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
    ]:
        m = re.search(pat, text)
        if m:
            try:
                rate = float(m.group(1))
                if rate > 0:
                    break
            except ValueError:
                continue
    if rate is None or rate == 0:
        return None
    attrs = []
    if re.search(r"(?<!비)참가적", text):
        attrs.append("참가적")
    elif "비참가적" in text:
        attrs.append("비참가적")
    if re.search(r"(?<!비)누적적", text):
        attrs.append("누적적")
    elif "비누적적" in text:
        attrs.append("비누적적")
    if attrs:
        return f"{rate:.1f}%({', '.join(attrs)})"
    return f"{rate:.1f}%"


def extract_redemption_rate(xml):
    """RCPS/RPS 상환이율. 소수 반환."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    for pat in [
        r"상환이자율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"상환수익률\s*(?:연\s*복리\s*)?([0-9]+(?:\.[0-9]+)?)\s*%",
        r"조기상환수익률\s*(?:연\s*복리\s*)?([0-9]+(?:\.[0-9]+)?)\s*%",
    ]:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1))
                if val > 0:
                    return val / 100.0
            except ValueError:
                continue
    return None


def extract_discount_rate(xml):
    """공모 유상증자 할인율. 소수 반환."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    for pat in [
        r"할인율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"할인율\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    ]:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1))
                if val > 0:
                    return val / 100.0
            except ValueError:
                continue
    return None


def extract_lead_managers(xml):
    """공모 유상증자 대표주관회사."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    next_keywords = (
        r"(?:인수인|모집주선|공동주관|일반공모|청약\s*개시|"
        r"\d+\.\s|\d+\)\s|증자방식|신주의\s*종류|발행\s*가액|"
        r"모집매출\s*방법|기타|【|《|■)"
    )
    patterns = [
        rf"대표주관회사\s*(?:\(공동\)|공동)?\s*[:：]?\s*([^\n]{{1,200}}?)(?=\s*{next_keywords})",
        rf"대표주관회사\s+([가-힣A-Za-z㈜()0-9,\s\.]{{2,200}}?)(?={next_keywords})",
    ]
    raw_text = None
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw_text = m.group(1).strip()
            if raw_text and raw_text != "-":
                break
    if not raw_text or raw_text == "-":
        return None
    securities_pattern = r"([가-힣A-Za-z]+(?:투자)?증권)(?:\s*(?:주식회사|㈜|\(주\)))?"
    matches = re.findall(securities_pattern, raw_text)
    if not matches:
        return None
    seen = set()
    unique = []
    for name in matches:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return ", ".join(unique)


# ============== 공모 유상증자 분류 (dart_scan.py 로직 이식) ==============
def check_offering_type(xml):
    """
    증자방식 판정: '공모' | '제3자배정' | '불명'
    '5. 증자방식' 섹션 근처 텍스트로 판단.
    """
    if not xml:
        return "불명"
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)

    # 증자방식 섹션 근처 300자
    for kw in ["증자방식", "증자 방식"]:
        idx = text.find(kw)
        if idx != -1:
            snippet = text[idx: idx + 300]
            if "제3자배정" in snippet or "제 3 자" in snippet:
                return "제3자배정"
            if any(k in snippet for k in ["주주배정", "일반공모", "소액공모", "공모"]):
                return "공모"

    # 전체 앞부분 재확인
    head = text[:3000]
    if "제3자배정" in head:
        return "제3자배정"
    if any(k in head for k in ["주주배정후 실권주", "주주배정 후 실권주", "일반공모 방식", "소액공모"]):
        return "공모"

    return "불명"


def parse_offering_method(xml):
    """증자방식 정규화 문구 추출 (예: '주주배정후 실권주 일반공모')."""
    if not xml:
        return ""
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)

    if "주주배정후 실권주 일반공모" in text or "주주배정 후 실권주 일반공모" in text:
        return "주주배정후 실권주 일반공모"
    head = text[:1000]
    if "일반공모" in head:
        return "일반공모"
    if "주주배정" in head:
        return "주주배정"
    if "소액공모" in head:
        return "소액공모"
    return ""


# ============== 우선주 (CPS/RCPS) 판별/파싱 (dart_cps_rcps_auto.py 로직 이식) ==============
def detect_preferred_type(xml):
    """
    본문에서 우선주 유형 판별: 'CPS' | 'RCPS' | None
    - 기타주식 수량 없으면 보통주(None)
    - 상환조건 → RCPS, 전환만 → CPS
    """
    if not xml:
        return None

    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)

    # Step 1: 기타주식 수량 확인
    other_shares = None
    try:
        root = etree.fromstring(xml.encode("utf-8"), etree.HTMLParser(recover=True))
    except Exception:
        root = None

    if root is not None:
        for table in root.iter("table"):
            rows = _rows_of(table)
            for row in rows:
                joined = " ".join(row)
                if "기타주식" in joined and ("(주)" in joined or "주식수" in joined.lower()):
                    for cell in row:
                        val = re.sub(r"[,\s]", "", cell)
                        if re.match(r"^\d+$", val) and int(val) > 0:
                            other_shares = int(val)
                            break
                    break
            if other_shares is not None:
                break

    if other_shares is None:
        m = re.search(r"기타주식\s*\(주\)\s*([0-9,]+|-)", text)
        if m:
            val = m.group(1).replace(",", "").strip()
            if val in ("-", ""):
                return None
            try:
                other_shares = int(val)
            except ValueError:
                pass

    if other_shares is None or other_shares == 0:
        return None

    # Step 2: 상환/전환 조건 판별
    if re.search(r"상환전환우선주|RCPS", text, re.IGNORECASE):
        return "RCPS"
    if re.search(r"전환우선주|CPS(?!\s*발행)", text, re.IGNORECASE):
        return "CPS"

    has_redeem = bool(re.search(r"상환[^한]", text))
    has_convert = bool(re.search(r"전환(?!사채|청구|비율)", text))

    if has_redeem and has_convert:
        return "RCPS"
    if has_convert and not has_redeem:
        return "CPS"
    if has_redeem and not has_convert:
        return "RCPS"
    return None


def extract_pref_dividend(xml):
    """우선배당 추출 (배당률 + 참가/누적 조건). dart_cps_rcps 패턴 개선."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    # 배당률 숫자 추출
    m = re.search(r"(?:우선배당률|우선배당율|배당률|배당비율)\s*[:：]?\s*(?:연\s*)?([\d.]+)\s*%", text)
    if not m:
        return None
    rate = m.group(1)
    # 참가/누적 조건 (배당률 근처 200자 내에서만 탐색)
    around = text[max(0, m.start()-50): m.end()+200]
    attrs = []
    if re.search(r"(?<!비)참가적", around):
        attrs.append("참가적")
    elif "비참가적" in around:
        attrs.append("비참가적")
    if re.search(r"(?<!비)누적적", around):
        attrs.append("누적적")
    elif "비누적적" in around:
        attrs.append("비누적적")
    if attrs:
        return f"{rate}%({', '.join(attrs)})"
    return f"{rate}%"


def extract_pref_redemption_rate(xml):
    """상환이율 추출 (상환 이율/금리/수익률). dart_cps_rcps 패턴."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m = re.search(
        r"상환\s*(?:이율|금리|수익률)[^\n]{0,80}?(\d+(?:\.\d+)?)\s*%",
        text,
    )
    if m:
        try:
            return float(m.group(1)) / 100.0
        except ValueError:
            pass
    return None


def extract_pref_refixing(xml):
    """시가리픽싱 추출 (전환가액 조정 매 N개월 + 하한 N%). dart_cps_rcps 패턴."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"전환가액\s*조정[^\n]{0,200}", text)
    if not m:
        return None
    snippet = m.group(0)
    interval_m = re.search(r"매\s*(\d+)\s*개월", snippet)
    floor_m = re.search(r"하한\s*(\d+)\s*%", snippet)
    parts = []
    if interval_m:
        parts.append(f"매 {interval_m.group(1)}개월")
    if floor_m:
        parts.append(f"하한 {floor_m.group(1)}%")
    if parts:
        return ", ".join(parts)
    return None


def extract_pref_duration(xml):
    """존속기간 추출 (발행일로부터 N년). dart_cps_rcps 패턴."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"발행일로부터\s*(\d+)\s*년", text)
    if m:
        return f"발행일로부터 {m.group(1)}년"
    return None


# ==========================================================
# 통합 함수
# ==========================================================
def parse_disclosure_details(dart_key, rcept_no, pymd_str=None, base_price=None):
    """공시 본문에서 모든 정보 추출 (document.xml 사용)."""
    result = {
        "capital_ratio": "-", "put_option": "-", "call_option": "-",
        "call_ratio": "-", "ytc": "-", "refixing": "-", "underwriters": "-",
        "discount_rate": "-", "lead_managers": "-", "dividend_rate": "-",
        "redemption_rate": "-", "exchange_target": "-", "premium_rate": "-",
        "offering_type": "불명", "offering_method": "",
        "_not_ready": False,
    }

    xml = fetch_document_xml(dart_key, rcept_no)
    if xml == "__NOT_READY__":
        result["_not_ready"] = True
        return result
    if not xml:
        return result

    pymd = _parse_date_kr(pymd_str) if pymd_str else None

    # 주식총수 대비 비율
    try:
        v = extract_capital_ratio(xml)
        if v is not None:
            result["capital_ratio"] = f"{v*100:.2f}%"
    except Exception as e:
        print(f"capital_ratio 실패: {e}")

    # Put Option
    try:
        if detect_no_put(xml):
            result["put_option"] = "없음"
        else:
            put = extract_put_schedule(xml)
            if not put and pymd:
                put = extract_put_text(xml, pymd)
            if put and pymd:
                result["put_option"] = f"발행일로부터 {format_put(put, pymd)} 후"
    except Exception as e:
        print(f"put_option 실패: {e}")

    # Call Option
    try:
        call = extract_call_schedule(xml)
        if not call and pymd:
            call = extract_call_text(xml, pymd)
        if call and pymd:
            result["call_option"] = f"발행일로부터 {format_call(call, pymd)}"
    except Exception as e:
        print(f"call_option 실패: {e}")

    # Call 비율
    try:
        v = extract_call_ratio(xml)
        if v is not None:
            result["call_ratio"] = f"{v*100:.1f}%"
    except Exception as e:
        print(f"call_ratio 실패: {e}")

    # YTC
    try:
        v = extract_ytc(xml, pymd)
        if v is not None:
            result["ytc"] = f"{v*100:.1f}%"
    except Exception as e:
        print(f"ytc 실패: {e}")

    # Refixing
    try:
        v = extract_refixing(xml, base_price)
        if v is not None:
            result["refixing"] = f"{v*100:.0f}%"
        else:
            # 2차 fallback: 우선주 시가리픽싱 패턴 (매 N개월, 하한 N%)
            v2 = extract_pref_refixing(xml)
            if v2:
                result["refixing"] = v2
    except Exception as e:
        print(f"refixing 실패: {e}")

    # 인수인
    try:
        subs = parse_subscribers(xml)
        managers = parse_fund_managers(xml)
        result["underwriters"] = summarize_underwriters(subs, managers)
    except Exception as e:
        print(f"underwriters 실패: {e}")

    # 할증률
    try:
        v = extract_premium_rate(xml)
        if v is not None and v != 0:
            result["premium_rate"] = f"{v*100:.1f}%"
        elif v == 0.0:
            result["premium_rate"] = "0%"
    except Exception as e:
        print(f"premium_rate 실패: {e}")

    # 교환대상주식
    try:
        v = extract_exchange_target(xml)
        if v:
            result["exchange_target"] = v
    except Exception as e:
        print(f"exchange_target 실패: {e}")

    # 우선배당률 (1차: 기본 패턴)
    try:
        v = extract_dividend_rate(xml)
        if v:
            result["dividend_rate"] = v
        else:
            # 2차 fallback: dart_cps_rcps 패턴
            v2 = extract_pref_dividend(xml)
            if v2:
                result["dividend_rate"] = v2
    except Exception as e:
        print(f"dividend_rate 실패: {e}")

    # 상환이율 (1차: 기본 패턴)
    try:
        v = extract_redemption_rate(xml)
        if v is not None:
            result["redemption_rate"] = f"{v*100:.1f}%"
        else:
            # 2차 fallback: dart_cps_rcps 패턴
            v2 = extract_pref_redemption_rate(xml)
            if v2 is not None:
                result["redemption_rate"] = f"{v2*100:.1f}%"
    except Exception as e:
        print(f"redemption_rate 실패: {e}")

    # 공모 할인율
    try:
        v = extract_discount_rate(xml)
        if v is not None:
            result["discount_rate"] = f"{v*100:.1f}%"
    except Exception as e:
        print(f"discount_rate 실패: {e}")

    # 공모 대표주관회사
    try:
        v = extract_lead_managers(xml)
        if v:
            result["lead_managers"] = v
    except Exception as e:
        print(f"lead_managers 실패: {e}")

    # 공모 유상증자 분류 (공모/제3자배정/불명) + 증자방식 정규화
    try:
        result["offering_type"] = check_offering_type(xml)
        m = parse_offering_method(xml)
        if m:
            result["offering_method"] = m
    except Exception as e:
        print(f"offering_type 실패: {e}")

    return result
