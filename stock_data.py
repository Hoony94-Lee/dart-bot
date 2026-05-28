"""
주식 가격 / 시가총액 조회 모듈 (다중 API fallback)
- 1차: NaverFinance API
- 2차: KRX 정보데이터시스템 (data.krx.co.kr)
- 3차: pykrx 라이브러리 (설치된 경우)
"""
import re
import json
import requests
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


# ============== DART API: corp_code → stock_code ==============
def get_stock_code(corp_code, dart_key):
    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/company.json",
            params={"crtfc_key": dart_key, "corp_code": corp_code},
            timeout=10,
        ).json()
        if res.get("status") == "000":
            stock_code = res.get("stock_code", "").strip()
            if stock_code and len(stock_code) == 6:
                return stock_code
    except Exception as e:
        print(f"종목코드 조회 실패 ({corp_code}): {e}")
    return None


# ============== 1차: NaverFinance ==============
def naver_fetch_close_price(stock_code, target_date):
    """NaverFinance 일별시세 API"""
    if not stock_code or not target_date or target_date == "-":
        return None
    try:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=10)
        
        url = "https://api.finance.naver.com/siseJson.naver"
        params = {
            "symbol": stock_code,
            "requestType": 1,
            "startTime": start_dt.strftime("%Y%m%d"),
            "endTime": target_dt.strftime("%Y%m%d"),
            "timeframe": "day",
        }
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        text = res.text.strip()
        text = re.sub(r"//.*", "", text)
        text = text.replace("'", '"')
        data = json.loads(text)
        
        if not data or len(data) < 2:
            return None
        
        target_yyyymmdd = int(target_dt.strftime("%Y%m%d"))
        best_row = None
        for row in data[1:]:
            if not row or len(row) < 5:
                continue
            row_date = int(row[0])
            if row_date <= target_yyyymmdd:
                if best_row is None or row_date > int(best_row[0]):
                    best_row = row
        
        if best_row:
            return int(best_row[4])
    except Exception as e:
        print(f"NaverFinance 종가 조회 실패 ({stock_code}): {e}")
    return None


def naver_fetch_market_data(stock_code):
    """NaverFinance 모바일 API: 시가총액, 상장주식수"""
    if not stock_code:
        return None
    try:
        url = f"https://m.stock.naver.com/api/stock/{stock_code}/basic"
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        
        mv = res.get("marketValue")
        shares = res.get("listedStockCnt")
        
        market_cap = None
        listed_shares = None
        
        if mv:
            try:
                mv_clean = str(mv).replace(",", "")
                market_cap = int(mv_clean) * 100000000
            except (ValueError, TypeError):
                pass
        
        if shares:
            try:
                listed_shares = int(str(shares).replace(",", ""))
            except (ValueError, TypeError):
                pass
        
        return {
            "market_cap": market_cap,
            "listed_shares": listed_shares,
        }
    except Exception as e:
        print(f"NaverFinance 시총 조회 실패 ({stock_code}): {e}")
    return None


# ============== 2차: KRX 정보데이터시스템 ==============
def krx_fetch_close_price(stock_code, target_date):
    """KRX 정보데이터시스템 - 일별시세
    
    target_date: "YYYY-MM-DD"
    """
    if not stock_code or not target_date or target_date == "-":
        return None
    try:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=10)
        
        # KRX 일별 시세 OTP 발급
        otp_url = "http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd"
        # 일별시세 검색: STK01001K1 (개별종목 시세 추이)
        otp_data = {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT01701",
            "tboxisuCd_finder_stkisu0_0": f"{stock_code}/종목명",
            "isuCd": f"KR7{stock_code}008",  # 약식 코드 (실제는 종목별 다름)
            "isuCd2": f"KR7{stock_code}008",
            "codeNmisuCd_finder_stkisu0_0": "종목명",
            "param1isuCd_finder_stkisu0_0": "ALL",
            "strtDd": start_dt.strftime("%Y%m%d"),
            "endDd": target_dt.strftime("%Y%m%d"),
            "share": "1",
            "money": "1",
            "csvxls_isNo": "false",
        }
        otp_res = requests.post(otp_url, data=otp_data, headers=HEADERS, timeout=10)
        otp_code = otp_res.text.strip()
        
        if not otp_code or len(otp_code) < 10:
            return None
        
        # 데이터 조회
        data_url = "http://data.krx.co.kr/comm/fileDn/download_csv/download.cmd"
        data_res = requests.post(
            data_url,
            data={"code": otp_code},
            headers=HEADERS,
            timeout=15,
        )
        
        # CSV 파싱
        lines = data_res.text.strip().split("\n")
        if len(lines) < 2:
            return None
        
        # 첫 줄은 헤더. 가장 최근 날짜의 종가 추출
        # 컬럼: 일자, 종가, 대비, 등락률, 시가, 고가, 저가, 거래량, ...
        for line in lines[1:]:
            cells = [c.strip().strip('"') for c in line.split(",")]
            if len(cells) >= 2 and cells[0]:
                try:
                    close = int(cells[1].replace(",", ""))
                    return close
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        print(f"KRX 종가 조회 실패 ({stock_code}): {e}")
    return None


