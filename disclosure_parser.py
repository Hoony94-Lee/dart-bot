"""
DART 공시 본문 파서 (메자닌 발행내역 자동 정리 스크립트 기반)
- document.xml API 사용 (HTML viewer 대비 본문이 완전함)
- 검증된 테이블 파싱 + 텍스트 fallback 로직
"""
import re
import io
import zipfile
import requests
import datetime
import calendar
from lxml import etree

DART_API_BASE = "https://opendart.fss.or.kr/api"


# ============== 펀드명 → 운용사 매핑 ==============
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


# ============== 본문 조회 (document.xml) ==============
def fetch_document_xml(dart_key, rcept_no):
    """DART document.xml API 호출. ZIP 안에서 가장 큰 XML 추출."""
    try:
        r = requests.get(
            f"{DART_API_BASE}/document.xml",
            params={"crtfc_key": dart_key, "rcept_no": rcept_no},
            timeout=60,
        )
        r.raise_for_status()
        blob = r.content
        print(f"[document.xml] rcept={rcept_no} 응답 크기: {len(blob)} bytes")
        
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = sorted(zf.namelist(), key=lambda n: zf.getinfo(n).file_size, reverse=True)
                if not names:
                    print(f"[document.xml] ZIP 안 비어있음")
                    return ""
                content = zf.read(names[0])
                print(f"[document.xml] ZIP 내 가장 큰 파일: {names[0]} ({len(content)} bytes)")
        except zipfile.BadZipFile:
            print(f"[document.xml] ZIP 아님 - 본문 그대로 사용 (응답 본문 일부: {blob[:200]})")
            content = blob
        
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                decoded = content.decode(enc)
                print(f"[document.xml] {enc} 디코딩 성공 (길이: {len(decoded)})")
                return decoded
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[document.xml] 실패 rcept={rcept_no}: {e}")
        return ""


# ============== 유틸리티 ==============
def _parse_date_any(s):
    m = re.search(r"(\d{4})[\.\-/](\d{1,2})[\.\-/](\d{1,2})", s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _parse_date_kr(s):
    if not s or s == "-":
        return None
    m = re.match(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(s))
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _add_months(d, n):
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _months_between(a, b):
    months = (b.year - a.year) * 12 + (b.month - a.month)
    diff = b.day - a.day
    if diff < -15:
        months -= 1
    elif diff > 15:
        months += 1
    return max(months, 0)


def _duration_str(start, end):
    if not start or not end:
        return ""
    months = _months_between(start, end)
    y, m = divmod(months, 12)
    if y > 0 and m > 0:
        return f"{y}년 {m}개월"
    if y > 0:
        return f"{y}년"
    return f"{m}개월"


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


# ============== 투자자 파싱 ==============
def parse_subscribers(xml):
    """'발행 대상자명' 헤더 있는 테이블 추출."""
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
                    })
    return out


def _manager_from_fund_name(fund_name):
    fname = fund_name.strip()
    for prefix, manager in FUND_PREFIX_TO_MANAGER.items():
        if fname.startswith(prefix):
            return manager
    return ""


def parse_fund_managers(xml):
    """'본건 펀드' 테이블에서 집합투자업자(운용사)명 추출."""
    if not xml:
        return []
    try:
        root = etree.fromstring(xml.encode("utf-8"), etree.HTMLParser(recover=True))
    except Exception:
        return []
    managers = []
    
    # (A) '본건 펀드' 전용 테이블
    for t in root.iter("table"):
        rows = _rows_of(t)
        if not rows:
            continue
        if not any(r and r[0].startswith("본건 펀드") for r in rows):
            continue
        for r in rows:
            if not r or not r[0].startswith("본건 펀드"):
                continue
            found = ""
            for cell in reversed(r):
                if any(kw in cell for kw in ["자산운용", "투자일임", "투자자문", "인베스트먼트"]):
                    found = re.sub(r"\s+", " ", cell).strip()
                    break
            if not found and len(r) >= 2:
                fund_name = r[1]
                found = _manager_from_fund_name(fund_name)
            if found and found not in managers:
                managers.append(found)
    
    if managers:
        return managers
    
    # (B) 발행대상자 테이블 펀드명에서 추출
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
            if any(kw in name for kw in ["신탁", "펀드", "투자조합", "사모"]):
                found = _manager_from_fund_name(name)
                if found and found not in managers:
                    managers.append(found)
    
    return managers


