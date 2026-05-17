import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DART_KEY = os.environ["DART_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# 관심 공시 키워드 (제목에 포함되면 발송)
KEYWORDS = [
    "유상증자결정",
    "무상증자결정",
    "전환사채권발행결정",
    "신주인수권부사채권발행결정",
    "교환사채권발행결정",
    "회사합병결정",
    "회사분할결정",
    "주식교환",
    "감자결정",
    "주요사항보고서",
]

EXCLUDE = ["철회"]
SENT_FILE = "sent.json"


def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE) as f:
            return set(json.load(f))
    return set()


def save_sent(sent):
    with open(SENT_FILE, "w") as f:
        json.dump(list(sent)[-1000:], f)


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
            print(f"DART API status: {res.get('status')}, message: {res.get('message')}")
            break
        items = res.get("list", [])
        if not items:
            break
        all_items.extend(items)
        if len(items) < 100:
            break
    return all_items


def filter_items(items, sent):
    result = []
    for item in items:
        title = item.get("report_nm", "")
        rcept_no = item.get("rcept_no", "")
        
        if rcept_no in sent:
            continue
        if any(ex in title for ex in EXCLUDE):
            continue
        if not any(kw in title for kw in KEYWORDS):
            continue
        result.append(item)
    return result


def format_message(item):
    title = item["report_nm"].strip()
    corp = item["corp_name"]
    market = item.get("corp_cls", "")
    market_map = {"Y": "🔵코스피", "K": "🟢코스닥", "N": "🟡코넥스", "E": "⚪기타"}
    market_str = market_map.get(market, "")
    
    rcept_dt = item.get("rcept_dt", "")
    rcept_no = item["rcept_no"]
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    
    return (
        f"{market_str} {corp}\n"
        f"📌 {title}\n"
        f"🕐 {rcept_dt}\n"
        f"🔗 {url}"
    )


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


def main():
    sent = load_sent()
    items = fetch_disclosures()
    new_items = filter_items(items, sent)
    
    print(f"전체 공시: {len(items)}건, 신규 매칭: {len(new_items)}건")
    
    new_items.sort(key=lambda x: x.get("rcept_dt", "") + x.get("rcept_no", ""))
    
    for item in new_items:
        msg = format_message(item)
        send_telegram(msg)
        sent.add(item["rcept_no"])
    
    save_sent(sent)
    print("완료")


if __name__ == "__main__":
    main()
