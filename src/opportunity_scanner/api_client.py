"""
api_client.py
조달청 나라장터 입찰공고정보서비스 호출 모듈

API (15129394): 나라장터 입찰공고정보서비스
  - getBidPblancListInfoServcPPSSrch : 용역 목록 (검색조건)
  - getBidPblancListInfoThngPPSSrch  : 물품 목록 (검색조건)
  - getBidPblancListInfoServcDetail : 용역 상세
"""

import os
import time
import logging
import concurrent.futures
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────

API_KEY = os.environ.get("G2B_API_KEY", "")

BID_API_BASE = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService"
LICENSE_API_ENABLED = os.environ.get("G2B_LICENSE_API_ENABLED", "").lower() in {"1", "true", "yes"}

DEFAULT_TIMEOUT = 30
RETRY_COUNT     = 3
RETRY_DELAY     = 2   # seconds
MAX_QUERY_DAYS  = 30  # API가 긴 조회기간에 resultCode=07을 반환하므로 분할 조회
PININSIGHT_CODES = ("1468", "1469", "1470", "1169", "9999")


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def _get(url: str, params: dict, timeout: int = DEFAULT_TIMEOUT) -> dict | None:
    """재시도 포함 GET 요청. 실패 시 None 반환."""
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

            # 공공API 에러코드 체크
            header = data.get("response", {}).get("header")
            if header is None:
                header = data.get("nkoneps.com.response.ResponseError", {}).get("header", {})
            result_code = header.get("resultCode", "00")
            if result_code not in ("00", "0000"):
                result_msg = header.get("resultMsg", "")
                logger.warning("API 오류 코드 %s: %s | URL: %s", result_code, result_msg, url)
                return None

            return data
        except requests.exceptions.Timeout:
            logger.warning("[%d/%d] 타임아웃: %s", attempt, RETRY_COUNT, url)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status in (401, 403):
                logger.warning("API 인증/승인 오류 %s: %s", status, url)
                return None
            logger.warning("[%d/%d] HTTP 오류 %s: %s", attempt, RETRY_COUNT, status, url)
        except Exception as e:
            logger.warning("[%d/%d] 예외: %s | %s", attempt, RETRY_COUNT, e, url)

        if attempt < RETRY_COUNT:
            time.sleep(RETRY_DELAY * attempt)

    return None


def _extract_items(data: dict) -> list[dict]:
    """응답에서 items 추출. 단건이면 리스트로 감쌈."""
    if not data:
        return []
    items = data.get("response", {}).get("body", {}).get("items", None)
    if items is None:
        return []
    if isinstance(items, dict) and "item" in items:
        item = items["item"]
        if isinstance(item, list):
            return item
        if isinstance(item, dict):
            return [item]
        return []
    if isinstance(items, dict):
        return [items]
    if isinstance(items, list):
        return items
    return []


# ─────────────────────────────────────────────
# API 1: 입찰공고정보서비스 (15129394)
# ─────────────────────────────────────────────

def _fetch_bid_list(endpoint: str, keyword: str,
                    start_dt: datetime, end_dt: datetime,
                    page_no: int = 1, num_rows: int = 100,
                    industry_code: str | None = None) -> list[dict]:
    """용역/물품 공고 목록 조회 공통 함수."""
    url = f"{BID_API_BASE}/{endpoint}"
    params = {
        "serviceKey": API_KEY,
        "pageNo":     page_no,
        "numOfRows":  num_rows,
        "inqryDiv":   1,   # 1: 공고일시 기준
        "inqryBgnDt": start_dt.strftime("%Y%m%d") + "0000",
        "inqryEndDt": end_dt.strftime("%Y%m%d")   + "2359",
        "bidNtceNm":  keyword,
        "type":       "json",
    }
    if industry_code:
        params["indstrytyCd"] = industry_code
    data = _get(url, params)
    return _extract_items(data)


def fetch_bids_servc(keyword: str, start_dt: datetime, end_dt: datetime,
                     page_no: int = 1, num_rows: int = 100,
                     industry_code: str | None = None) -> list[dict]:
    """용역 입찰공고 목록 조회."""
    return _fetch_bid_list("getBidPblancListInfoServcPPSSrch", keyword, start_dt, end_dt,
                           page_no, num_rows, industry_code=industry_code)