def summarize_underwriters(subs, managers):
    """긴 리스트를 대표 운용사/법인으로 요약."""
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
            m_clean = _clean_name(m)
            if m_clean and m_clean not in names:
                names.append(m_clean)
    
    for s in subs or []:
        name = s["name"]
        is_trustee = trustee_pattern.search(name) and ("신탁업자" in name or "펀드" in name)
        if is_trustee:
            continue
        clean = _clean_name(name)
        if clean and clean not in names:
            names.append(clean)
    
    if not names:
        return "-"
    
    # 최대 5개까지만 표시 (텔레그램 메시지 길이 제한 고려)
    if len(names) > 5:
        return ", ".join(names[:5]) + f" 외 {len(names)-5}곳"
    return ", ".join(names)


# ============== Put/Call 파싱 ==============
def extract_put_schedule(xml):
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
        {"중도상환청구권", "행사기간"},
        {"중도상환청구권", "시기"},
        {"풋옵션"},
        {"투자자조기상환"},
    ])
    if not rs:
        return None
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


def extract_put_text(xml, pymd):
    """텍스트 기반 Put 일정 파싱 (테이블 실패 시 fallback)"""
    if not xml or not pymd:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m_sec = re.search(r"조기상환청구권.{0,1000}", text)
    if not m_sec:
        return None
    section = m_sec.group(0)
    m_year = re.search(r"발행일로부터\s*(\d+)년이?\s*되는\s*날", section)
    if not m_year:
        # "발행일로부터 N년 M개월" 패턴
        m_ym = re.search(r"발행일로부터\s*(\d+)년\s*(\d+)개월", section)
        if m_ym:
            years = int(m_ym.group(1))
            months = int(m_ym.group(2))
            first = _add_months(pymd, years * 12 + months)
            m_iv = re.search(r"매\s*(\d+)개월", section)
            return {
                "first": first,
                "last": first,
                "interval_months": int(m_iv.group(1)) if m_iv else None,
            }
        # "발행일로부터 N개월" 패턴
        m_m = re.search(r"발행일로부터\s*(\d+)개월", section)
        if m_m:
            months = int(m_m.group(1))
            first = _add_months(pymd, months)
            m_iv = re.search(r"매\s*(\d+)개월", section)
            return {
                "first": first,
                "last": first,
                "interval_months": int(m_iv.group(1)) if m_iv else None,
            }
        return None
    start_years = int(m_year.group(1))
    m_iv = re.search(r"매\s*(\d+)개월\s*에?\s*해당되는\s*날", section)
    interval_months = int(m_iv.group(1)) if m_iv else None
    try:
        first = pymd.replace(year=pymd.year + start_years)
    except ValueError:
        first = pymd.replace(year=pymd.year + start_years, day=28)
    return {"first": first, "last": first, "interval_months": interval_months}


def detect_no_put(xml):
    if not xml:
        return False
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    if re.search(r"조기상환청구권.{0,80}(해당사항\s*없|해당\s*없|없습니다|없음)", text):
        return True
    if re.search(
        r"(사채권자|인수인).{0,40}(어떠한\s*경우에도|어떠한경우에도).{0,40}(조기상환|중도상환).{0,40}(요구할\s*수\s*없)",
        text,
    ):
        return True
    return False


def extract_call_schedule(xml):
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


