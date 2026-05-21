"""
DART 공시 본문 HTML 파서
- 주식총수 대비 비율
- Put Option / Call Option / Call 비율 / YTC
- Refixing 한도 / 조정 주기
- 인수인 (집합투자업자 = 운용사명)
"""
import re
import html as html_lib
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_viewer_dcmno(rcept_no):
    """공시 viewer 페이지에서 dcmNo 추출"""
    try:
        res = requests.get(
            "https://dart.fss.or.kr/dsaf001/main.do",
            params={"rcpNo": rcept_no},
            headers=HEADERS,
            timeout=10,
        )
        m = re.search(
            r"viewDoc\(['\"]" + rcept_no + r"['\"]\s*,\s*['\"](\d+)['\"]",
            res.text,
        )
        if m:
            return m.group(1)
    except Exception as e:
        print(f"dcmNo 조회 실패 ({rcept_no}): {e}")
    return None


def fetch_disclosure_text(rcept_no):
    """공시 본문 HTML → 정제된 텍스트"""
    dcm_no = fetch_viewer_dcmno(rcept_no)
    if not dcm_no:
        return None
    
    try:
        res = requests.get(
            "https://dart.fss.or.kr/report/viewer.do",
            params={
                "rcpNo": rcept_no,
                "dcmNo": dcm_no,
                "eleId": "0",
                "offset": "0",
                "length": "0",
                "dtd": "dart3.xsd",
            },
            headers=HEADERS,
            timeout=15,
        )
        html = res.text
        text = re.sub(r"<[^>]+>", " ", html)
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text
    except Exception as e:
        print(f"공시 본문 조회 실패 ({rcept_no}): {e}")
    return None


# ───────────────────────────────────────
# 개별 항목 파싱
# ───────────────────────────────────────
def parse_capital_ratio(text):
    """주식총수 대비 비율(%) 추출"""
    if not text:
        return "-"
    # 패턴: "주식총수 대비 비율(%) 7.94"
    m = re.search(r"주식총수\s*대비\s*비율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)", text)
    if m:
        try:
            return f"{float(m.group(1)):.2f}%"
        except ValueError:
            pass
    return "-"


def parse_put_option(text):
    """
    Put Option 행사 시점
    예: "발행일로부터 24개월 ... 57개월" → "발행일로부터 2년 후"
    
    회사채 관례상 첫 Put 시점만 표시 (start month)
    """
    if not text:
        return "-"
    
    # 조기상환청구권 영역 추출
    m = re.search(r"조기상환청구권.*?(?=매도청구권|콜옵션|\[Call|$)", text, re.DOTALL)
    if not m:
        return "-"
    seg = m.group(0)
    
    # "발행일로부터 N개월" 첫 번째 매칭
    m2 = re.search(r"발행일로부터\s*(\d+)\s*개월", seg)
    if m2:
        months = int(m2.group(1))
        if months % 12 == 0:
            return f"발행일로부터 {months // 12}년 후"
        return f"발행일로부터 {months}개월 후"
    return "-"


def parse_call_option(text):
    """
    Call Option 행사 기간
    예: "발행일로부터 12개월 ... 24개월" → "발행일로부터 1년~2년"
    """
    if not text:
        return "-"
    
    # 매도청구권 영역 추출
    m = re.search(r"매도청구권.*?(?=조기상환청구권|풋옵션|\[Put|기타\s*투자판단|합병|$)",
                  text, re.DOTALL)
    if not m:
        return "-"
    seg = m.group(0)
    
    # "발행일로부터 N개월 ... M개월"
    m2 = re.search(r"발행일로부터\s*(\d+)\s*개월.*?(\d+)\s*개월", seg)
    if m2:
        start = int(m2.group(1))
        end = int(m2.group(2))
        start_str = f"{start // 12}년" if start % 12 == 0 else f"{start}개월"
        end_str = f"{end // 12}년" if end % 12 == 0 else f"{end}개월"
        return f"발행일로부터 {start_str}~{end_str}"
    return "-"