def fetch_bids_thng(keyword: str, start_dt: datetime, end_dt: datetime,
                    page_no: int = 1, num_rows: int = 100,
                    industry_code: str | None = None) -> list[dict]:
    """물품 입찰공고 목록 조회."""
    return _fetch_bid_list("getBidPblancListInfoThngPPSSrch", keyword, start_dt, end_dt,
                           page_no, num_rows, industry_code=industry_code)


def _date_chunks(start_dt: datetime, end_dt: datetime, days: int = MAX_QUERY_DAYS):
    cur = start_dt
    while cur <= end_dt:
        chunk_end = min(cur + timedelta(days=days - 1), end_dt)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def fetch_all_pages(fetch_fn, keyword: str,
                    start_dt: datetime, end_dt: datetime,
                    num_rows: int = 100,
                    industry_code: str | None = None) -> list[dict]:
    """페이지네이션 자동 처리 — 전체 결과 수집."""
    all_items = []
    for chunk_start, chunk_end in _date_chunks(start_dt, end_dt):
        page_no = 1
        while True:
            items = fetch_fn(keyword, chunk_start, chunk_end, page_no=page_no,
                             num_rows=num_rows, industry_code=industry_code)
            if not items:
                break
            all_items.extend(items)
            if len(items) < num_rows:
                break   # 마지막 페이지
            page_no += 1
            time.sleep(0.3)  # 과부하 방지
    return all_items


def fetch_license_info(bid_ntce_no: str, bid_ntce_ord: str = "00") -> list[str] | None:
    """
    면허제한정보 조회 → 요구 자격 코드 목록 반환.
    예: ['1468', '1469']
    빈 리스트 = 면허제한 없음
    None = API 비활성/실패로 확인 불가
    """
    if not LICENSE_API_ENABLED:
        return None

    url = f"{BID_API_BASE}/getLicenseInfoServc"
    params = {
        "serviceKey": API_KEY,
        "bidNtceNo":  bid_ntce_no,
        "bidNtceOrd": bid_ntce_ord,
        "type":       "json",
    }
    data = _get(url, params, timeout=15)
    if data is None:
        return None
    items = _extract_items(data)
    codes = []
    for item in items:
        code = item.get("lcnsLmtCd", "").strip()
        if code:
            codes.append(code)
    return codes


def fetch_bid_detail_servc(bid_ntce_no: str, bid_ntce_ord: str = "00") -> dict:
    """용역 공고 상세 조회 (추정가격, 낙찰방법 등 보완용)."""
    url = f"{BID_API_BASE}/getBidPblancListInfoServcDetail"
    params = {
        "serviceKey": API_KEY,
        "bidNtceNo":  bid_ntce_no,
        "bidNtceOrd": bid_ntce_ord,
        "type":       "json",
    }
    data = _get(url, params, timeout=15)
    items = _extract_items(data)
    return items[0] if items else {}


def enrich_license_info(bids: list[dict], max_workers: int = 10) -> list[dict]:
    """공고 목록에 면허제한 코드 정보를 추가한다."""
    if not bids or not LICENSE_API_ENABLED:
        return bids

    def _get_license(idx_bid: tuple[int, dict]) -> tuple[int, list[str]]:
        idx, bid = idx_bid
        codes = fetch_license_info(bid.get("bidNtceNo", ""), bid.get("bidNtceOrd", "00"))
        return idx, codes

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_get_license, (idx, bid)): idx
            for idx, bid in enumerate(bids)
        }
        for f in concurrent.futures.as_completed(futures):
            idx, codes = f.result()
            if codes is not None:
                bids[idx]["_license_codes"] = codes
                bids[idx]["_license_source"] = "API(getLicenseInfoServc)"

    return bids


# ─────────────────────────────────────────────
# 필드 정규화
# ─────────────────────────────────────────────