def extract_call_text(xml, pymd):
    if not xml or not pymd:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m_kw = re.search(r"(?:매도청구권|콜옵션)", text)
    if not m_kw:
        return None
    sec_start = max(0, m_kw.start() - 1000)
    section = text[sec_start: m_kw.start() + 3000]
    section_post = text[m_kw.start(): m_kw.start() + 3000]
    
    _START_PAT = (
        r"발행일로부터?\s*"
        r"(?:"
        r"[가-힣]*\((\d+)\)년|"
        r"(\d+)년이?"
        r")"
        r"(?:\s*[가-힣]*\(\d+\)개월)?"
        r"\s*(?:이?되는|경과한|에\s*해당하는)\s*날?(?:의\s*익일)?"
    )
    m_start = re.search(_START_PAT, section_post) or re.search(_START_PAT, section)
    if not m_start:
        # "발행일로 N년" 패턴 (이엔플러스 유형)
        m_start = re.search(r"발행일로\s*(\d+)년이?\s*되는\s*날", section_post)
        if m_start:
            start_months = int(m_start.group(1)) * 12
        else:
            return None
    else:
        if m_start.group(1):
            start_months = int(m_start.group(1)) * 12
        elif m_start.group(2):
            start_months = int(m_start.group(2)) * 12
        else:
            return None
    
    end_months = start_months
    # 종료 파싱
    m_end = re.search(r"(\d+)년이?\s*(?:되는|에\s*해당하는)\s*날(?:[^까지]{0,40})?까지", section_post)
    if m_end:
        end_months = int(m_end.group(1)) * 12
    else:
        m_end_ym = re.search(r"(\d+)년\s*(\d+)개월(?:이?\s*되는)?\s*날?(?:[^까지]{0,40})?까지", section_post)
        if m_end_ym:
            end_months = int(m_end_ym.group(1)) * 12 + int(m_end_ym.group(2))
        else:
            m_rel = re.search(r"이후\s*(\d+)개월이?\s*되는\s*날", section_post)
            if m_rel:
                end_months = start_months + int(m_rel.group(1))
    
    # 인터벌
    if re.search(r"매월[^。]{0,300}마다", section_post):
        interval_months = 1
    else:
        m_iv = re.search(r"매\s*\[?(\d+)개월\]?\s*(?:이?\s*(?:되는|해당되는)|에?\s*해당(?:되는|하는)|마다)\s*(?:날)?", section_post)
        interval_months = int(m_iv.group(1)) if m_iv else None
    
    first = _add_months(pymd, start_months)
    last = _add_months(pymd, end_months)
    return {"first": first, "last": last, "interval_months": interval_months}


