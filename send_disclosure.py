import os
import re
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

MARKET_MAP = {"Y": "유가", "K": "코스닥", "N": "코넥스", "E": "기타"}


# ───────────────────────────────────────
# 휴장일 / 발송기록
# ───────────────────────────────────────
def is_holiday():
    kst = ZoneInfo("Asia/Seoul")
    today = datetime.now(kst).strftime("%Y-%m-%d")
    weekday = datetime.now(kst).weekday()
    if weekday >= 5:
        print(f"오늘({today})은 주말. 발송 생략.")
        return True
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
    try:
        v = int(str(value).replace(",", "").replace("-", "0"))
        if v == 0:
            return "-"
        if v >= 100000000:
            uk = v / 100000000
            if uk >= 100:
                return f"{uk:,.0f}억원"
            return f"{uk:,.1f}억원"
        return f"{v:,}원"
    except (ValueError, TypeError):
        return str(value) if value else "-"


def fmt_date(date_str):
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
        return f"{v:.2f}%"
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


def extract_premium(text):
    """
    가액 결정방법 텍스트에서 할증률을 추출한다.
    
    예시:
    - "...높은 가액에 7%를 할증한 금액..." → 7.0%
    - "...산술평균한 가격과 최근일... 중 높은 가격 이상..." → "-" (할증 없음)
    - "...10%를 가산한 금액..." → 10.0%
    - "...에 5% 가산하여..." → 5.0%
    
    Returns: "7.0%" 형태의 문자열 or "-"
    """
    if not text or text == "-":
        return "-"
    
    # 할증/가산을 의미하는 키워드와 % 조합 검색
    # 예: "7%를 할증", "10% 가산", "에 5%를 더한", "+ 7%", "플러스 5%"
    patterns = [
        r"([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:를|을)?\s*(?:할증|가산|더한|더하여|더해|플러스|할증하여)",
        r"(?:할증|가산|더한|플러스)\s*(?:한|하여|하는|하면)?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"에\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:를|을)?\s*(?:할증|가산|더한|더하여|더해)",
        r"\+\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1))
                return f"{val:.1f}%"
            except ValueError:
                continue
    
    return "-"


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
def format_cb_message(item, detail, market):
    type_name = {"CB": "전환사채", "BW": "신주인수권부사채", "EB": "교환사채"}[item["_type_code"]]
    type_label = {"CB": "전환", "BW": "행사", "EB": "교환"}[item["_type_code"]]
    
    corp = item["corp_name"]
    rcept_no = item["rcept_no"]
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    
    if not detail:
        return (
            f"✅[{market}] {type_name} 발행결정\n\n"
            f"* 기업명: {corp}\n"
            f"(상세 정보 조회 실패 - 원문 확인 필요)\n\n"
            f"🔗 {url}"
        )
    
    amount = fmt_amount(safe_get(detail, "bd_fta", "ovis_fta"))
    coupon = safe_get(detail, "bd_intr_ex", "bd_intr_rt")
    ytm = safe_get(detail, "bd_intr_sf", "bd_mtd_intr_rt")
    coupon_str = f"{coupon}% / {ytm}%" if coupon != "-" or ytm != "-" else "-"
    
    board_date = fmt_date(safe_get(detail, "bddd"))
    issue_date = fmt_date(safe_get(detail, "pymd", "bdis_pymd"))
    maturity_date = fmt_date(safe_get(detail, "bd_mtd", "bdmt_ediscbd"))
    
    conv_price = fmt_num(safe_get(detail, "cv_prc", "ex_prc", "exct_prc"))
    conv_ratio = fmt_pct(safe_get(detail, "act_mktprcdiv_rt", "ratlst_isstkrt"))
    
    # 할증률: 가액 결정방법 텍스트에서 추출
    decision_text = safe_get(
        detail,
        "cv_prc_dmd_mth",      # 전환가액 결정방법
        "ex_prc_dmd_mth",      # 행사가액 결정방법
        "exct_prc_dmd_mth",    # 교환가액 결정방법
        "cv_prc_dmd",
        "ex_prc_dmd",
        "exct_prc_dmd",
    )
    premium_str = extract_premium(decision_text)
    
    put_opt = safe_get(detail, "rpcmt_opt_ow_int_dts", "rpcmtad_pym")
    call_opt = safe_get(detail, "spcmt_opt_ow_int_dts", "spcmtad_pym")
    
    # YTC (Yield to Call)
    ytc = safe_get(detail, "spcmt_intr", "spcmt_intr_rt", "ytc")
    ytc_str = f"{ytc}%" if ytc != "-" else "-"
    
    refix = safe_get(detail, "act_mktprcdv_lwlmt", "rfix_lwlmt")
    refix_str = f"{refix}%" if refix != "-" else "-"
    
    underwriter = safe_get(detail, "atn_nm", "thrd_pps_corp_nm")
    use = safe_get(detail, "fdpp_fclt", "fdpp_op", "use_purps")
    
    return (
        f"✅[{market}] {type_name} 발행결정\n\n"
        f"* 기업명: {corp}\n"
        f"* 발행금액: {amount}\n"
        f"* Coupon/YTM: {coupon_str}\n"
        f"* 이사회결의일: {board_date}\n"
        f"* 발행일: {issue_date}\n"
        f"* 만기일: {maturity_date}\n"
        f"* {type_label}가액: {conv_price}원\n"
        f"* 할증률: {premium_str}\n"
        f"* 주식총수 대비 비율: {conv_ratio}\n"
        f"* Put Option: {put_opt}\n"
        f"* Call Option: {call_opt}\n"
        f"* YTC: {ytc_str}\n"
        f"* Refixing: {refix_str}\n"
        f"* 인수인: {underwriter}\n"
        f"* 자금사용목적: {use}\n\n"
        f"🔗 {url}"
    )


