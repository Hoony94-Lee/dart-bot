"""
주식 가격 및 시가총액 조회 모듈
- NaverFinance Mobile API 활용 (User-Agent 필요)
- DART corp_code → 종목코드 매핑
"""
import os
import re
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# DART API에서 종목코드 조회
def get_stock_code(corp_code, dart_key):
    """DART corp_code로 6자리 종목코드 조회"""
    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/company.json",
            params={
                "crtfc_key": dart_key,
                "corp_code": corp_code,
            },
            timeout=10,
        ).json()
        if res.get("status") == "000":
            stock_code = res.get("stock_code", "").strip()
            if stock_code and len(stock_code) == 6:
                return stock_code
    except Exception as e:
        print(f"종목코드 조회 실패 ({corp_code}): {e}")
    return None


def fetch_close_price(stock_code, target_date_str):
    """
    NaverFinance에서 특정 일자 종가 조회
    target_date_str: "YYYY-MM-DD"
    Returns: int (종가) or None
    """
    if not stock_code or not target_date_str or target_date_str == "-":
        return None
    
    try:
        # 조회 기간: target_date 기준 ±10일 (휴장일 대응)
        target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=10)
        end_dt = target_dt
        
        url = "https://api.finance.naver.com/siseJson.naver"
        params = {
            "symbol": stock_code,
            "requestType": 1,
            "startTime": start_dt.strftime("%Y%m%d"),
            "endTime": end_dt.strftime("%Y%m%d"),
            "timeframe": "day",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, params=params, headers=headers, timeout=10)
        
        # 응답 형식: [['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'], [20260520, ...], ...]
        text = res.text.strip()
        # JSON이 아닌 JS 객체 형식이라 정리 필요
        text = re.sub(r"//.*", "", text)  # 주석 제거
        text = text.replace("'", '"')
        
        import json
        data = json.loads(text)
        
        if not data or len(data) < 2:
            return None
        
        # 가장 가까운 거래일의 종가 추출 (target_date 이하)
        target_yyyymmdd = int(target_dt.strftime("%Y%m%d"))
        best_row = None
        for row in data[1:]:  # 첫 행은 헤더
            if not row or len(row) < 5:
                continue
            row_date = int(row[0])
            if row_date <= target_yyyymmdd:
                if best_row is None or row_date > int(best_row[0]):
                    best_row = row
        
        if best_row:
            return int(best_row[4])  # 종가
    except Exception as e:
        print(f"종가 조회 실패 ({stock_code}, {target_date_str}): {e}")
    
    return None


def fetch_market_cap(stock_code, target_date_str=None):
    """
    NaverFinance 모바일 API로 시가총액 조회
    Returns: int (시가총액, 원 단위) or None
    
    주의: 모바일 API는 실시간 데이터만 제공.
    과거 시점 시가총액은 종가 × 상장주식수로 계산.
    """
    if not stock_code:
        return None
    
    try:
        url = f"https://m.stock.naver.com/api/stock/{stock_code}/basic"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10).json()
        
        # marketValue: 시가총액 (단위: 억원, 문자열)
        # marketValueKor: "514억원" 같은 한글 표기
        mv = res.get("marketValue")
        if mv:
            # 쉼표 제거 후 숫자 변환
            mv_clean = str(mv).replace(",", "")
            return int(mv_clean) * 100000000  # 억원 → 원
    except Exception as e:
        print(f"시가총액 조회 실패 ({stock_code}): {e}")
    
    return None


def fetch_listed_shares(stock_code):
    """상장주식수 조회"""
    if not stock_code:
        return None
    
    try:
        url = f"https://m.stock.naver.com/api/stock/{stock_code}/basic"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10).json()
        
        # listedStockCnt: 상장주식수
        shares = res.get("listedStockCnt")
        if shares:
            return int(str(shares).replace(",", ""))
    except Exception as e:
        print(f"상장주식수 조회 실패 ({stock_code}): {e}")
    
    return None


def fetch_stock_price_and_mktcap(corp_code, price_ref_date, dart_key):
    """
    종가와 시가총액을 함께 조회
    
    Args:
        corp_code: DART 기업코드 (8자리)
        price_ref_date: 종가 기준일 "YYYY-MM-DD"
        dart_key: DART API key
    
    Returns:
        {
            "close_price": int or None,
            "market_cap": int or None,  # 원 단위
            "stock_code": str or None
        }
    """
    result = {
        "close_price": None,
        "market_cap": None,
        "stock_code": None
    }
    
    # 1. 종목코드 조회
    stock_code = get_stock_code(corp_code, dart_key)
    if not stock_code:
        return result
    result["stock_code"] = stock_code
    
    # 2. 종가 조회 (기준일 종가)
    close_price = fetch_close_price(stock_code, price_ref_date)
    result["close_price"] = close_price
    
    # 3. 시가총액 = 종가 × 상장주식수 (기준일 시점)
    if close_price:
        shares = fetch_listed_shares(stock_code)
        if shares:
            result["market_cap"] = close_price * shares
    
    return result


# 포맷팅 헬퍼
def fmt_market_cap(value):
    """시가총액을 억원 단위로 포맷"""
    if not value or value in ("-", None):
        return "-"
    try:
        v = int(value)
        uk = v / 100000000
        if uk >= 10000:
            return f"{uk/10000:,.1f}조"
        return f"{uk:,.0f}"
    except (ValueError, TypeError):
        return "-"


def fmt_close_price(value):
    """종가 포맷 (천단위 콤마)"""
    if not value or value in ("-", None):
        return "-"
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return "-"
