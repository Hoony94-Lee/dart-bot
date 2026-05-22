import os
import re
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from stock_data import (
    fetch_stock_price_and_mktcap,
    fmt_market_cap,
    fmt_close_price,
)
from disclosure_parser import parse_disclosure_details

DART_KEY = os.environ["DART_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TARGET_TYPES = [
    ("전환사채권발행결정",        "CB"),
    ("신주인수권부사채권발행결정", "BW"),
    ("교환사채권발행결정",        "EB"),
    ("유상증자결정",             "RI"),
]

PREFERRED_STOCK_KEYWORDS = [
    "전환우선주",
    "상환전환우선주",
    "전환상환우선주",
    "상환우선주",
]

EXCLUDE = ["철회", "기재정정", "정정"]

SENT_FILE = "sent.json"
HOLIDAY_FILE = "holidays.json"


# ───────────────────────────────────────
# 휴장일 / 발송기록
# ───────────────────────────────────────
def is_holiday():
    """주말, 공휴일, 또는 영업시간 외 발송 차단"""
    kst = ZoneInfo("Asia/Seoul")
    now = datetime.now(kst)
    today = now.strftime("%Y-%m-%d")
    weekday = now.weekday()
    
    # 주말 차단
    if weekday >= 5:
        print(f"오늘({today})은 주말. 발송 생략.")
        return True
    
    # 영업시간 차단 (KST 06:00 ~ 20:30)
    hour = now.hour
    minute = now.minute
    current_minutes = hour * 60 + minute
    
    BUSINESS_START = 6 * 60        # 06:00
    BUSINESS_END = 20 * 60 + 30    # 20:30
    
    if current_minutes < BUSINESS_START or current_minutes > BUSINESS_END:
        print(f"현재 시각({now.strftime('%H:%M')})은 영업시간 외. 발송 생략.")
        return True
    
    # 공휴일 차단
    if os.path.exists(HOLIDAY_FILE):
        with open(HOLIDAY_FILE) as f:
            holidays = json.load(f)
        if today in holidays:
            print(f"오늘({today})은 휴장일. 발송 생략.")
            return True
    
    return False


def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE) as f:
            return set(json.load(f))
    return set()


def save_sent(sent):
    with open(SENT_FILE, "w") as f:
        json.dump(list(sent)[-1000:], f)


# ───────────────────────────────────────
# 유틸리티
# ───────────────────────────────────────
def fmt_amount(value):
    """금액을 억원 단위로 포맷 (정수 형태, 예: 50억원)"""
    try:
        v = int(str(value).replace(",", "").replace("-", "0"))
        if v == 0:
            return "-"
        uk = v / 100000000
        return f"{uk:,.0f}억원"
    except (ValueError, TypeError):
        return str(value) if value else "-"


def fmt_date(date_str):
    """날짜 포맷 (YYYYMMDD → YYYY-MM-DD)"""
    if not date_str or date_str == "-":
        return "-"
    s = str(date_str).replace(".", "-").replace("/", "-")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def fmt_pct(value):
    if not value or value == "-":
        return "-"
    try:
        v = float(str(value).replace(",", "").replace("%", ""))
        return f"{v:.1f}%"
    except (ValueError, TypeError):
        return str(value)


def fmt_num(value):
    if not value or value == "-":
        return "-"
    try:
        return f"{int(str(value).replace(',', '')):,}"
    except (ValueError, TypeError):
        return str(value)


def safe_get(d, *keys, default="-"):
    for k in keys:
        v = d.get(k)
        if v and str(v).strip() and str(v).strip() != "-":
            return str(v).strip()
    return default


def is_preferred_stock(stock_type_str):
    if not stock_type_str or stock_type_str == "-":
        return False
    return any(kw in stock_type_str for kw in PREFERRED_STOCK_KEYWORDS)


