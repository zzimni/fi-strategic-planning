"""
filters.py
공고 하드 필터 + 핀인사이트 등록업종 자격 매칭 모듈
"""

from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 핀인사이트 등록업종 코드
# ─────────────────────────────────────────────

PININSIGHT_CODES: set[str] = {"1468", "1469", "1470", "1169", "9999"}

CODE_NAMES = {
    "1468": "SW(컴퓨터관련서비스)",
    "1469": "SW(디지털콘텐츠)",
    "1470": "SW(DB제작/검색)",
    "1169": "학술연구용역",
    "9999": "기타자유업종",
}


# ─────────────────────────────────────────────
# 날짜 파싱 유틸
# ─────────────────────────────────────────────

_DATE_FORMATS = [
    "%Y%m%d%H%M",      # 202605221000
    "%Y%m%d%H%M%S",    # 20260522100000
    "%Y/%m/%d %H:%M",  # 2026/05/22 10:00
    "%Y-%m-%d %H:%M",  # 2026-05-22 10:00
    "%Y%m%d",          # 20260522
]


def parse_date(raw: str) -> datetime | None:
    if not raw or raw.strip() in ("-", ""):
        return None
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw[: len(fmt.replace("%Y", "XXXX")
                                                .replace("%m", "XX")
                                                .replace("%d", "XX")
                                                .replace("%H", "XX")
                                                .replace("%M", "XX")
                                                .replace("%S", "XX"))],
                                     fmt)
        except ValueError:
            pass
    # 마지막 시도: 앞 8자리만
    try:
        return datetime.strptime(raw[:8], "%Y%m%d")
    except Exception:
        return None


# ─────────────────────────────────────────────
# Hard Filter
# ─────────────────────────────────────────────

# 수의계약 키워드
_SUUUI_KEYWORDS = ["수의시담", "수의계약", "소액수의"]
# 공사 키워드
_CONSTWK_KEYWORDS = ["공사"]


def hard_filter(bid: dict, today: datetime = None,
                close_min_days: int = 0,
                close_max_days: int = 60) -> tuple[bool, str]:
    """
    공고 하드 필터.
    Returns:
        (True, "")         → 통과
        (False, "사유")    → 제외
    """
    if today is None:
        today = datetime.now()

    # 1. 마감일 파싱
    close_dt = parse_date(bid.get("bidClseDt", ""))
    if close_dt is None:
        return False, "마감일 미정"

    days_left = (close_dt - today).days
    if days_left < 0:
        return False, "이미 마감"
    if days_left < close_min_days:
        return False, f"마감 임박 (D-{days_left})"
    if days_left > close_max_days:
        return False, f"마감 원거리 (D-{days_left})"

    # 2. 수의계약 제외
    bid_mthd = bid.get("bidMthdNm", "")
    if any(k in bid_mthd for k in _SUUUI_KEYWORDS):
        return False, "수의계약"

    # 3. 공사 제외
    ntce_kind = bid.get("ntceKindNm", "")
    if any(k in ntce_kind for k in _CONSTWK_KEYWORDS):
        return False, "공사 (시공자격 없음)"

    return True, ""


# ─────────────────────────────────────────────
# 자격 매칭
# ─────────────────────────────────────────────

# 각 업종 코드별 추정 키워드
_CODE_KEYWORDS: dict[str, list[str]] = {
    "1468": [  # SW(컴퓨터관련서비스) — 시스템 구축·운영
        "시스템 구축", "시스템구축", "플랫폼 구축", "플랫폼구축",
        "시스템 운영", "시스템 개발", "소프트웨어 개발",
        "솔루션 구축", "서비스 구축", "통합 시스템", "관리 시스템",
        "플랫폼 운영", "시스템 유지보수", "시스템 고도화",
        "플랫폼 개발", "앱 개발", "앱개발", "웹 개발",
    ],
    "1469": [  # SW(디지털콘텐츠) — AI·챗봇·교육콘텐츠
        "AI기반", "AI 기반", "인공지능", "챗봇", "LLM", "머신러닝", "딥러닝",
        "디지털콘텐츠", "디지털 콘텐츠", "교육 콘텐츠", "콘텐츠 개발",
        "학습 콘텐츠", "AID", "AI활용", "에듀테크",
        "교육용 소프트웨어", "대화형 서비스", "추천 서비스",
        "자연어처리", "NLP", "음성인식", "컴퓨터비전",
    ],
    "1470": [  # SW(DB제작/검색) — 데이터 분석·DB구축
        "DB구축", "DB 구축", "데이터베이스", "database",
        "데이터 분석", "데이터분석", "빅데이터", "BI", "시각화",
        "데이터 처리", "데이터 시각화", "대시보드", "통계분석",
        "데이터 표준화", "데이터 정리", "데이터 품질",
        "검색 서비스", "검색시스템", "KOSIS", "공공데이터",
    ],
    "1169": [  # 학술연구용역 — 정책연구·R&D·로드맵
        "정책연구", "정책 연구", "연구용역", "연구 용역",
        "타당성 검토", "타당성검토", "타당성",
        "로드맵 수립", "로드맵", "전략 수립", "활용전략", "활용 전략",
        "교육평가", "교육 평가", "실태조사", "실태 조사",
        "학술 연구", "정책 분석", "효과성 분석", "성과 평가",
        "사회과학", "컨설팅", "기본계획",
    ],
}