def format_ri_message(item, detail, market):
    corp = item["corp_name"]
    rcept_no = item["rcept_no"]
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    
    if not detail:
        return None
    
    stock_type = safe_get(detail, "nstk_kndn", "nstk_knd")
    method = safe_get(detail, "ic_mthn", "nstk_asstd")
    
    public_keywords = ["주주배정", "일반공모", "실권주"]
    is_public = any(kw in method for kw in public_keywords)
    
    if is_preferred_stock(stock_type):
        return _format_ri_preferred(item, detail, market, corp, url, stock_type, method)
    if is_public:
        return _format_ri_public(item, detail, market, corp, url, stock_type, method)
    return None


def _format_ri_preferred(item, detail, market, corp, url, stock_type, method):
    """종류주 유상증자 (사모 메자닌)"""
    new_shares = fmt_num(safe_get(detail, "nstk_ostk_cnt", "nstk_cnt"))
    total_amount = fmt_amount(safe_get(detail, "fdpp_amount", "nstk_total_isstkamt"))
    capital_ratio = fmt_pct(safe_get(detail, "ratlst_isstkrt", "tisstk_rt"))
    conv_price = fmt_num(safe_get(detail, "nstk_isstk_pr", "nstk_iss_prc"))
    
    refix = safe_get(detail, "act_mktprcdv_lwlmt", "rfix_lwlmt")
    refix_str = f"{refix}%" if refix != "-" else "-"
    
    put_opt = safe_get(detail, "rpcmt_opt_ow_int_dts", "rpcmtad_pym")
    call_opt = safe_get(detail, "spcmt_opt_ow_int_dts", "spcmtad_pym")
    
    # YTC
    ytc = safe_get(detail, "spcmt_intr", "spcmt_intr_rt", "ytc")
    ytc_str = f"{ytc}%" if ytc != "-" else "-"
    
    purpose = safe_get(detail, "fdpp_fclt", "fdpp_op", "use_purps")
    board_date = fmt_date(safe_get(detail, "bddd"))
    pay_date = fmt_date(safe_get(detail, "pymd"))
    target = safe_get(detail, "thrd_pps_corp_nm", "thrd_pps_asstd", "atn_nm")
    
    return (
        f"✅[{market}] 유상증자 결정 ({method})\n\n"
        f"* 기업명: {corp}\n"
        f"* 신주의 종류: {stock_type}\n\n"
        f"* 발행금액: {total_amount}\n"
        f"* 이사회결의일: {board_date}\n"
        f"* 납입일: {pay_date}\n"
        f"* 신주 수: {new_shares}주 (증자비율 {capital_ratio})\n"
        f"* 전환가액: {conv_price}원\n"
        f"* Refixing: {refix_str}\n"
        f"* Put Option: {put_opt}\n"
        f"* Call Option: {call_opt}\n"
        f"* YTC: {ytc_str}\n"
        f"* 자금조달목적: {purpose}\n"
        f"* 배정 대상자: {target}\n\n"
        f"🔗 {url}"
    )


