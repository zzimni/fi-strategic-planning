"""
scorer.py
핀인사이트 강점 기반 공고 적합도 점수화 모듈 (115점 만점)
"""

from datetime import datetime
import logging

from filters import parse_date

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 도메인 키워드 (도메인 적합도 판단용)
# ─────────────────────────────────────────────

_BIG_DATA_AI_KWS = [
    "빅데이터", "데이터분석", "데이터 분석", "BI", "대시보드", "시각화",
    "인공지능", "AI", "머신러닝", "딥러닝", "LLM", "NLP",
]
_BIG_DATA_KWS = [
    "빅데이터", "데이터분석", "데이터 분석", "BI", "대시보드",
    "시각화", "통계분석", "KOSIS", "공공데이터", "데이터 거버넌스",
]
_AI_KWS = [
    "인공지능", "AI", "머신러닝", "딥러닝", "LLM", "NLP",
    "챗봇", "자연어처리", "예측모델", "추천시스템", "컴퓨터비전",
]
_EDU_LITERACY_KWS = [
    "리터러시", "AID", "AI 교육", "AI교육", "데이터 리터러시",
    "디지털 역량", "디지털 인재", "디지털 전환 교육",
]
_EDU_TARGET_KWS = [
    "재직자", "청년", "취업준비생", "취준생", "대학생",
    "HRD", "신중년", "구직자", "양성과정",
]

# 전략적 가치
_FOLLOWUP_KWS   = ["플랫폼", "구축", "운영"]
_STRATEGY_KWS   = ["로드맵", "정책연구", "타당성", "기본계획", "활용전략"]
_REFERENCE_KWS  = ["레퍼런스", "우수사례", "시범", "파일럿"]
_SIMILAR_KWS    = ["부산", "파주", "광주", "인천", "대전"]  # 핀인사이트 동종 사업 지역

# 고가치 발주기관
_HIGH_VALUE_ORGS = [
    "조달청", "한국데이터산업진흥원", "한국지능정보사회진흥원", "정보통신산업진흥원",
    "한국과학기술원", "연구원", "진흥원", "과학기술정보통신부", "행정안전부",
    "고용노동부", "교육부",
]
_PUBLIC_ORGS = ["청", "처", "부", "원", "공단", "공사", "재단", "센터", "시청", "군청", "구청"]


# ─────────────────────────────────────────────
# 점수 계산
# ─────────────────────────────────────────────