# ============== Call 비율 ==============
def extract_call_ratio(xml):
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    
    NUM = r"\d+(?:\.\d+)?"
    patterns = [
        rf"Call\s*Option\s*\[?({NUM})\]?\s*%",
        rf"콜옵션\s*\[?({NUM})\]?\s*%",
        rf"발행가액의?\s*\[?({NUM})\]?\s*%\s*를?\s*(?:초과|한도)",
        rf"발행가액\s*총액[^.{{}}]{{0,50}}?\[?({NUM})\]?\s*%",
        rf"주식\s*수량의?\s*\[?({NUM})\]?\s*%",
        rf"\[?({NUM})\]?\s*%\s*의?\s*범위\s*내에서",
        rf"(?:전자등록총액|등록총액)의?\s*\[?({NUM})\]?\s*%\s*를?\s*초과하여\s*(?:콜옵션|Call)",
        rf"본\s*사채\s*원금\s*기준\s*\[?({NUM})\]?\s*%",
        rf"인수한[^\n]{{0,30}}?(?:권면)?금액의?\s*({NUM})\s*/\s*100",
        rf"본\s*사채\s*총\s*권면금액의?\s*({NUM})\s*/\s*100",
        rf"인수금액의?\s*\[?({NUM})\]?\s*%\s*를?\s*(?:한도|초과)",
        rf"원금(?:에\s*해당되는\s*금액)?의?\s*\[?({NUM})\]?\s*%\s*를?\s*초과하지\s*않는",
        rf"대상채권의?\s*\[?({NUM})\]?\s*%\s*\[",
        rf"사채원금의?\s*\[?({NUM})\]?\s*%",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            v = float(m.group(1))
            if 0 < v <= 100:
                return v / 100.0
    
    # '전부 또는 일부' → Call 100%
    if re.search(
        r"(?:전자등록금액|전자등록총액|권면금액|매매목적물|본\s*사채)의?\s*전부\s*또는\s*일부"
        r"(?:에\s*대하여)?[^。.]{0,120}?(?:매도\s*청구권?|매도하여\s*줄\s*것을\s*청구|콜옵션)",
        text,
    ):
        return 1.0
    
    return None


# ============== YTC ==============
def extract_ytc_text(xml):
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    m_call = re.search(r"(?:매도청구권|콜옵션|매도청구)", text)
    if not m_call:
        return None
    section = text[m_call.start(): m_call.start() + 5000]
    
    # (1) 연 복리 N% 수익률
    m = re.search(r"연\s*복리?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:의?\s*)?수익(?:률|율)", section)
    if m:
        return float(m.group(1)) / 100.0
    
    # (1b) 매도청구수익률
    m = re.search(r"(?:매도청구수익률|Call\s*수익률)[^\d%]{0,30}연\s*복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%", section)
    if not m:
        m = re.search(r"연\s*복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*\(이하", section)
    if m:
        return float(m.group(1)) / 100.0
    
    # (2) N% 수익률
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*수익(?:률|율)", section)
    if m:
        around = section[max(0, m.start() - 30):m.end()]
        if not re.search(r"이자율|지연|조기상환", around):
            return float(m.group(1)) / 100.0
    
    # (3) N%의 이율
    m = re.search(
        r"(?:행사금액의?\s*)?\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*이율(?:\([^)]*\))?\s*(?:을?\s*적용한\s*금액을?\s*매매금액|을?\s*적용하여\s*계산한\s*금액)",
        section,
    )
    if m:
        return float(m.group(1)) / 100.0
    
    # (4) 연 N%(M개월 단위 복리)
    m = re.search(r"연\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*\([^)]*(?:\d+개월\s*단위\s*복리|분기단위\s*연복리)[^)]*\)", section)
    if m:
        return float(m.group(1)) / 100.0
    
    # (4e) 복리 연 N%의 수익률
    m = re.search(r"복리\s*연\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*수익률", section)
    if not m:
        m = re.search(r"연\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*수익률(?:이?\s*보장|을?\s*적용)", section)
    if m:
        v = float(m.group(1))
        if v > 0:
            return v / 100.0
    
    # (4b) 연 단리 N%의 이율
    m = re.search(r"연\s*단리\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*이율", section)
    if m:
        return float(m.group(1)) / 100.0
    
    # (4c) 연복리 N%의 이자율
    m = re.search(r"연복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%의?\s*이자율을?\s*적용", section)
    if m:
        return float(m.group(1)) / 100.0
    
    # (4d) N개월 단위 연복리
    m = re.search(r"(?:\d+개월|분기)\s*단위\s*연\s*복리\s*\[?(\d+(?:\.\d+)?)\]?\s*%", section)
    if m:
        v = float(m.group(1))
        if v > 0:
            return v / 100.0
    
    # (5) (1+0.NN)^ 공식
    m = re.search(r"\(1\s*\+\s*(0\.\d+)\)\s*\^", section)
    if m:
        v = float(m.group(1))
        if 0 < v < 1:
            return round(v, 4)
    
    # Put 수익률 (Call이 없는 경우 Put YTC라도)
    m_put = re.search(r"조기상환청구권", text)
    if m_put:
        put_sec = text[m_put.start(): m_put.start() + 3000]
        # 범위 형태: 5%~15%
        m_range = re.search(
            r"(?:연복리|복리\s*연|연\s*복리)\s*([0-9]+(?:\.\d+)?)\s*%\s*~\s*([0-9]+(?:\.\d+)?)\s*%",
            put_sec,
        )
        if m_range:
            return (float(m_range.group(1)) / 100.0, float(m_range.group(2)) / 100.0)
        m_single = re.search(r"(?:연복리|복리\s*연|연\s*복리)\s*\[?(\d+(?:\.\d+)?)\]?\s*%", put_sec)
        if m_single:
            return float(m_single.group(1)) / 100.0
    
    return None


def extract_ytc_reverse(xml, pymd):
    """매매가액 표에서 역산"""
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
    for r in rs:
        if not r or not r[0].strip():
            continue
        if not re.match(r"^\d+(차|회|호)?$|^\d+\s*$", r[0].strip()):
            continue
        row_dates = [_parse_date_any(c) for c in r]
        row_dates = [x for x in row_dates if x]
        if not row_dates:
            continue
        pay_date = max(row_dates)
        pct = None
        for c in reversed(r):
            m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$", c)
            if m:
                pct = float(m.group(1))
                break
        if pct is None:
            continue
        t_days = (pay_date - pymd).days
        if t_days <= 0:
            continue
        t_years = t_days / 365.25
        try:
            ytc = (pct / 100.0) ** (1.0 / t_years) - 1.0
        except (ValueError, ZeroDivisionError):
            continue
        if ytc <= 0.0 or ytc >= 1.0:
            continue
        return round(ytc, 3)
    return None


def extract_ytc(xml, pymd=None):
    v = extract_ytc_text(xml)
    if v is not None:
        return v
    return extract_ytc_reverse(xml, pymd)


# ============== 할증률 ==============
def extract_premium_rate(xml):
    """할증(할인)율 추출. 소수 반환 (0.15 = 15% 할증)."""
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    has_section = bool(re.search(r"(전환|행사|교환)가액\s*결정방법", text))
    
    # (1) 기준주가의 N%
    m = re.search(
        r"기준주가의?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:를|에)?\s*(?:해당하는?\s*가액을?\s*)?(?:최초\s*)?(?:전환|행사|교환)\s*가액",
        text,
    )
    if m:
        return round((float(m.group(1)) - 100.0) / 100.0, 4)
    
    # (1b) 동 가격의 N%
    m = re.search(r"동\s*가격의?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:에\s*해당하는)?\s*가액", text)
    if m:
        return round((float(m.group(1)) - 100.0) / 100.0, 4)
    
    # (1c) 가액의 N%에 해당하는 가액
    m = re.search(r"(?:가장\s*높은\s*)?가액의?\s*\[?(\d+(?:\.\d+)?)\]?\s*%\s*에?\s*해당하는\s*가액(?:으로\s*하되)?", text)
    if m:
        pct = float(m.group(1))
        if pct != 100.0:
            return round((pct - 100.0) / 100.0, 4)
    
    # (2) N% 할증
    m = re.search(r"\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:를)?\s*할증", text)
    if m:
        return round(float(m.group(1)) / 100.0, 4)
    
    # (3) N% 할인 (할인발행 제외)
    for m in re.finditer(r"\[?(\d+(?:\.\d+)?)\]?\s*%\s*(?:를)?\s*할인(\w*)", text):
        if "발행" not in m.group(2):
            return round(-float(m.group(1)) / 100.0, 4)
    
    if has_section:
        return 0.0
    return None


# ============== Refixing ==============
def extract_refixing(xml, base_price):
    """Refixing 한도 추출. (최저 조정가액) / base_price 비율 반환."""
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


# ============== 주식총수 대비 비율 ==============
def extract_capital_ratio(xml):
    """주식총수 대비 비율(%) 추출"""
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


# ============== 교환사채 - 교환대상주식 ==============
def extract_exchange_target(xml):
    if not xml:
        return None
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text)
    
    # 자기주식 우선
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
            raw = m.group(1).strip()
            raw = re.sub(r"\s+", " ", raw)
            raw = raw.replace("㈜", "").replace("주식회사", "").strip()
            if len(raw) > 50:
                raw = raw[:50] + "..."
            return raw if raw else None
    return None