# 자격 미해당 추가 판단 키워드
_DISQUALIFY_LICENSE_KEYWORDS = [
    "라이센스 구매", "라이선스 구매", "라이센스 임대",
    "라이선스 임대", "라이선스 연간 사용권",
]
_DISQUALIFY_EVENT_KEYWORDS = [
    "환경교육주간 행사", "국제교류", "주간 행사",
    "체험 사업 위탁", "예비 산림",
]
_DISQUALIFY_GOODS_KEYWORDS = [
    "라이센스 구매", "라이선스 구매", "ODTK",
    "서버 구매", "소프트웨어 라이선스",
]


def check_qualification(bid: dict) -> tuple[list[str], str]:
    """
    핀인사이트 등록업종 자격 매칭.

    Returns:
        matched_codes : 매칭된 코드 목록 (예: ['1469', '1470'])
        source        : '검색조건(API)' | '명시(API)' | '추정(사업내용)' | '자격제한없음'
    """
    searched_codes: list[str] = bid.get("_matched_codes", [])
    if searched_codes:
        matched = [c for c in searched_codes if c in PININSIGHT_CODES]
        if matched:
            return matched, "검색조건(API)"

    license_codes: list[str] = bid.get("_license_codes", [])

    # 1순위: API로 가져온 명시적 코드
    if license_codes:
        matched = [c for c in license_codes if c in PININSIGHT_CODES]
        return matched, "명시(API)"

    # 2순위: 면허제한 코드 없음 → 자격제한 없음 (9999 적용)
    if bid.get("_license_source") == "API(getLicenseInfoServc)":
        # API를 호출했는데 빈 리스트 → 실제로 면허제한 없음
        return ["9999"], "자격제한없음"

    # 3순위: API 호출 안 됨 → 공고명 기반 추정
    title = bid.get("bidNtceNm", "")
    matched = []
    for code, kws in _CODE_KEYWORDS.items():
        if any(k in title for k in kws):
            matched.append(code)

    return matched, "추정(사업내용)"


def is_disqualified(bid: dict, matched_codes: list[str],
                    license_source: str) -> list[str]:
    """
    자격 미해당 사유 목록 반환.
    빈 리스트 = 통과.
    """
    reasons = []
    title    = bid.get("bidNtceNm", "")
    biz_type = bid.get("ntceKindNm", "")

    # 공사
    if "공사" in biz_type:
        reasons.append("업무구분 공사 (시공자격 없음)")
        return reasons  # 공사면 더 볼 필요 없음

    # 명시적 코드 있는데 매칭 0개
    explicit_codes = bid.get("_license_codes", [])
    if explicit_codes and not matched_codes:
        reasons.append(f"면허제한 불일치 (요구: {','.join(explicit_codes)})")

    # 추정도 0개
    if not explicit_codes and license_source == "추정(사업내용)" and not matched_codes:
        reasons.append("등록업종 매칭 없음")

    # 단순 라이선스 구매/임대
    if any(k in title for k in _DISQUALIFY_LICENSE_KEYWORDS):
        if "구축" not in title and "개발" not in title:
            reasons.append("단순 라이선스 유통")

    # 단순 행사·기획
    if any(k in title for k in _DISQUALIFY_EVENT_KEYWORDS):
        reasons.append("단순 행사·기획 (강점 영역 아님)")

    # 물품 구매·유통
    if "물품" in biz_type:
        if any(k in title for k in _DISQUALIFY_GOODS_KEYWORDS):
            reasons.append("물품 구매·유통")

    return reasons


def apply_qualification_filter(bids: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    자격 필터 적용.

    Returns:
        qualified   : 자격 통과 공고 (matched_codes + source 필드 추가됨)
        disqualified: 자격 미해당 공고 (disqualify_reasons 필드 추가됨)
    """
    qualified   = []
    disqualified = []

    for bid in bids:
        matched_codes, source = check_qualification(bid)
        bid["_matched_codes"] = matched_codes
        bid["_license_source_label"] = source

        reasons = is_disqualified(bid, matched_codes, source)

        if reasons:
            bid["_disqualify_reasons"] = reasons
            disqualified.append(bid)
        else:
            qualified.append(bid)

    return qualified, disqualified