def score_bid(bid: dict, today: datetime = None) -> dict:
    """
    공고 하나의 적합도 점수를 계산하고 점수 내역을 반환.

    Returns:
        {
            'total': int,          # 총점 (0~115)
            'grade': str,          # S/A/B/C
            'breakdown': dict,     # 항목별 점수
            'reasons': list[str],  # 점수 근거 (상위 3개)
        }
    """
    if today is None:
        today = datetime.now()

    title    = bid.get("bidNtceNm", "")
    org      = bid.get("ntceInsttNm", "") + bid.get("dmndInsttNm", "")
    close_dt = parse_date(bid.get("bidClseDt", ""))
    matched  = bid.get("_matched_codes", [])
    budget_raw = bid.get("presmptPrce", bid.get("asignBdgtAmt", "0"))

    breakdown: dict[str, int] = {}
    reasons: list[str] = []

    # ── 4-1. 도메인 적합도 (최대 50점) ──────────────
    has_bigdata = any(k in title for k in _BIG_DATA_KWS)
    has_ai      = any(k in title for k in _AI_KWS)

    if has_bigdata and has_ai:
        d_score = 50
        reasons.append("빅데이터+AI 동시 매칭")
    elif has_bigdata:
        d_score = 45
        reasons.append("빅데이터·데이터분석 직접 매칭")
    elif has_ai:
        d_score = 45
        reasons.append("AI 응용 사업 직접 매칭")
    elif any(k in title for k in _BIG_DATA_AI_KWS):
        d_score = 30
        reasons.append("관련 키워드 부분 매칭")
    elif any(k in title for k in ["교육", "양성", "연수", "부트캠프", "HRD"]):
        d_score = 20
        reasons.append("교육 일반 매칭")
    else:
        d_score = 10
    breakdown["domain"] = d_score

    # ── 4-2. 교육 특화 가산 (최대 +15) ──────────────
    edu_score = 0
    has_literacy = any(k in title for k in _EDU_LITERACY_KWS)
    has_target   = any(k in title for k in _EDU_TARGET_KWS)

    if has_literacy and has_target:
        edu_score = 15
        reasons.append("AI·데이터 리터러시 교육 + 재직자/청년 대상")
    elif has_literacy:
        edu_score = 5
        reasons.append("AI·데이터 리터러시 교육 키워드")
    elif has_target:
        edu_score = 10
        reasons.append("재직자·청년·HRD 대상 교육")
    breakdown["education_bonus"] = edu_score

    # ── 4-3. 등록업종 매칭 가산 (최대 +30) ──────────
    n_codes = len([c for c in matched if c != "9999"])
    if n_codes >= 3:
        code_score = 30
        reasons.append(f"등록업종 {n_codes}개 복합 매칭")
    elif n_codes == 2:
        code_score = 20
        reasons.append(f"등록업종 2개 매칭")
    elif n_codes == 1:
        code_score = 10
    elif "9999" in matched:
        code_score = 5   # 기타자유업종만
    else:
        code_score = 0
    breakdown["code_bonus"] = code_score

    # ── 4-4. 실행 가능성 (최대 20점) ─────────────────
    exec_score = 0

    # 마감 여유
    if close_dt:
        days_left = (close_dt - today).days
        if days_left >= 14:
            exec_score += 15
        elif days_left >= 7:
            exec_score += 8
        else:
            exec_score += 3

    # 발주기관 가치
    if any(k in org for k in _HIGH_VALUE_ORGS):
        exec_score += 15
        reasons.append(f"고가치 발주기관: {bid.get('ntceInsttNm','')}")
    elif any(k in org for k in _PUBLIC_ORGS):
        exec_score += 8

    # 20점 cap
    exec_score = min(exec_score, 20)
    breakdown["execution"] = exec_score

    # ── 4-5. 전략적 가치 (최대 20점) ─────────────────
    strat_score = 0

    if any(k in title for k in _FOLLOWUP_KWS):
        strat_score += 10
    if any(k in title for k in _STRATEGY_KWS):
        strat_score += 7
        reasons.append("전략→후속 연결 가능 (로드맵/정책연구)")
    if any(k in title for k in _REFERENCE_KWS):
        strat_score += 5
    if any(k in title for k in _SIMILAR_KWS):
        strat_score += 5

    # 예산 적정성 (3천만~5억)
    try:
        budget = float(str(budget_raw).replace(",", "").replace(" ", "") or "0")
        if 30_000_000 <= budget <= 500_000_000:
            strat_score += 5
            reasons.append("예산 적정 (3천만~5억)")
    except (ValueError, TypeError):
        pass

    strat_score = min(strat_score, 20)
    breakdown["strategy"] = strat_score

    # ── 총점 & 등급 ──────────────────────────────────
    total = (breakdown["domain"]
             + breakdown["education_bonus"]
             + breakdown["code_bonus"]
             + breakdown["execution"]
             + breakdown["strategy"])

    if total >= 85:
        grade = "S"
    elif total >= 70:
        grade = "A"
    elif total >= 55:
        grade = "B"
    else:
        grade = "C"

    return {
        "total":     total,
        "grade":     grade,
        "breakdown": breakdown,
        "reasons":   reasons[:3],   # 상위 3개만
    }


def score_all(bids: list[dict], today: datetime = None) -> list[dict]:
    """
    공고 목록 전체 점수화 후 점수 내림차순 정렬.
    각 bid에 '_score', '_grade', '_reasons' 필드 추가.
    """
    if today is None:
        today = datetime.now()

    for bid in bids:
        result = score_bid(bid, today)
        bid["_score"]     = result["total"]
        bid["_grade"]     = result["grade"]
        bid["_reasons"]   = result["reasons"]
        bid["_breakdown"] = result["breakdown"]

    bids.sort(key=lambda b: b["_score"], reverse=True)
    return bids