# ============== 우선주 (CPS/RCPS) ==============
def extract_dividend_rate(xml):
    """우선배당률 + 참가/누적 속성"""
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
    """RCPS/RPS 상환이율"""
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


# ============== 공모 유상증자 ==============
def extract_discount_rate(xml):
    """공모 유상증자 할인율"""
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
    """공모 유상증자 대표주관회사"""
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


# ============== 통합 함수 ==============
def parse_disclosure_details(dart_key, rcept_no, pymd_str=None, base_price=None):
    """
    공시 본문에서 모든 정보 추출 (document.xml 사용)
    
    Args:
        dart_key: DART API key
        rcept_no: 공시 접수번호
        pymd_str: 납입일 YYYYMMDD (Put/Call 날짜 계산용)
        base_price: 전환가액/행사가액 (Refixing 계산용)
    
    Returns: dict
    """
    result = {
        "capital_ratio": "-",
        "put_option": "-",
        "call_option": "-",
        "call_ratio": "-",
        "ytc": "-",
        "refixing": "-",
        "underwriters": "-",
        "discount_rate": "-",
        "lead_managers": "-",
        "dividend_rate": "-",
        "redemption_rate": "-",
        "exchange_target": "-",
        "premium_rate": "-",
    }
    
    xml = fetch_document_xml(dart_key, rcept_no)
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
                fd = _duration_str(pymd, put["first"])
                iv = f" (매 {put['interval_months']}개월)" if put.get("interval_months") else ""
                result["put_option"] = f"발행일로부터 {fd} 후{iv}"
    except Exception as e:
        print(f"put_option 실패: {e}")
    
    # Call Option
    try:
        call = extract_call_schedule(xml)
        if not call and pymd:
            call = extract_call_text(xml, pymd)
        if call and pymd:
            fd = _duration_str(pymd, call["first"])
            ld = _duration_str(pymd, call["last"])
            iv = f" (매 {call['interval_months']}개월)" if call.get("interval_months") else ""
            if fd == ld:
                result["call_option"] = f"발행일로부터 {fd}{iv}"
            else:
                result["call_option"] = f"발행일로부터 {fd}~{ld}{iv}"
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
            if isinstance(v, tuple):
                result["ytc"] = f"{v[0]*100:.1f}%~{v[1]*100:.1f}%"
            else:
                result["ytc"] = f"{v*100:.1f}%"
    except Exception as e:
        print(f"ytc 실패: {e}")
    
    # Refixing
    try:
        v = extract_refixing(xml, base_price)
        if v is not None:
            result["refixing"] = f"{v*100:.0f}%"
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
    
    # 우선배당률
    try:
        v = extract_dividend_rate(xml)
        if v:
            result["dividend_rate"] = v
    except Exception as e:
        print(f"dividend_rate 실패: {e}")
    
    # 상환이율
    try:
        v = extract_redemption_rate(xml)
        if v is not None:
            result["redemption_rate"] = f"{v*100:.1f}%"
    except Exception as e:
        print(f"redemption_rate 실패: {e}")
    
    # 공모 유상증자 할인율
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
    
    return result


if __name__ == "__main__":
    import os
    dart_key = os.environ.get("DART_API_KEY", "f8a8d38311d5a3914032697a62b2ada1eb228624")
    
    test_cases = [
        ("20260520000262", "20260528", 5424, "엔젯 BW"),
        ("20260521000803", "20260528", 3875, "이엔플러스 CB"),
        ("20260521800995", "20260529", 5350, "에이프로젠 CB"),
        ("20260522000559", "20260610", 13070, "뉴라텍 CB"),
    ]
    
    for rcept_no, pymd_str, base_price, name in test_cases:
        print(f"\n=== {name} ({rcept_no}) ===")
        result = parse_disclosure_details(dart_key, rcept_no, pymd_str, base_price)
        for k, v in result.items():
            print(f"  {k}: {v}")