def normalize_bid(raw: dict) -> dict:
    """입찰공고정보서비스 응답을 통일된 포맷으로 변환."""
    bid_ntce_no  = raw.get("bidNtceNo", "")
    bid_ntce_ord = raw.get("bidNtceOrd", "00")
    return {
        "_source":        "15129394",
        "bidNtceNo":      bid_ntce_no,
        "bidNtceOrd":     bid_ntce_ord,
        "bidNtceFullNo":  f"{bid_ntce_no}-{bid_ntce_ord}",
        "bidNtceNm":      raw.get("bidNtceNm", "").strip(),
        "ntceInsttNm":    raw.get("ntceInsttNm", "").strip(),   # 공고기관
        "dmndInsttNm":    raw.get("dmndInsttNm", raw.get("dminsttNm", "")).strip(),  # 수요기관
        "bidMthdNm":      raw.get("bidMthdNm",
                                  raw.get("bidMethdNm",
                                          raw.get("cntrctCnclsMthdNm", ""))).strip(),
        "ntceKindNm":     raw.get("ntceKindNm", "").strip(),    # 업무구분
        "bidClseDt":      raw.get("bidClseDt", "").strip(),     # 마감일시
        "bidNtceDt":      raw.get("bidNtceDt", "").strip(),     # 공고일시
        "presmptPrce":    raw.get("presmptPrce", "").strip(),   # 추정가격
        "asignBdgtAmt":   raw.get("asignBdgtAmt", "").strip(),  # 배정예산
        "indstrytyLmtYn": raw.get("indstrytyLmtYn", "").strip(), # 업종제한 여부
        "_matched_codes": [],
        "_license_codes": [],   # 면허제한 코드 (별도 API 조회 후 채움)
        "_license_source": "",
    }


# ─────────────────────────────────────────────
# 통합 수집
# ─────────────────────────────────────────────

def collect_all_bids(keywords: list[str],
                     start_dt: datetime,
                     end_dt: datetime,
                     fetch_license: bool = False) -> dict[str, list[dict]]:
    """
    모든 키워드에 대해 용역/물품 공고를 병렬 호출하여 수집.

    반환:
        {keyword: [normalized_bid_dict, ...]}
    """
    if not API_KEY:
        raise ValueError("G2B_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

    results: dict[str, list[dict]] = {}

    def _collect_keyword(kw: str) -> tuple[str, list[dict]]:
        logger.info("  키워드 수집 중: '%s'", kw)

        merged: dict[str, dict] = {}
        servc_count = 0
        thng_count = 0

        def _merge_items(items: list[dict], matched_code: str | None = None):
            for item in items:
                bid = normalize_bid(item)
                key = bid["bidNtceNo"]
                if not key:
                    continue
                if key not in merged:
                    merged[key] = bid
                if matched_code and matched_code not in merged[key]["_matched_codes"]:
                    merged[key]["_matched_codes"].append(matched_code)
                    merged[key]["_license_source"] = "검색조건(indstrytyCd)"

        # 핀인사이트 등록업종 코드로 선필터링한다.
        for code in PININSIGHT_CODES:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                f_servc = ex.submit(fetch_all_pages, fetch_bids_servc, kw, start_dt, end_dt,
                                    industry_code=code)
                f_thng = ex.submit(fetch_all_pages, fetch_bids_thng, kw, start_dt, end_dt,
                                   industry_code=code)
                servc_items = f_servc.result()
                thng_items = f_thng.result()

            servc_count += len(servc_items)
            thng_count += len(thng_items)
            _merge_items(servc_items + thng_items, matched_code=code)

        # 업종제한 없는 일반 공고는 indstrytyCd 검색에 잡히지 않을 수 있어 보완 수집한다.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_servc = ex.submit(fetch_all_pages, fetch_bids_servc, kw, start_dt, end_dt)
            f_thng = ex.submit(fetch_all_pages, fetch_bids_thng, kw, start_dt, end_dt)
            servc_items = f_servc.result()
            thng_items = f_thng.result()

        general_items = [
            item for item in servc_items + thng_items
            if item.get("indstrytyLmtYn") == "N"
        ]
        servc_count += len(servc_items)
        thng_count += len(thng_items)
        _merge_items(general_items, matched_code="9999")

        if fetch_license:
            enrich_license_info(list(merged.values()))

        logger.info("    → %d건 수집 완료 (용역:%d 물품:%d 합산중복제거→%d)",
                    len(merged), servc_count, thng_count, len(merged))

        return kw, list(merged.values())

    # 키워드별 병렬 수집
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(keywords), 4)) as ex:
        futures = {ex.submit(_collect_keyword, kw): kw for kw in keywords}
        for f in concurrent.futures.as_completed(futures):
            kw, items = f.result()
            results[kw] = items

    return results