def get_price_ref_date(rcept_dt, rcept_tm):
    """
    공시 시간 기준으로 종가 기준일 결정
    - 15:30 이후 공시 → 이사회결의일 당일 종가
    - 15:30 이전 공시 → 이사회결의일 전일 종가
    """
    if not rcept_dt or not rcept_tm:
        return "-"
    try:
        tm_int = int(str(rcept_tm).zfill(4))
        date_obj = datetime.strptime(rcept_dt, "%Y%m%d")
        if tm_int >= 1530:
            return date_obj.strftime("%Y-%m-%d")
        else:
            prev_date = date_obj - timedelta(days=1)
            return prev_date.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "-"


def fmt_short_date(date_str):
    """YYYY-MM-DD → M/D 형식 변환 (예: 2026-05-20 → 5/20)"""
    if not date_str or date_str == "-":
        return "-"
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{date_obj.month}/{date_obj.day}"
    except (ValueError, TypeError):
        return date_str


# ───────────────────────────────────────
# DART 공시 조회
# ───────────────────────────────────────
def fetch_disclosures():
    kst = ZoneInfo("Asia/Seoul")
    today = datetime.now(kst).strftime("%Y%m%d")
    yesterday = (datetime.now(kst) - timedelta(days=1)).strftime("%Y%m%d")
    
    all_items = []
    for page in range(1, 6):
        res = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": DART_KEY,
                "bgn_de": yesterday,
                "end_de": today,
                "page_no": page,
                "page_count": 100,
            },
            timeout=30,
        ).json()
        if res.get("status") != "000":
            print(f"DART API status: {res.get('status')}")
            break
        items = res.get("list", [])
        if not items:
            break
        all_items.extend(items)
        if len(items) < 100:
            break
    return all_items


def match_type(title):
    for keyword, code in TARGET_TYPES:
        if keyword in title:
            return code
    return None


def filter_items(items, sent):
    result = []
    for item in items:
        title = item.get("report_nm", "")
        rcept_no = item.get("rcept_no", "")
        if rcept_no in sent:
            continue
        if any(ex in title for ex in EXCLUDE):
            continue
        code = match_type(title)
        if not code:
            continue
        item["_type_code"] = code
        result.append(item)
    return result