# ============== 3차: pykrx (선택사항) ==============
def pykrx_fetch_data(stock_code, target_date):
    """pykrx 라이브러리 사용 (설치 필요: pip install pykrx)"""
    if not target_date or target_date == "-":
        return None
    try:
        from pykrx import stock
        
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=10)
        
        # 일별 OHLCV
        df = stock.get_market_ohlcv(
            start_dt.strftime("%Y%m%d"),
            target_dt.strftime("%Y%m%d"),
            stock_code,
        )
        if df.empty:
            return None
        
        # 가장 가까운 거래일
        last_row = df.iloc[-1]
        close = int(last_row["종가"])
        
        # 시가총액
        cap_df = stock.get_market_cap(
            target_dt.strftime("%Y%m%d"),
            target_dt.strftime("%Y%m%d"),
            stock_code,
        )
        market_cap = None
        listed_shares = None
        if not cap_df.empty:
            cap_row = cap_df.iloc[-1]
            market_cap = int(cap_row["시가총액"])
            listed_shares = int(cap_row["상장주식수"])
        
        return {
            "close_price": close,
            "market_cap": market_cap,
            "listed_shares": listed_shares,
        }
    except ImportError:
        return None
    except Exception as e:
        print(f"pykrx 조회 실패 ({stock_code}): {e}")
    return None


# ============== 통합 함수 ==============
def fetch_stock_price_and_mktcap(corp_code, price_ref_date, dart_key):
    """
    종가 + 시가총액 조회 (다중 API fallback)
    
    Returns:
        {
            "close_price": int or None,
            "market_cap": int or None,
            "listed_shares": int or None,
            "stock_code": str or None
        }
    """
    result = {
        "close_price": None,
        "market_cap": None,
        "listed_shares": None,
        "stock_code": None,
    }
    
    # 종목코드 조회
    stock_code = get_stock_code(corp_code, dart_key)
    if not stock_code:
        return result
    result["stock_code"] = stock_code
    
    # 1차: NaverFinance
    close_price = naver_fetch_close_price(stock_code, price_ref_date)
    market_data = naver_fetch_market_data(stock_code)
    
    if close_price:
        result["close_price"] = close_price
    if market_data:
        if market_data.get("market_cap"):
            result["market_cap"] = market_data["market_cap"]
        if market_data.get("listed_shares"):
            result["listed_shares"] = market_data["listed_shares"]
    
    # 2차 fallback: KRX (종가 누락 시)
    if not result["close_price"]:
        close_price = krx_fetch_close_price(stock_code, price_ref_date)
        if close_price:
            result["close_price"] = close_price
    
    # 3차 fallback: pykrx (KRX 마저 실패 시)
    if not result["close_price"] or not result["market_cap"]:
        pykrx_data = pykrx_fetch_data(stock_code, price_ref_date)
        if pykrx_data:
            if not result["close_price"] and pykrx_data.get("close_price"):
                result["close_price"] = pykrx_data["close_price"]
            if not result["market_cap"] and pykrx_data.get("market_cap"):
                result["market_cap"] = pykrx_data["market_cap"]
            if not result["listed_shares"] and pykrx_data.get("listed_shares"):
                result["listed_shares"] = pykrx_data["listed_shares"]
    
    # 시가총액이 비어있지만 종가와 상장주식수가 있으면 계산
    if not result["market_cap"] and result["close_price"] and result["listed_shares"]:
        result["market_cap"] = result["close_price"] * result["listed_shares"]
    
    return result


# ============== 포맷팅 ==============
def fmt_market_cap(value):
    """시가총액 → 억원 단위"""
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
    if not value or value in ("-", None):
        return "-"
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return "-"