def parse_call_ratio(text):
    """
    Call 비율 추출
    예: "각 인수인별로 각각 최초 전자등록총액의 60.0%를 초과" → "60.0%"
    """
    if not text:
        return "-"
    
    # 매도청구권 영역 한정
    m = re.search(r"매도청구권.*?(?=조기상환청구권|\[Put|기타\s*투자판단|합병|$)",
                  text, re.DOTALL)
    if not m:
        return "-"
    seg = m.group(0)
    
    # "최초 전자등록총액의 60.0%를 초과" 또는 "사채발행금액의 N%"
    patterns = [
        r"전자등록총액의\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*를?\s*초과",
        r"발행금액의\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*를?\s*초과",
        r"콜옵션.*?한도.*?([0-9]+(?:\.[0-9]+)?)\s*%",
        r"매수할\s*수\s*있.*?([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    for pat in patterns:
        m2 = re.search(pat, seg)
        if m2:
            try:
                return f"{float(m2.group(1)):.1f}%"
            except ValueError:
                continue
    return "-"


def parse_ytc(text):
    """
    YTC 추출
    예: "복리 연 3.0%의 수익률이 보장" → "3.0%"
    """
    if not text:
        return "-"
    
    m = re.search(r"매도청구권.*?(?=조기상환청구권|\[Put|기타\s*투자판단|합병|$)",
                  text, re.DOTALL)
    if not m:
        return "-"
    seg = m.group(0)
    
    patterns = [
        r"복리\s*연\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"연\s*복리\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"수익률.*?([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:의\s*)?수익률",
        r"단리\s*연\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    for pat in patterns:
        m2 = re.search(pat, seg)
        if m2:
            try:
                return f"{float(m2.group(1)):.1f}%"
            except ValueError:
                continue
    return "-"


def parse_refixing(text):
    """
    Refixing 한도 추출
    
    판정 로직:
    1. "최저 조정가액 (원)" 다음 값이 실제 숫자 → Refixing 있음
    2. "-"이면 → Refixing 없음 → "-"
    
    "발행당시 행사가액의 N% 미만으로 조정가능한 잔여 발행한도" 문구는
    공시 양식 문구일 뿐 Refixing 한도가 아니므로 사용하지 않음.
    """
    if not text:
        return "-"
    
    # "최저 조정가액 (원)" 다음 값 추출
    m = re.search(
        r"최저\s*조정\s*가액\s*\(?\s*원?\s*\)?\s*([0-9,]+|\-)",
        text,
    )
    if not m:
        return "-"
    
    raw_val = m.group(1).strip().replace(",", "")
    
    # "-"이면 Refixing 없음
    if raw_val == "-" or not raw_val.isdigit():
        return "-"
    
    try:
        min_price = int(raw_val)
    except ValueError:
        return "-"
    
    if min_price <= 0:
        return "-"
    
    # 행사가액/전환가액 추출 (Refixing 비율 계산용)
    # 패턴: "행사가액 5,424" 또는 "전환가액 X,XXX"
    base_price = None
    for pat in [
        r"행사가액\s*\(?\s*원?\s*\)?\s*([0-9,]+)",
        r"전환가액\s*\(?\s*원?\s*\)?\s*([0-9,]+)",
        r"교환가액\s*\(?\s*원?\s*\)?\s*([0-9,]+)",
    ]:
        m2 = re.search(pat, text)
        if m2:
            try:
                base_price = int(m2.group(1).replace(",", ""))
                if base_price > 0:
                    break
            except ValueError:
                continue
    
    if not base_price or base_price <= 0:
        return f"최저 {min_price:,}원"
    
    ratio = (min_price / base_price) * 100
    
    # 조정 주기 추출
    cycle = None
    cycle_patterns = [
        r"매\s*(\d+)\s*개월\s*마다\s*(?:행사가액|전환가액)?\s*조정",
        r"(?:행사가액|전환가액)\s*조정\s*주기.*?매\s*(\d+)\s*개월",
    ]
    for pat in cycle_patterns:
        m3 = re.search(pat, text)
        if m3:
            cycle = int(m3.group(1))
            break
    
    if cycle:
        return f"{ratio:.0f}% (매 {cycle}개월마다)"
    return f"{ratio:.0f}%"


def parse_dividend_rate(text):
    """
    우선주 우선배당률 추출
    예: "우선배당률 1.0% 참가적 누적적" → "1.0%(참가적, 누적적)"
    
    공시 본문 패턴:
    - "우선배당률(%) 1.0" 또는 "우선배당율 1.0%"
    - "참가적/비참가적", "누적적/비누적적" 별도 항목으로 표기
    """
    if not text:
        return "-"
    
    # 우선배당률 추출
    rate = None
    patterns = [
        r"우선배당률\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"우선배당율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"배당률\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                rate = float(m.group(1))
                if rate > 0:
                    break
            except ValueError:
                continue
    
    if rate is None or rate == 0:
        return "-"
    
    rate_str = f"{rate:.1f}%"
    
    # 참가적/비참가적, 누적적/비누적적 속성 추출
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
        return f"{rate_str}({', '.join(attrs)})"
    return rate_str


def parse_redemption_rate(text):
    """
    상환이율(RCPS/RPS) 추출
    예: "상환이자율 2.0%" 또는 "상환수익률 연 복리 2.0%" → "2.0%"
    
    공시 본문 패턴:
    - "상환이자율(%)"
    - "상환수익률 연 X% 복리"
    - "조기상환수익률" (상환우선주의 상환 조건)
    """
    if not text:
        return "-"
    
    patterns = [
        r"상환이자율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"상환수익률\s*(?:연\s*복리\s*)?([0-9]+(?:\.[0-9]+)?)\s*%",
        r"조기상환수익률\s*(?:연\s*복리\s*)?([0-9]+(?:\.[0-9]+)?)\s*%",
        r"상환\s*시\s*수익률\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"연\s*복리\s*([0-9]+(?:\.[0-9]+)?)\s*%의?\s*수익률.*?상환",
    ]
    
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1))
                if val > 0:
                    return f"{val:.1f}%"
            except ValueError:
                continue
    
    return "-"


def parse_exchange_target(text):
    """
    교환사채(EB)의 교환대상주식 추출
    
    공시 본문 패턴:
    - "교환대상 주식의 종류 자기주식" 또는 "교환대상 주식: OO기업 보통주"
    - 표 형태: "교환대상 - 종류 - {주식명}"
    """
    if not text:
        return "-"
    
    # 자기주식 우선 매칭
    if re.search(r"자기주식.*?교환", text) or re.search(r"교환[^.]*?자기주식", text):
        return "자기주식"
    
    # 회사명 + 보통주/우선주 패턴
    patterns = [
        # "교환대상 주식의 종류 {주식명}"
        r"교환대상\s*주식의?\s*종류\s*[:：]?\s*([가-힣A-Za-z0-9㈜().\s]+?(?:보통주|우선주))",
        # "교환대상 : {주식명}"
        r"교환대상\s*[:：]\s*([가-힣A-Za-z0-9㈜().\s]+?(?:보통주|우선주))",
        # "교환의 대상이 되는 주식 {주식명}"
        r"교환의?\s*대상(?:이\s*되는)?\s*주식\s*[:：]?\s*([가-힣A-Za-z0-9㈜().\s]+?(?:보통주|우선주))",
        # 표 형태: "교환대상 주식 {주식명}"
        r"교환대상\s*주식\s+([가-힣A-Za-z0-9㈜()]+(?:\s+(?:보통주|우선주)))",
    ]
    
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).strip()
            raw = re.sub(r"\s+", " ", raw)
            raw = raw.replace("㈜", "").replace("주식회사", "").strip()
            if len(raw) > 50:
                raw = raw[:50] + "..."
            return raw if raw else "-"
    
    return "-"