def _format_ri_public(item, detail, market, corp, url, stock_type, method):
    """공모 유상증자"""
    new_shares = fmt_num(safe_get(detail, "nstk_ostk_cnt", "nstk_cnt"))
    total_amount = fmt_amount(safe_get(detail, "fdpp_amount", "nstk_total_isstkamt"))
    capital_ratio = fmt_pct(safe_get(detail, "ratlst_isstkrt", "tisstk_rt"))
    issue_price = fmt_num(safe_get(detail, "nstk_isstk_pr", "nstk_iss_prc"))
    
    assign_per_share = safe_get(detail, "nstk_asstd_stkcnt", "ostk_asstd_cnt")
    
    board_date = fmt_date(safe_get(detail, "bddd"))
    pay_date = fmt_date(safe_get(detail, "pymd"))
    listing_date = fmt_date(safe_get(detail, "nstk_lstd_pd", "nstk_lstmsd"))
    
    osh_sub_start = fmt_date(safe_get(detail, "osh_sbd_st_dt", "exrgt_sbd_st_dt"))
    osh_sub_end = fmt_date(safe_get(detail, "osh_sbd_ed_dt", "exrgt_sbd_ed_dt"))
    osh_sub = f"{osh_sub_start}~{osh_sub_end}" if osh_sub_start != "-" else "-"
    
    gnrl_sub_start = fmt_date(safe_get(detail, "gnrl_sbd_st_dt", "fail_sbd_st_dt"))
    gnrl_sub_end = fmt_date(safe_get(detail, "gnrl_sbd_ed_dt", "fail_sbd_ed_dt"))
    gnrl_sub = f"{gnrl_sub_start}~{gnrl_sub_end}" if gnrl_sub_start != "-" else "-"
    
    underwriter = safe_get(detail, "rs_atn", "atn_nm", "und_nm")
    purpose = safe_get(detail, "fdpp_fclt", "fdpp_op", "use_purps")
    
    new_shares_str = f"{stock_type} {new_shares}주" if stock_type != "-" else f"{new_shares}주"
    
    return (
        f"✅[{market}] 유상증자 결정 (공모)\n\n"
        f"* 기업명: {corp}\n"
        f"* 증자방식: {method}\n"
        f"* 발행금액: {total_amount}\n"
        f"* 신주의 종류와 수: {new_shares_str} (증자비율 {capital_ratio})\n"
        f"* 1주당 신주배정주식수: {assign_per_share}\n"
        f"* 예정 발행가액: {issue_price}원\n"
        f"* 이사회결의일: {board_date}\n"
        f"* 구주주청약: {osh_sub}\n"
        f"* 일반공모청약: {gnrl_sub}\n"
        f"* 납입일: {pay_date}\n"
        f"* 신주상장예정일: {listing_date}\n"
        f"* 대표주관회사: {underwriter}\n"
        f"* 자금조달목적: {purpose}\n\n"
        f"🔗 {url}"
    )


def format_message(item):
    market = MARKET_MAP.get(item.get("corp_cls", ""), "기타")
    corp_code = item.get("corp_code", "")
    rcept_no = item.get("rcept_no", "")
    type_code = item["_type_code"]
    
    detail = fetch_detail(corp_code, rcept_no, type_code)
    
    if type_code == "RI":
        return format_ri_message(item, detail, market)
    else:
        return format_cb_message(item, detail, market)


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
