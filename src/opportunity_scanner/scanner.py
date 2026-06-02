"""
scanner.py
나라장터 공고 스캐너 — 메인 진입점

사용법:
    # 즉시 1회 실행
    python scanner.py

    # 주간 스케줄러 모드 (매주 월요일 09:00 자동 실행)
    python scanner.py --schedule

    # 특정 키워드·기간 지정
    python scanner.py --keywords AI 빅데이터 --days-min 7 --days-max 45

환경변수 (.env):
    G2B_API_KEY=공공데이터포털_서비스키
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 스케줄러
try:
    import schedule
    import time
    HAS_SCHEDULE = True
except ImportError:
    HAS_SCHEDULE = False

from dotenv import load_dotenv

from api_client import collect_all_bids, enrich_license_info
from filters import hard_filter, apply_qualification_filter
from scorer import score_all
from reporter import generate_report

load_dotenv()

# ─────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────

DEFAULT_KEYWORDS = ["AI", "빅데이터", "데이터분석", "교육", "인공지능", "양성", "리터러시"]
DEFAULT_DAYS_MIN  = 7   # 최소 7일 이후 마감
DEFAULT_DAYS_MAX  = 60  # 최대 60일 이내 마감
DEFAULT_LOOKBACK_DAYS = 90  # 최근 90일 공고를 수집한 뒤 마감일로 필터링
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = PROJECT_ROOT / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"

# ─────────────────────────────────────────────
# 로깅 설정
# ─────────────────────────────────────────────

# 로그 디렉토리 사전 생성
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / "scanner.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 모의(Mock) 데이터 생성 유틸
# ─────────────────────────────────────────────

def get_mock_bids(keywords: list[str]) -> dict[str, list[dict]]:
    """모의(Mock) 공고 수집 데이터 생성"""
    from datetime import datetime, timedelta

    today = datetime.now()
    results = {}

    templates = [
        {
            "title": "2026년 인공지능(AI) 기반 맞춤형 데이터 예측 모델 및 교육 플랫폼 구축",
            "org": "한국지능정보사회진흥원",
            "demand": "과학기술정보통신부",
            "method": "협상에의한계약",
            "kind": "용역",
            "days_left": 20,
            "budget": "250000000",
            "licenses": ["1468", "1469", "1470"],
        },
        {
            "title": "소상공인을 위한 생성형 AI 기술 활용 디지털 역량강화 교육 사업",
            "org": "소상공인시장진흥공단",
            "demand": "중소벤처기업부",
            "method": "협상에의한계약",
            "kind": "용역",
            "days_left": 10,
            "budget": "80000000",
            "licenses": ["1469", "9999"],
        },
        {
            "title": "2026년 인공지능 윤리 가이드라인 및 로드맵 수립 연구 용역",
            "org": "정보통신정책연구원",
            "demand": "정보통신정책연구원",
            "method": "제한경쟁",
            "kind": "용역",
            "days_left": 5,
            "budget": "40000000",
            "licenses": ["1169"],
        },
        {
            "title": "지방세정 빅데이터 분석 및 시각화 대시보드 구축 사업",
            "org": "부산광역시청",
            "demand": "부산광역시청",
            "method": "협상에의한계약",
            "kind": "용역",
            "days_left": 15,
            "budget": "130000000",
            "licenses": ["1470", "1468"],
        },
        {
            "title": "2026년 청년 디지털 인재 양성 및 AI·데이터 분석 부트캠프(HRD) 위탁 운영",
            "org": "한국데이터산업진흥원",
            "demand": "과학기술정보통신부",
            "method": "협상에의한계약",
            "kind": "용역",
            "days_left": 25,
            "budget": "320000000",
            "licenses": ["1469", "1470", "1169"],
        },
        {
            "title": "인공지능(AI) 대학원 연구동 정비 및 소방 설비 공사",
            "org": "한국과학기술원(KAIST)",
            "demand": "한국과학기술원(KAIST)",
            "method": "일반경쟁",
            "kind": "공사",
            "days_left": 15,
            "budget": "500000000",
            "licenses": ["1465"],
        },
        {
            "title": "국유재산 빅데이터 분석을 위한 GIS 공간정보 시스템 인프라 구축",
            "org": "한국자산관리공사",
            "demand": "한국자산관리공사",
            "method": "협상에의한계약",
            "kind": "용역",
            "days_left": 14,
            "budget": "180000000",
            "licenses": ["1170"],
        },
        {
            "title": "인공지능 솔루션 개발용 상용 GPU 소프트웨어 라이선스 구매",
            "org": "한국전자통신연구원",
            "demand": "한국전자통신연구원",
            "method": "일반경쟁",
            "kind": "물품",
            "days_left": 8,
            "budget": "120000000",
            "licenses": ["9999"],
        },
        {
            "title": "2026년 빅데이터 리터러시 소액 수의계약 위탁 교육",
            "org": "파주시청",
            "demand": "파주시청",
            "method": "수의계약",
            "kind": "용역",
            "days_left": 4,
            "budget": "15000000",
            "licenses": ["9999"],
        },
        {
            "title": "2026년 AI 데이터 표준화 가이드라인 제작 용역",
            "org": "한국지능정보사회진흥원",
            "demand": "한국지능정보사회진흥원",
            "method": "협상에의한계약",
            "kind": "용역",
            "days_left": -2,
            "budget": "45000000",
            "licenses": ["1468", "1470"],
        }
    ]

    for kw in keywords:
        kw_bids = []
        kw_lower = kw.lower()
        for i, t in enumerate(templates):
            title_lower = t["title"].lower()
            is_match = False
            
            if kw_lower in title_lower:
                is_match = True
            elif kw_lower == "ai" and ("인공지능" in title_lower or "딥러닝" in title_lower):
                is_match = True
            elif kw_lower == "인공지능" and "ai" in title_lower:
                is_match = True
            elif kw_lower == "빅데이터" and "데이터" in title_lower:
                is_match = True
            elif kw_lower == "데이터분석" and ("빅데이터" in title_lower or "데이터" in title_lower):
                is_match = True
            elif kw_lower == "교육" and ("부트캠프" in title_lower or "양성" in title_lower or "리터러시" in title_lower or "역량강화" in title_lower):
                is_match = True
                
            if is_match or len(kw_bids) < 3:
                bid_no = f"R{26 + i:02d}BK{100000 + i:06d}"
                ord_no = "00"
                close_dt = (today + timedelta(days=t["days_left"])).strftime("%Y%m%d%H%M")
                notice_dt = (today - timedelta(days=2)).strftime("%Y%m%d%H%M")
                
                bid = {
                    "_source": "15129394",
                    "bidNtceNo": bid_no,
                    "bidNtceOrd": ord_no,
                    "bidNtceFullNo": f"{bid_no}-{ord_no}",
                    "bidNtceNm": t["title"],
                    "ntceInsttNm": t["org"],
                    "dmndInsttNm": t["demand"],
                    "bidMthdNm": t["method"],
                    "ntceKindNm": t["kind"],
                    "bidClseDt": close_dt,
                    "bidNtceDt": notice_dt,
                    "presmptPrce": t["budget"],
                    "asignBdgtAmt": t["budget"],
                    "_license_codes": t["licenses"],
                    "_license_source": "API(getLicenseInfoServc)" if t["licenses"] else "",
                }
                kw_bids.append(bid)
        results[kw] = kw_bids
        
    return results


# ─────────────────────────────────────────────
# 핵심 파이프라인
# ─────────────────────────────────────────────

def run_scan(keywords: list[str],
             days_min: int = DEFAULT_DAYS_MIN,
             days_max: int = DEFAULT_DAYS_MAX,
             top_n: int = 10,
             mock: bool = False) -> str:
    """
    공고 수집 → 필터링 → 점수화 → xlsx 생성.

    Returns:
        생성된 xlsx 파일 경로
    """
    today    = datetime.now()
    notice_start_dt = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    notice_end_dt   = today
    close_start_dt  = today + timedelta(days=days_min)
    close_end_dt    = today + timedelta(days=days_max)

    logger.info("=" * 60)
    logger.info("🚀 나라장터 공고 스캔 시작" + (" (🧪 모의 데이터 모드)" if mock else ""))
    logger.info("   키워드  : %s", ", ".join(keywords))
    logger.info("   공고수집: %s ~ %s (공고일 기준)",
                notice_start_dt.strftime("%Y-%m-%d"),
                notice_end_dt.strftime("%Y-%m-%d"))
    logger.info("   마감필터: %s ~ %s",
                close_start_dt.strftime("%Y-%m-%d"),
                close_end_dt.strftime("%Y-%m-%d"))
    logger.info("=" * 60)

    # Step 1: 공고 수집 (API 또는 Mock)
    if mock:
        logger.info("[1/4] 🧪 모의(Mock) 데이터 로드 중...")
        raw = get_mock_bids(keywords)
    else:
        logger.info("[1/4] API 호출 중 (용역·물품 병렬)...")
        raw = collect_all_bids(keywords, notice_start_dt, notice_end_dt, fetch_license=False)

    # Step 2: Hard filter + 자격 필터
    logger.info("[2/4] 필터링 중...")
    keyword_results: dict[str, dict] = {}
    for kw, bids in raw.items():
        total = len(bids)

        # 하드 필터 (마감일·수의계약·공사)
        after_hard = [b for b in bids
                      if hard_filter(b, today, days_min, days_max)[0]]
        enrich_license_info(after_hard)

        # 자격 필터 (등록업종 매칭)
        qualified, disqualified = apply_qualification_filter(after_hard)

        logger.info("   [%s] 전체 %d건 → 하드필터 통과 %d건 → 자격통과 %d건 / 미해당 %d건",
                    kw, total, len(after_hard), len(qualified), len(disqualified))

        keyword_results[kw] = {
            "qualified":    qualified,
            "disqualified": disqualified,
            "total":        total,
        }

    # Step 3: 점수화 (자격 통과 공고만)
    logger.info("[3/4] 적합도 점수화 중...")
    for kw, v in keyword_results.items():
        v["qualified"] = score_all(v["qualified"], today)

    # Step 4: xlsx 리포트 생성
    REPORTS_DIR.mkdir(exist_ok=True)
    filename = f"공고스캔_{today.strftime('%Y%m%d_%H%M')}.xlsx"
    output_path = str(REPORTS_DIR / filename)

    logger.info("[4/4] xlsx 리포트 생성 중 → %s", output_path)
    generate_report(keyword_results, output_path, today=today, top_n=top_n)

    # 요약 출력
    logger.info("=" * 60)
    logger.info("✅ 스캔 완료!")
    total_q = sum(len(v["qualified"])   for v in keyword_results.values())
    total_d = sum(len(v["disqualified"]) for v in keyword_results.values())
    logger.info("   자격 통과: %d건  /  미해당: %d건", total_q, total_d)
    logger.info("   리포트  : %s", output_path)

    # S등급 공고 요약 출력
    s_bids = []
    for v in keyword_results.values():
        s_bids.extend([b for b in v["qualified"] if b.get("_grade") == "S"])
    if s_bids:
        logger.info("🌟 S등급 공고 (%d건):", len(s_bids))
        for b in s_bids[:5]:
            logger.info("   [%s] %s (%s, %s점)",
                        b.get("bidNtceNo", ""),
                        b.get("bidNtceNm", "")[:40],
                        b.get("ntceInsttNm", ""),
                        b.get("_score", 0))

    logger.info("=" * 60)
    return output_path


# ─────────────────────────────────────────────
# 주간 스케줄러
# ─────────────────────────────────────────────

def scheduled_job(keywords: list[str]):
    """매주 월요일 자동 실행 작업."""
    try:
        path = run_scan(keywords)
        logger.info("📅 주간 스캔 완료: %s", path)
    except Exception as e:
        logger.error("❌ 주간 스캔 실패: %s", e, exc_info=True)


def run_scheduler(keywords: list[str]):
    if not HAS_SCHEDULE:
        logger.error("'schedule' 패키지가 필요합니다. pip install schedule")
        sys.exit(1)

    logger.info("📅 주간 스케줄러 시작 — 매주 월요일 09:00 실행")
    schedule.every().monday.at("09:00").do(scheduled_job, keywords=keywords)

    # 즉시 1회 실행 (처음 등록 시)
    logger.info("📅 최초 실행 중...")
    scheduled_job(keywords)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="나라장터 공고 스캐너 — 조달청 OpenAPI 기반"
    )
    parser.add_argument(
        "--keywords", nargs="+", default=DEFAULT_KEYWORDS,
        help="검색 키워드 목록 (기본: AI 빅데이터 데이터분석 교육 인공지능 양성 리터러시)"
    )
    parser.add_argument(
        "--days-min", type=int, default=DEFAULT_DAYS_MIN,
        help="마감일 최소 여유 일수 (기본: 0)"
    )
    parser.add_argument(
        "--days-max", type=int, default=DEFAULT_DAYS_MAX,
        help="마감일 최대 여유 일수 (기본: 60)"
    )
    parser.add_argument(
        "--top-n", type=int, default=10,
        help="키워드 시트당 표시 건수 (기본: 10)"
    )
    parser.add_argument(
        "--schedule", action="store_true",
        help="주간 스케줄러 모드 (매주 월요일 09:00 자동 실행)"
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="모의(Mock) 데이터 모드로 실행하여 API 호출 없이 샘플 리포트 생성"
    )

    args = parser.parse_args()

    # 로그 디렉토리 생성
    LOGS_DIR.mkdir(exist_ok=True)

    if not args.mock and not os.environ.get("G2B_API_KEY"):
        api_key = input("G2B_API_KEY (공공데이터포털 서비스키)를 입력하세요: ").strip()
        if not api_key:
            logger.error("API 키가 없으면 실행할 수 없습니다.")
            sys.exit(1)
        os.environ["G2B_API_KEY"] = api_key
        # api_client 모듈에도 반영
        import api_client
        api_client.API_KEY = api_key

    if args.schedule:
        run_scheduler(args.keywords)
    else:
        run_scan(
            keywords=args.keywords,
            days_min=args.days_min,
            days_max=args.days_max,
            top_n=args.top_n,
            mock=args.mock,
        )


if __name__ == "__main__":
    main()