def parse_premium_rate(text):
    """
    교환사채/전환사채 할증률 추출
    예: "기준주가에 10% 할증" → "10.0%"
    
    공시 본문 패턴:
    - "할증률(%) 10" 또는 "할증율 10%"  
    - "기준주가 대비 N% 할증"
    - "산술평균가액에 N%를 가산"
    """
    if not text:
        return "-"
    
    patterns = [
        r"할증률\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"할증율\s*\(?\s*%?\s*\)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:를|을)?\s*(?:할증|가산)",
        r"(?:할증|가산)\s*(?:한|하여)?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"기준주가\s*대비\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1))
                if val == 0:
                    return "-"
                return f"{val:.1f}%"
            except ValueError:
                continue
    
    return "-"


def parse_discount_rate(text):
    """
    공모 유상증자 할인율 추출
    예: "할인율(%) 25" 또는 "할인율 25%" → "25%"
    
    공시 본문 양식: 
    "신주발행가액" 표에 "할인율(또는 할증율)(%)" 항목으로 표기됨
    """
    if not text:
        return "-"
    
    # 패턴: "할인율" 다음 숫자
    patterns = [
        r"할인율\s*\(?\s*%?\s*\)?\s*(?:또는\s*할증율\s*\(?\s*%?\s*\)?)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"할증율\s*\(?\s*%?\s*\)?\s*(?:또는\s*할인율\s*\(?\s*%?\s*\)?)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"할인율\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1))
                # 0이면 할인 없음
                if val == 0:
                    return "-"
                return f"{val:.1f}%"
            except ValueError:
                continue
    
    return "-"


def parse_underwriters(text):
    """
    사모 메자닌 인수인 (집합투자업자 = 운용사명) 추출
    예: "코리아자산운용 주식회사, 르퓨쳐자산운용 주식회사" → "코리아자산운용, 르퓨쳐자산운용"
    """
    if not text:
        return "-"
    
    # "집합투자업자" 컬럼에 있는 운용사명 추출
    # 패턴: "{운용사명}자산운용" 형태
    asset_mgmt_pattern = r"([가-힣A-Za-z]+자산운용)(?:\s*(?:주식회사|㈜))?"
    
    # "집합투자업자" 또는 "특정인" 영역에서 찾기
    section_match = re.search(
        r"(?:집합투자업자|특정인에 대한 대상자별|투자자\s*정보).*?(?=$)",
        text,
        re.DOTALL,
    )
    
    seg = section_match.group(0) if section_match else text
    
    matches = re.findall(asset_mgmt_pattern, seg)
    if not matches:
        return "-"
    
    # 중복 제거 (순서 유지)
    seen = set()
    unique = []
    for name in matches:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    
    if not unique:
        return "-"
    
    return ", ".join(unique)


def parse_lead_managers(text):
    """
    공모 유상증자 대표주관회사 추출
    
    공시 본문에서 "대표주관회사" 컬럼/라인의 증권사명 추출.
    예: "한국투자증권, 미래에셋증권" → "한국투자증권, 미래에셋증권"
    
    공동 대표주관회사가 여러 곳인 경우도 모두 추출.
    """
    if not text:
        return "-"
    
    # 1차: "대표주관회사" 키워드 다음 텍스트 영역
    # 패턴: "대표주관회사 OOO증권" 형태 (다음 키워드까지)
    next_keywords = (
        r"(?:인수인|모집주선|공동주관|일반공모|청약\s*개시|"
        r"\d+\.\s|\d+\)\s|증자방식|신주의\s*종류|발행\s*가액|"
        r"모집매출\s*방법|기타|【|《|■)"
    )
    
    patterns = [
        # "대표주관회사 [공동] : OOO증권, XXX증권"
        rf"대표주관회사\s*(?:\(공동\)|공동)?\s*[:：]?\s*([^\n]{{1,200}}?)(?=\s*{next_keywords})",
        # "대표주관회사 OOO증권" (단순)
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
        return "-"
    
    # 증권사명 추출 (한글 + "증권" 패턴)
    # "한국투자증권㈜" → "한국투자증권"
    # "NH투자증권 주식회사" → "NH투자증권"
    securities_pattern = r"([가-힣A-Za-z]+(?:투자)?증권)(?:\s*(?:주식회사|㈜|\(주\)))?"
    matches = re.findall(securities_pattern, raw_text)
    
    if not matches:
        # 증권사 패턴 매칭 안되면 원본 텍스트 일부 반환
        cleaned = re.sub(r"\s+", " ", raw_text).strip()
        cleaned = cleaned.rstrip(",").strip()
        # 너무 길면 자르기
        if len(cleaned) > 100:
            cleaned = cleaned[:100] + "..."
        return cleaned if cleaned else "-"
    
    # 중복 제거 (순서 유지)
    seen = set()
    unique = []
    for name in matches:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    
    return ", ".join(unique)


# ───────────────────────────────────────
# 통합 함수
# ───────────────────────────────────────
def parse_disclosure_details(rcept_no):
    """
    공시 본문에서 모든 부가 정보 추출
    
    Returns: dict
        {
            "capital_ratio": "7.94%",
            "put_option": "발행일로부터 2년 후",
            "call_option": "발행일로부터 1년~2년",
            "call_ratio": "60.0%",
            "ytc": "3.0%",
            "refixing": "70% (매 7개월마다)" or "70%",
            "underwriters": "코리아자산운용, 르퓨처자산운용, ..."
        }
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
    
    text = fetch_disclosure_text(rcept_no)
    if not text:
        return result
    
    try:
        result["capital_ratio"] = parse_capital_ratio(text)
    except Exception as e:
        print(f"capital_ratio 파싱 실패: {e}")
    
    try:
        result["put_option"] = parse_put_option(text)
    except Exception as e:
        print(f"put_option 파싱 실패: {e}")
    
    try:
        result["call_option"] = parse_call_option(text)
    except Exception as e:
        print(f"call_option 파싱 실패: {e}")
    
    try:
        result["call_ratio"] = parse_call_ratio(text)
    except Exception as e:
        print(f"call_ratio 파싱 실패: {e}")
    
    try:
        result["ytc"] = parse_ytc(text)
    except Exception as e:
        print(f"ytc 파싱 실패: {e}")
    
    try:
        result["refixing"] = parse_refixing(text)
    except Exception as e:
        print(f"refixing 파싱 실패: {e}")
    
    try:
        result["underwriters"] = parse_underwriters(text)
    except Exception as e:
        print(f"underwriters 파싱 실패: {e}")
    
    try:
        result["discount_rate"] = parse_discount_rate(text)
    except Exception as e:
        print(f"discount_rate 파싱 실패: {e}")
    
    try:
        result["lead_managers"] = parse_lead_managers(text)
    except Exception as e:
        print(f"lead_managers 파싱 실패: {e}")
    
    try:
        result["dividend_rate"] = parse_dividend_rate(text)
    except Exception as e:
        print(f"dividend_rate 파싱 실패: {e}")
    
    try:
        result["redemption_rate"] = parse_redemption_rate(text)
    except Exception as e:
        print(f"redemption_rate 파싱 실패: {e}")
    
    try:
        result["exchange_target"] = parse_exchange_target(text)
    except Exception as e:
        print(f"exchange_target 파싱 실패: {e}")
    
    try:
        result["premium_rate"] = parse_premium_rate(text)
    except Exception as e:
        print(f"premium_rate 파싱 실패: {e}")
    
    return result


if __name__ == "__main__":
    # 테스트
    result = parse_disclosure_details("20260520000262")
    for k, v in result.items():
        print(f"{k}: {v}")