def fetch_detail(corp_code, rcept_no, type_code):
    endpoints = {
        "CB": "cvbdIsDecsn",
        "BW": "bdwtIsDecsn",
        "EB": "exbdIsDecsn",
        "RI": "piicDecsn",
    }
    endpoint = endpoints.get(type_code)
    if not endpoint:
        return None
    
    kst = ZoneInfo("Asia/Seoul")
    end_de = datetime.now(kst).strftime("%Y%m%d")
    bgn_de = (datetime.now(kst) - timedelta(days=2)).strftime("%Y%m%d")
    
    res = requests.get(
        f"https://opendart.fss.or.kr/api/{endpoint}.json",
        params={
            "crtfc_key": DART_KEY,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
        },
        timeout=30,
    ).json()
    
    if res.get("status") != "000":
        if type_code == "RI":
            res = requests.get(
                "https://opendart.fss.or.kr/api/pifricDecsn.json",
                params={
                    "crtfc_key": DART_KEY,
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
                timeout=30,
            ).json()
            if res.get("status") != "000":
                return None
        else:
            return None
    
    items = res.get("list", [])
    for item in items:
        if item.get("rcept_no") == rcept_no:
            return item
    return items[0] if items else None


# ───────────────────────────────────────
# 메시지 포맷팅
# ───────────────────────────────────────
def format_bond_message(item, detail):
    """CB/BW/EB 통합 포맷"""
    type_map = {
        "CB": "전환사채발행결정",
        "BW": "신주인수권부사채발행결정",
        "EB": "교환사채발행결정",
    }
    # 가격 항목 라벨 분기
    price_label_map = {
        "CB": "전환가액",
        "BW": "행사가액",
        "EB": "교환가액",
    }
    type_code = item["_type_code"]
    title_name = type_map[type_code]
    price_label = price_label_map[type_code]
    
    corp = item["corp_name"]
    rcept_no = item["rcept_no"]
    rcept_dt = item.get("rcept_dt", "")
    rcept_tm = item.get("rcept_tm", "")
    corp_code = item.get("corp_code", "")
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    
    if not detail:
        return (
            f"✅주요사항보고서({title_name})\n"
            f"기업명: {corp}\n"
            f"(상세 정보 조회 실패 - 원문 확인 필요)\n\n"
            f"🔗 {url}"
        )
    
    # 기본정보
    amount = fmt_amount(safe_get(detail, "bd_fta"))
    
    # 시가총액, 종가 (NaverFinance API)
    price_ref_date = get_price_ref_date(rcept_dt, rcept_tm)
    stock_data = fetch_stock_price_and_mktcap(corp_code, price_ref_date, DART_KEY)
    mkt_cap_str = fmt_market_cap(stock_data["market_cap"])
    close_price_str = fmt_close_price(stock_data["close_price"])
    
    # 발행 스케줄
    board_date = fmt_date(safe_get(detail, "bddd"))
    issue_date = fmt_date(safe_get(detail, "pymd"))
    maturity_date = fmt_date(safe_get(detail, "bd_mtd"))
    
    # 가격 조건
    exec_price_raw = safe_get(detail, "cv_prc")
    exec_price = fmt_num(exec_price_raw)
    try:
        base_price = int(str(exec_price_raw).replace(",", "")) if exec_price_raw != "-" else None
    except (ValueError, TypeError):
        base_price = None
    
    # 공시 본문 파싱
    pymd_str = safe_get(detail, "pymd")
    parsed = parse_disclosure_details(DART_KEY, rcept_no, pymd_str, base_price)
    
    # 금리 조건
    coupon = safe_get(detail, "bd_intr_ex")
    ytm = safe_get(detail, "bd_intr_sf")
    coupon_str = f"{coupon}% / {ytm}%" if coupon != "-" or ytm != "-" else "-"
    
    # 가격 섹션 (EB는 할증률 + 교환대상주식 추가)
    if type_code == "EB":
        price_section = (
            f"발행금액: {amount}\n"
            f"{price_label}: {exec_price}원 ({fmt_short_date(price_ref_date)} 종가 {close_price_str}원)\n"
            f"할증률: {parsed['premium_rate']}\n"
            f"교환대상주식: {parsed['exchange_target']}\n"
            f"주식총수 대비 비율: {parsed['capital_ratio']}"
        )
    else:
        price_section = (
            f"발행금액: {amount}\n"
            f"{price_label}: {exec_price}원 ({fmt_short_date(price_ref_date)} 종가 {close_price_str}원)\n"
            f"주식총수 대비 비율: {parsed['capital_ratio']}"
        )
    
    return (
        f"✅주요사항보고서({title_name})\n"
        f"기업명: {corp} (시가총액 {mkt_cap_str}억원)\n"
        f"{price_section}\n\n"
        f"이사회결의일: {board_date}\n"
        f"발행일: {issue_date}\n"
        f"만기일: {maturity_date}\n\n"
        f"Coupon/YTM: {coupon_str}\n"
        f"Refixing: {parsed['refixing']}\n"
        f"Put Option: {parsed['put_option']}\n"
        f"Call Option: {parsed['call_option']}\n"
        f"Call 비율: {parsed['call_ratio']}\n"
        f"YTC: {parsed['ytc']}\n"
        f"인수인: {parsed['underwriters']}\n\n"
        f"🔗 {url}"
    )


def format_ri_message(item, detail):
    """유상증자"""
    corp = item["corp_name"]
    rcept_no = item["rcept_no"]
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    
    if not detail:
        return None
    
    stock_type = safe_get(detail, "nstk_kndn")
    method = safe_get(detail, "ic_mthn")
    
    public_keywords = ["주주배정", "일반공모", "실권주"]
    is_public = any(kw in method for kw in public_keywords)
    
    if is_preferred_stock(stock_type):
        return _format_ri_preferred(item, detail, corp, url, stock_type, method)
    if is_public:
        return _format_ri_public(item, detail, corp, url, stock_type, method)
    return None


def _format_ri_preferred(item, detail, corp, url, stock_type, method):
    """
    종류주 유상증자 (CPS, RCPS, CRPS, RPS)
    
    표시 항목:
    - 공통: 우선배당률, Refixing, Call Option, Call 비율, YTC, 인수인
    - RCPS/RPS만: Put Option, 상환이율 (상환권이 있는 우선주)
    """
    rcept_dt = item.get("rcept_dt", "")
    rcept_tm = item.get("rcept_tm", "")
    rcept_no = item["rcept_no"]
    corp_code = item.get("corp_code", "")
    
    amount = fmt_amount(safe_get(detail, "fdpp_amount"))
    price_ref_date = get_price_ref_date(rcept_dt, rcept_tm)
    stock_data = fetch_stock_price_and_mktcap(corp_code, price_ref_date, DART_KEY)
    mkt_cap_str = fmt_market_cap(stock_data["market_cap"])
    close_price_str = fmt_close_price(stock_data["close_price"])
    
    conv_price_raw = safe_get(detail, "nstk_isstk_pr")
    conv_price = fmt_num(conv_price_raw)
    try:
        base_price = int(str(conv_price_raw).replace(",", "")) if conv_price_raw != "-" else None
    except (ValueError, TypeError):
        base_price = None
    
    pymd_str = safe_get(detail, "pymd")
    parsed = parse_disclosure_details(DART_KEY, rcept_no, pymd_str, base_price)
    
    board_date = fmt_date(safe_get(detail, "bddd"))
    pay_date = fmt_date(safe_get(detail, "pymd"))
    
    # 상환권 있는 우선주 판정 (RCPS, RPS, 상환전환우선주, 상환우선주 등)
    has_redemption = any(kw in stock_type for kw in [
        "상환전환우선주",
        "전환상환우선주",
        "상환우선주",
        "RCPS",
        "RPS",
    ])
    
    # 상환권 있는 경우에만 Put Option + 상환이율 표시
    if has_redemption:
        redemption_section = (
            f"우선배당률: {parsed['dividend_rate']}\n"
            f"Refixing: {parsed['refixing']}\n"
            f"Put Option: {parsed['put_option']}\n"
            f"상환이율: {parsed['redemption_rate']}\n"
            f"Call Option: {parsed['call_option']}\n"
            f"Call 비율: {parsed['call_ratio']}\n"
            f"YTC: {parsed['ytc']}\n"
            f"인수인: {parsed['underwriters']}"
        )
    else:
        redemption_section = (
            f"우선배당률: {parsed['dividend_rate']}\n"
            f"Refixing: {parsed['refixing']}\n"
            f"Call Option: {parsed['call_option']}\n"
            f"Call 비율: {parsed['call_ratio']}\n"
            f"YTC: {parsed['ytc']}\n"
            f"인수인: {parsed['underwriters']}"
        )
    
    return (
        f"✅주요사항보고서(유상증자결정)\n"
        f"기업명: {corp} (시가총액 {mkt_cap_str}억원)\n"
        f"신주의 종류: {stock_type}\n"
        f"발행금액: {amount}\n"
        f"전환가액: {conv_price}원 ({fmt_short_date(price_ref_date)} 종가 {close_price_str}원)\n"
        f"주식총수 대비 비율: {parsed['capital_ratio']}\n\n"
        f"이사회결의일: {board_date}\n"
        f"납입일: {pay_date}\n\n"
        f"{redemption_section}\n\n"
        f"🔗 {url}"
    )


def _format_ri_public(item, detail, corp, url, stock_type, method):
    """공모 유상증자"""
    rcept_dt = item.get("rcept_dt", "")
    rcept_tm = item.get("rcept_tm", "")
    rcept_no = item["rcept_no"]
    corp_code = item.get("corp_code", "")
    
    amount = fmt_amount(safe_get(detail, "fdpp_amount"))
    price_ref_date = get_price_ref_date(rcept_dt, rcept_tm)
    stock_data = fetch_stock_price_and_mktcap(corp_code, price_ref_date, DART_KEY)
    mkt_cap_str = fmt_market_cap(stock_data["market_cap"])
    close_price_str = fmt_close_price(stock_data["close_price"])
    
    issue_price_raw = safe_get(detail, "nstk_isstk_pr")
    issue_price = fmt_num(issue_price_raw)
    try:
        base_price = int(str(issue_price_raw).replace(",", "")) if issue_price_raw != "-" else None
    except (ValueError, TypeError):
        base_price = None
    
    pymd_str = safe_get(detail, "pymd")
    parsed = parse_disclosure_details(DART_KEY, rcept_no, pymd_str, base_price)
    
    new_shares = fmt_num(safe_get(detail, "nstk_ostk_cnt"))
    
    board_date = fmt_date(safe_get(detail, "bddd"))
    pay_date = fmt_date(safe_get(detail, "pymd"))
    listing_date = fmt_date(safe_get(detail, "nstk_lstd_pd"))
    
    osh_sub_start = fmt_date(safe_get(detail, "osh_sbd_st_dt"))
    osh_sub_end = fmt_date(safe_get(detail, "osh_sbd_ed_dt"))
    osh_sub = f"{osh_sub_start} ~ {osh_sub_end}" if osh_sub_start != "-" else "-"
    
    gnrl_sub_start = fmt_date(safe_get(detail, "gnrl_sbd_st_dt"))
    gnrl_sub_end = fmt_date(safe_get(detail, "gnrl_sbd_ed_dt"))
    gnrl_sub = f"{gnrl_sub_start} ~ {gnrl_sub_end}" if gnrl_sub_start != "-" else "-"
    
    new_shares_str = f"{stock_type} {new_shares}주" if stock_type != "-" else f"{new_shares}주"
    
    return (
        f"✅주요사항보고서(유상증자결정)\n"
        f"기업명: {corp} (시가총액 {mkt_cap_str}억원)\n"
        f"증자방식: {method}\n"
        f"발행금액: {amount}\n"
        f"신주의 종류와 수: {new_shares_str}\n"
        f"예정 발행가액: {issue_price}원 ({fmt_short_date(price_ref_date)} 종가 {close_price_str}원)\n"
        f"주식총수 대비 비율: {parsed['capital_ratio']}\n"
        f"할인율: {parsed['discount_rate']}\n\n"
        f"이사회결의일: {board_date}\n"
        f"구주주청약: {osh_sub}\n"
        f"일반공모청약: {gnrl_sub}\n"
        f"납입일: {pay_date}\n"
        f"신주상장예정일: {listing_date}\n"
        f"대표주관회사: {parsed['lead_managers']}\n\n"
        f"🔗 {url}"
    )


def format_message(item):
    corp_code = item.get("corp_code", "")
    rcept_no = item.get("rcept_no", "")
    type_code = item["_type_code"]
    
    detail = fetch_detail(corp_code, rcept_no, type_code)
    
    if type_code == "RI":
        return format_ri_message(item, detail)
    else:
        return format_bond_message(item, detail)


def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={
            "chat_id": TG_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )


# ───────────────────────────────────────
# 메인
# ───────────────────────────────────────
def main():
    if is_holiday():
        return
    
    sent = load_sent()
    items = fetch_disclosures()
    new_items = filter_items(items, sent)
    
    print(f"전체 공시: {len(items)}건, 신규 매칭: {len(new_items)}건")
    
    new_items.sort(key=lambda x: x.get("rcept_dt", "") + x.get("rcept_no", ""))
    
    sent_count = 0
    skipped_count = 0
    
    for item in new_items:
        try:
            msg = format_message(item)
            if msg is None:
                print(f"스킵: {item['corp_name']}")
                sent.add(item["rcept_no"])
                skipped_count += 1
                continue
            send_telegram(msg)
            sent.add(item["rcept_no"])
            sent_count += 1
            print(f"발송 완료: {item['corp_name']} - {item['report_nm']}")
        except Exception as e:
            print(f"오류 ({item.get('corp_name')}): {e}")
            continue
    
    save_sent(sent)
    print(f"종료 - 발송: {sent_count}건, 스킵: {skipped_count}건")


if __name__ == "__main__":
    main()
