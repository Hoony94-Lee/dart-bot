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


def parse_underwriters(text):
    """
    인수인 (집합투자업자 = 운용사명) 추출
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
    
    return result


if __name__ == "__main__":
    # 테스트
    result = parse_disclosure_details("20260520000262")
    for k, v in result.items():
        print(f"{k}: {v}")
