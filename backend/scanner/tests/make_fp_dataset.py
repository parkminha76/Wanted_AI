"""오탐 제거 분류기 학습 데이터 생성기 (A의 요청 스펙 대응).

    uv run python backend/scanner/tests/make_fp_dataset.py

**사람이 하는 일은 문장 쓰기 하나다.** 아래 TEMPLATES에 `{value}` 자리를 비워 둔
문장만 채우면 된다. 나머지는 전부 이 스크립트가 한다.

  - `{value}` 자리에 넣을 가짜 값 생성 (체크섬이 있는 타입은 통과하도록 계산해서)
  - `start`/`end` 계산 — 손으로 세면 반드시 틀린다. 한글은 눈으로 자릿수를 못 센다
  - `text[start:end]`가 정말 그 값인지 검산
  - **`rules.py`가 실제로 그 값을 그 타입 후보로 잡는지 확인** (아래 설명)
  - `group_id` 부여, 규격대로 JSON 저장, 칸별 건수 집계

왜 rules.py 통과 여부까지 확인하나
----------------------------------
오탐 제거 분류기는 **정규식이 이미 잡은 후보만** 넘겨받는다
(`models.filter_false_positive(text, context, risk_type)`). 그러니 `rules.py`가
애초에 안 잡는 값으로 학습시키면, 실제로는 들어올 일이 없는 입력을 배우는 셈이다.
label=0(오탐 예시)도 마찬가지다 — **정규식과 체크섬을 통과했는데 문맥상 아닌 것**이라야
분류기가 실제로 판정할 거리가 된다. 그래서 값 생성기가 체크섬까지 맞춰서 만든다.

`emp_no`(사번) 탐지기는 2026-09-12에 `rules.py`에 들어왔다
----------------------------------------------------------
처음 이 파일을 쓸 때는 A가 요청한 5개 타입 중 사번만 `rules.py`에 정규식이 없어서
어떤 문장을 넣어도 후보로 잡히지 않았다. 지금은 `EMPLOYEE_NUMBER_PATTERN`이 있고,
값의 모양이 아니라 **옆에 오는 라벨 단어**("사번 2024-0317")를 기준으로 잡는다.

그래서 label=0(오탐 예시)을 만들기가 오히려 어렵다 — "사번 키워드 뒤인데 진짜 사번이
아닌 값"만 오탐이 되기 때문이다. 아래 TEMPLATE_TARGET_OVERRIDES에서 그 칸만 목표를
낮춰 둔 이유이고, 정규식이 오탐을 구조적으로 막고 있다는 뜻이라 나쁜 신호가 아니다.
검증 표의 "rules.py 확인" 칸에서 실제로 잡히는지 매번 확인한다.

주의: 값은 전부 합성이다. 실제 개인정보는 한 건도 들어가지 않는다.
"""

from __future__ import annotations

import datetime
import json
import os
import random
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.scanner.detectors import rules      # noqa: E402

OUT_DIR = os.path.join(REPO_ROOT, "sample_data", "false_positive")
AUTHOR = "B"                       # 파일명에 들어간다
BATCH = 1                          # 같은 날 또 보낼 때 2, 3으로 올린다

# A가 정한 목표: 타입당 label=1·0 각 30건. 문장 15개 x 값 2개 = 30건.
RECORDS_PER_TEMPLATE = 2
TARGET_PER_BUCKET = 30
MIN_TEMPLATES = TARGET_PER_BUCKET // RECORDS_PER_TEMPLATE

# 칸별 목표 예외. **A와 합의한 것만** 여기 적고, 왜 낮췄는지 같이 남긴다.
# 그냥 채우기 힘들다고 낮추면 그 칸의 분류기 성능이 조용히 나빠진다.
TEMPLATE_TARGET_OVERRIDES: dict[tuple[str, int], int] = {
    # 2026-09-12. emp_no 탐지기가 키워드 앵커 방식이라 "사번 키워드 뒤인데 실제
    # 사번이 아닌 값"만 오탐이 된다. 형식 설명·예시·더미값·번호대역 정도가 전부라
    # 12문장이 한계다. 더 채우면 서로 비슷한 문장만 늘어 학습에 해가 된다.
    # **분류기 입장에서는 오히려 좋은 신호다** — 정규식이 오탐을 구조적으로 막고 있다.
    # A 확인 필요.
    ("emp_no", 0): 12,
    # 2026-09-10 ("phone", 0): 4 로 낮췄다가 **2026-09-12에 되돌렸다.**
    # 그때는 휴대폰 `01[016789]`만 잡아서 "전화번호 형식인데 전화번호가 아닌 것"이
    # 현실에 없었다. rules.py에 지역번호(02·031~064·070·050X)가 들어오면서
    # 회사 대표번호·고객센터가 후보로 잡히기 시작했고, 그게 전부 개인정보가 아니라
    # label 0 재료가 됐다. 목표를 낮출 이유가 사라져서 예외를 지운다.
}


def target_templates(risk_type: str, label: int) -> int:
    """그 칸에 필요한 문장 수."""
    return TEMPLATE_TARGET_OVERRIDES.get((risk_type, label), MIN_TEMPLATES)

random.seed(20260910)              # 돌릴 때마다 같은 값이 나오게 고정


# ---------------------------------------------------------------------------
# 여기만 채우면 된다
# ---------------------------------------------------------------------------
#
# 규칙 세 가지
#   1. 값이 들어갈 자리에 `{value}`를 **정확히 한 번** 쓴다.
#   2. label=1은 "문맥상 진짜 그 타입인 문장", label=0은 "형태는 같은데 다른 용도인 문장".
#   3. **문장을 다양하게 쓰는 게 개수보다 중요하다.** 모델은 숫자가 아니라 옆에 있는
#      단어를 본다. 같은 문장에 값만 바꾸면 모델에게는 같은 문장 하나다.
#
# 문장 옆에 설명을 붙이고 싶으면 ("문장", "설명") 형태로 쓰면 note에 들어간다.
#
# 지금 들어 있는 것은 **형식을 보여주는 예시**다. 칸마다 15개가 될 때까지 추가할 것 —
# 몇 개가 모자란지는 스크립트가 실행할 때마다 알려준다.

# ---------------------------------------------------------------------------
# 경계선 케이스 처리 방침 (2026-09-12 확정)
# ---------------------------------------------------------------------------
#
# 개인 것인지 조직 것인지 문장만으로 가릴 수 없으면 **그 문장은 쓰지 않는다.**
# label 0으로 흡수하지 않는다.
#
#   label 0으로 흡수하면   "애매하면 개인정보가 아니다"를 가르치는 셈이 된다.
#                          오탐은 줄지만 **놓침이 늘어난다** — 개인정보 보호 제품에서
#                          놓침은 오탐보다 큰 실패다.
#   별도 카테고리는        A의 학습 파이프라인이 label 0/1만 받아서 만들 수 없다.
#
# A의 요청서도 같은 방침이다 — "애매하면 라벨링 보류하고 A와 상의. 임의로 라벨링하지
# 말 것. 잘못된 라벨 하나가 데이터 적은 초기 단계에서는 영향이 크다."
#
# 애매한 문장을 살리고 싶으면 버리는 대신 **문맥을 더 준다**:
# "문의사항은 {value}로 연락 주세요"(애매) -> "퇴사 후에도 {value}로 연락 주셔도
# 괜찮습니다"(개인 확정) 처럼 귀속이 드러나는 사실을 문장에 넣는다.


TEMPLATES: dict[str, dict[int, list]] = {
    # ---------------- 계좌번호 ----------------
    "account": {
        1: [
            "입금 계좌는 {value}입니다. 확인 후 송금 부탁드립니다",
            "환불 계좌 {value}로 3영업일 이내 처리됩니다",
            "급여 이체 계좌를 {value}로 변경 신청합니다",
            "대금은 하나은행 {value} 계좌로 입금해 주세요",
            "보증금 반환 계좌: {value} (예금주 본인 확인 필요)",
            "자동이체 등록 계좌 {value} 승인되었습니다",
            "{value}로 잔금 이체를 완료했습니다",
            "정산 대금 수령 계좌를 {value}로 등록해 주십시오",
            "국민은행 {value} 예금주명이 일치하지 않습니다",
            "계약금은 아래 계좌로 송금 바랍니다 — {value}",
            "월세는 매월 이십오일에 {value}로 자동 출금됩니다",
            "출금 계좌 {value}의 잔액이 부족합니다",
            "지급 계좌 정보가 {value}로 확인되었습니다",
            "후원금은 {value}(농협)로 보내주시면 됩니다",
            "기존 입금계좌 {value}는 폐업으로 사용이 중지되었습니다",
        ],
        0: [
            ("주문번호 {value} 배송 조회 부탁드립니다", "주문번호"),
            ("송장번호 {value}로 택배 추적이 가능합니다", "송장번호"),
            ("계약 관리번호 {value} 문서를 첨부합니다", "문서 관리번호"),
            ("상담 접수번호 {value}로 진행 상황을 확인하세요", "접수번호"),
            ("재고 관리 코드 {value} 품목은 단종되었습니다", "재고 코드"),
            ("회의실 예약번호 {value} 확인 부탁드립니다", "예약번호"),
            ("청구서 번호 {value} 기준으로 재발행했습니다", "청구서 번호"),
            ("견적서 {value} 유효기간은 발행일로부터 보름입니다", "견적서 번호"),
            ("등기번호 {value}로 우편물 조회가 가능합니다", "등기번호"),
            ("작업지시서 {value} 공정이 완료되었습니다", "작업지시번호"),
            ("차량 배차번호 {value} 기사님께 전달했습니다", "배차번호"),
            ("바코드 {value} 스캔 오류가 발생했습니다", "바코드"),
            ("A/S 접수번호는 {value}이며 방문은 사흘 내 예정입니다", "A/S 접수번호"),
            ("정기점검 이력번호 {value} 조회 결과입니다", "이력번호"),
            ("입찰 공고번호 {value} 마감이 연장되었습니다", "공고번호"),
            # 사번 문맥 문장 5개가 여기 있었는데 **2026-09-12에 뺐다.**
            # rules.py에 emp_no 탐지기(키워드 앵커 방식)가 들어오면서 "사번 XXX"는
            # emp_no로 먼저 잡히고 account 후보가 아예 안 된다 — 정규식이 구조적으로
            # 해결해서 분류기가 배울 필요가 없어졌다. 후보가 안 되는 값으로 학습시키면
            # 실제로는 들어올 일 없는 입력을 배우게 된다.
        ],
    },
    # ---------------- 사업자등록번호 ----------------
    "biz_reg": {
        1: [
            "사업자등록번호 {value}로 세금계산서 발행 부탁드립니다",
            "당사 사업자등록번호는 {value}입니다",
            "거래처 등록을 위해 사업자등록번호 {value}를 제출합니다",
            "세금계산서에 기재된 사업자번호 {value}가 맞는지 확인해 주세요",
            "폐업 조회 결과 사업자등록번호 {value}는 정상 사업자입니다",
            "부가세 신고 시 사업자등록번호 {value}를 입력하세요",
            "{value} 사업자로 등록된 상호가 변경되었습니다",
            "계산서 발행처 사업자번호: {value}",
            "홈택스에서 {value} 사업자 상태를 조회했습니다",
            "면세사업자 {value}는 계산서만 발행 가능합니다",
            "사업자등록증 사본과 함께 {value} 확인 부탁드립니다",
            "본 계약의 갑은 사업자등록번호 {value}의 법인입니다",
            "간이과세자 {value}로 등록 변경을 신청했습니다",
            "공급자 등록번호 {value} 오기재로 계산서를 수정합니다",
            "입점 심사에 필요한 사업자번호는 {value}입니다",
        ],
        0: [
            ("발주서 번호 {value} 기준으로 처리하겠습니다", "발주번호"),
            ("자산 관리번호 {value} 장비는 폐기 예정입니다", "자산번호"),
            ("민원 접수번호 {value} 처리 결과를 안내드립니다", "접수번호"),
            ("쿠폰 코드 {value}는 이번 달까지 사용 가능합니다", "쿠폰코드"),
            ("설비 일련번호 {value} 점검이 완료되었습니다", "일련번호"),
            ("교육 수강번호 {value}로 출석이 등록되었습니다", "수강번호"),
            ("도서 관리번호 {value} 현재 대출 중입니다", "도서 관리번호"),
            ("품목 코드 {value} 단가가 인상되었습니다", "품목 코드"),
            ("보증서 번호 {value}를 분실했습니다", "보증서 번호"),
            ("전표번호 {value} 승인 대기 상태입니다", "전표번호"),
            ("공사 현장코드 {value} 안전점검 일정입니다", "현장코드"),
            ("배송 예약번호 {value}로 변경 가능합니다", "예약번호"),
            ("설문 응답번호 {value} 데이터를 집계했습니다", "응답번호"),
            ("증빙자료 일련번호 {value} 첨부합니다", "일련번호"),
            ("정기구독 번호 {value} 갱신 안내드립니다", "구독번호"),
            # --- 사번 ---
            # 값은 타입 기본 생성기(체크섬 통과 3-2-5)를 그대로 쓴다. 사번이 그 형식일
            # 확률은 낮지만, 분류기가 배워야 할 규칙("사번이라는 단어가 있으면
            # 사업자등록번호가 아니다")은 형식과 무관하게 같다.
            ("사번 {value} 직원의 재직증명서를 발급했습니다", "사번"),
            ("직원번호 {value}로 사내 시스템에 접속했습니다", "사번"),
            ("사원번호 {value} 부서 이동 내역입니다", "사번"),
            ("퇴직 처리된 사번 {value}를 명단에서 제외했습니다", "사번"),
            ("사번 {value} 님의 교육 이수 현황입니다", "사번"),
        ],
    },
    # ---------------- 사번 ----------------
    "emp_no": {
        1: [
            "사번 {value} 직원의 근태 기록입니다",
            "입사 시 부여된 사번 {value}로 로그인하세요",
            "인사 시스템에 사번 {value}가 등록되어 있습니다",
            "사번 {value} 직원의 연차 잔여일수를 확인합니다",
            "퇴사 처리된 사번 {value} 계정을 비활성화합니다",
            "급여명세서는 사번 {value} 기준으로 발급됩니다",
            "사원번호 {value} 직원의 부서 이동을 승인합니다",
            "교육 이수 현황 — 사번 {value} 미이수",
            "출입카드 재발급 대상 사번은 {value}입니다",
            "사번 {value}로 사내 시스템 권한을 신청했습니다",
            "평가 대상자 사번 {value}의 면담 일정입니다",
            "직원번호 {value} 경력 증명서를 발급했습니다",
            "사번 {value} 계정의 비밀번호가 초기화되었습니다",
            "신규 입사자에게 사번 {value}를 부여했습니다",
            "사번 {value} 님의 건강검진 예약이 완료되었습니다",
        ],
        0: [
            # ⚠️ 이 칸은 2026-09-12에 전부 새로 썼다.
            #
            # rules.py의 emp_no 탐지기는 **키워드 앵커 방식**이다 —
            # (사번|사원번호|직원번호|임직원번호) 바로 뒤에 오는 값만 잡는다.
            # 그래서 "문서번호 97-83140" 같은 문장은 애초에 후보가 되지 않는다
            # (예전 15문장이 전부 그런 것들이라 30건이 통째로 쓸모없었다).
            #
            # 이 방식에서 오탐이 나는 자리는 하나뿐이다: **사번 키워드 뒤에 오는 값이
            # 실제 직원의 번호가 아닌 경우** — 형식 설명, 예시, 더미값, 번호 대역.
            ("사번 {value} 형식으로 자동 부여됩니다", "사번 형식 설명"),
            ("직원번호 {value} 형태는 2020년부터 쓰지 않습니다", "폐기된 형식"),
            ("사원번호 {value} 규칙을 이번에 개정했습니다", "부여 규칙"),
            ("사번 {value} 이후 입사자부터 새 체계를 적용합니다", "기준점"),
            ("직원번호 {value} 예시를 참고해 작성해 주세요", "작성 예시"),
            ("사번 {value} 는 샘플이며 실제 직원이 아닙니다", "샘플값"),
            ("사원번호 {value} 대역은 아직 사용하지 않습니다", "미사용 번호대역"),
            ("사번 {value} 번대는 퇴사자에게 재사용하지 않습니다", "번호대역 정책"),
            ("직원번호 {value} 컬럼은 테스트 값으로 채워져 있습니다", "테스트 데이터"),
            ("사번 {value} 마스킹 처리 예시 화면입니다", "마스킹 예시"),
            ("사원번호 {value} 템플릿을 내려받아 작성하세요", "양식 템플릿"),
            ("직원번호 {value} 더미값으로 이관 테스트를 진행했습니다", "더미값"),
        ],
    },
    # ---------------- 전화번호 ----------------
    #
    # **라벨 기준: 유선이냐 휴대폰이냐가 아니라 "누구에게 연결되느냐"다.**
    #
    #     특정 개인에게 연결  -> label 1  (개인 휴대폰, 직통번호, 자택 전화)
    #     조직 아무나 받음    -> label 0  (대표번호, 고객센터, 민원실, 콜센터)
    #
    # 회사 유선번호라도 그 사람에게 바로 연결되면 개인정보다. 명함에 찍혀 배포돼도
    # 마찬가지다 — 공개됐다는 게 개인정보가 아니라는 뜻은 아니고 위험도가 낮아질 뿐이다.
    #
    # 그래서 **문장만 읽고도 개인 것인지 조직 것인지 분명해야 한다.**
    # "문의사항은 {value}로 연락 주세요"에 유선번호가 들어가면 누가 봐도 회사 번호인데
    # label 1에 있으면 분류기에 잘못된 답을 가르친다(2026-09-12에 그런 문장 5개를 고쳤다).
    # 애매하면 "직통"·"자택"·"본인"·"고객님"처럼 귀속이 드러나는 말을 넣거나 뺀다.
    #
    # 유선을 label 1에서 통째로 빼면 안 된다. 그러면 분류기가 "02로 시작하면 개인정보가
    # 아니다"를 배워서 진짜 직통번호·자택번호를 놓친다.
    "phone": {
        1: [
            "담당자 직통번호는 {value}입니다",
            "재택근무 중이라 자택 전화 {value}로 연락 부탁드립니다",
            ("휴대폰 번호 {value}로 인증번호를 발송했습니다", "", "phone_mobile"),
            ("긴급 시 담당자 개인 번호 {value}로 전화 부탁드립니다", "", "phone_mobile"),
            ("배송 기사 연락처 {value} 안내드립니다", "", "phone_mobile"),
            "예약 확인을 위해 고객님 번호 {value}로 연락드리겠습니다",
            ("{value}로 부재중 전화가 왔습니다", "", "phone_mobile"),
            "비상연락망에 본인 연락처 {value}를 등록했습니다",
            ("수신자 번호 {value}가 결번입니다", "", "phone_mobile"),
            ("본인 명의 휴대전화 {value}로 본인확인을 진행합니다", "", "phone_mobile"),
            "가입 시 입력하신 번호 {value}가 맞습니까",
            ("택배 수령인 연락처: {value}", "", "phone_mobile"),
            ("면접 안내는 {value}로 문자 발송됩니다", "", "phone_mobile"),
            ("{value} 번호로 알림톡이 전송되었습니다", "", "phone_mobile"),
            "보호자 연락처 {value}를 기재해 주세요",
            # --- 키워드 없이 문맥만으로 개인 소유가 드러나는 문장 ---
            # "직통"·"자택"·"본인"·"고객님"으로만 label 1을 채우면 모델이 그 네 단어를
            # 외운다. 그 단어가 없는 개인 번호를 통째로 놓치게 되므로 섞어 둔다.
            "퇴사 후에도 {value}로 연락 주셔도 괜찮습니다",
            "제 명의로 되어 있는 번호는 {value}입니다",
            "{value}는 제가 십 년 넘게 쓰고 있는 번호입니다",
            "이사하면서 번호가 {value}로 바뀌었습니다",
        ],
        0: [
            # 문서 안의 예시·더미값
            ("양식의 연락처란에는 {value} 형태로 입력하세요", "입력 서식 예시"),
            ("아래 {value}는 예시 번호이며 실제 번호가 아닙니다", "문서 내 예시"),
            ("테스트 계정의 더미 번호 {value}는 발송 대상에서 제외됩니다", "테스트 더미값"),
            ("매뉴얼 캡처에 쓰인 {value}는 가상의 번호입니다", "매뉴얼 예시"),
            # --- 회사 대표번호·고객센터 ---
            # 개인 집 전화와 **형식이 완전히 같은데** 홈페이지에 공개된 사업자 정보라
            # 개인정보가 아니다. 숫자로는 절대 못 가르고 옆 단어로만 갈린다.
            # 지역번호가 phone 패턴에 들어오면서 생긴 오탐의 주범이자,
            # 분류기가 배우기에 가장 좋은 재료다.
            ("고객센터 {value}로 문의해 주시기 바랍니다", "회사 고객센터", "phone_landline"),
            ("본사 대표번호는 {value}입니다", "회사 대표번호", "phone_landline"),
            ("기술지원 직통 {value} (평일 09시~18시)", "부서 직통번호", "phone_landline"),
            ("A/S 접수는 {value}로 전화 주세요", "회사 접수번호", "phone_landline"),
            ("지점 대표번호 {value} 안내드립니다", "지점 대표번호", "phone_landline"),
            ("예약 문의: {value} (자동응답 운영)", "예약 대표번호", "phone_landline"),
            ("민원실 대표전화 {value}로 연결됩니다", "기관 대표번호", "phone_landline"),
            ("회사 대표번호가 {value}로 변경되었습니다", "회사 대표번호", "phone_landline"),
            ("콜센터 {value} 운영시간은 평일만입니다", "콜센터", "phone_landline"),
            ("매장 전화번호 {value}는 홈페이지에 공개되어 있습니다", "공개된 매장번호", "phone_landline"),
            ("총무팀 사무실 번호 {value}로 문의 바랍니다", "부서 사무실번호", "phone_landline"),
            # --- 키워드 없이 문맥만으로 조직 소유가 드러나는 문장 (label 1과 같은 이유) ---
            ("{value}로 전화하시면 상담원이 연결됩니다", "상담원 연결 = 조직", "phone_landline"),
            ("홈페이지 하단에 안내된 번호 {value}로 문의해 주세요", "공개 안내 번호", "phone_landline"),
            ("{value}는 24시간 자동응답으로 운영됩니다", "자동응답 운영 = 조직", "phone_landline"),
        ],
    },
    # ---------------- 카드번호 ----------------
    "card": {
        1: [
            "결제 카드번호 {value} 승인 완료되었습니다",
            "등록하신 카드 {value}의 유효기간을 확인해 주세요",
            "카드번호 {value}로 자동결제가 등록되었습니다",
            "환불은 결제하신 카드 {value}로 처리됩니다",
            "법인카드 {value} 사용 내역을 첨부합니다",
            "카드 {value} 분실 신고가 접수되었습니다",
            "{value} 카드로 할부 결제했습니다",
            "체크카드 {value} 한도가 초과되었습니다",
            "정기결제 수단을 카드 {value}로 변경했습니다",
            "해외 결제가 차단된 카드 {value} 해제를 요청드립니다",
            "카드번호 {value} 건의 승인이 취소되었습니다",
            "재발급된 카드 {value}를 등록해 주세요",
            "가맹점 매출전표의 카드번호는 {value}입니다",
            "{value} 카드의 청구 내역을 조회했습니다",
            "결제수단으로 등록된 신용카드 {value}가 만료되었습니다",
        ],
        0: [
            ("상품권 번호 {value}를 입력하시면 사용 가능합니다", "상품권 번호"),
            ("기프트카드 일련번호 {value} 잔액을 조회합니다", "기프트카드 일련번호"),
            ("쿠폰번호 {value}는 중복 사용이 불가합니다", "쿠폰번호"),
            ("장비 시리얼 {value} 보증기간이 만료되었습니다", "장비 시리얼"),
            ("멤버십 카드번호 {value} 포인트 적립 내역입니다", "멤버십 번호"),
            ("회원번호 {value}로 조회하시면 됩니다", "회원번호"),
            ("도서 바코드 {value} 반납 처리되었습니다", "바코드"),
            ("제품 등록번호 {value} 보증 서비스 안내입니다", "제품 등록번호"),
            ("주차권 번호 {value}는 당일에만 유효합니다", "주차권 번호"),
            ("사원증 일련번호 {value} 재발급 신청서입니다", "사원증 일련번호"),
            ("소프트웨어 인증번호 {value}를 입력하세요", "인증번호"),
            ("교통카드 충전 이력번호 {value} 확인 바랍니다", "이력번호"),
            ("경품 응모번호 {value} 당첨자 발표입니다", "응모번호"),
            ("설비 자산태그 {value} 위치가 변경되었습니다", "자산태그"),
            ("택배 운송장번호 {value} 배송 완료되었습니다", "운송장번호"),
        ],
    },
}


# ---------------------------------------------------------------------------
# 값 생성기 — 체크섬이 있는 타입은 통과하도록 계산해서 만든다
# ---------------------------------------------------------------------------


def _luhn_check_digit(digits: str) -> str:
    """Luhn 체크 디지트. 카드번호 마지막 한 자리가 이 값이어야 한다."""
    total = 0
    for i, ch in enumerate(reversed(digits + "0")):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - total % 10) % 10)


def gen_card() -> str:
    """Luhn을 통과하는 16자리 카드번호. rules.py가 card 후보로 잡는다."""
    body = random.choice("453") + "".join(str(random.randint(0, 9)) for _ in range(14))
    digits = body + _luhn_check_digit(body)
    return "-".join(digits[i:i + 4] for i in (0, 4, 8, 12))


def gen_biz_reg() -> str:
    """체크섬을 통과하는 사업자등록번호 10자리 (가중치 1,3,7,1,3,7,1,3,5)."""
    while True:
        head = "".join(str(random.randint(0, 9)) for _ in range(9))
        weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
        total = sum(int(d) * w for d, w in zip(head, weights))
        total += (int(head[8]) * 5) // 10
        check = (10 - (total % 10)) % 10
        digits = head + str(check)
        if digits[0] != "0":                     # 000-으로 시작하는 값은 어색하다
            return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


# 은행별 자릿수 묶음. 총 10~16자리여야 rules.py가 account 후보로 잡는다.
#
# 카카오뱅크 형식(4-2-7, 예: 3333-01-1234567)은 **일부러 뺐다.** 지금 rules.py가
# 못 잡아서(_KNOWN_GAPS 참고) 분류기에 후보로 넘어올 일이 없고, 넘어오지 않는 값으로
# 학습시키면 데이터만 더러워진다. rules.py가 고쳐지면 (4, 2, 7)을 여기 다시 넣을 것.
_ACCOUNT_SHAPES = ((3, 2, 4, 5), (3, 3, 6), (4, 3, 6), (3, 6, 5), (4, 4, 5), (3, 4, 6))


# rules.py가 못 잡는 것으로 확인된 실제 형식. 돌릴 때마다 다시 확인해서, 고쳐지면
# 경고가 사라진다. 데이터에서 뺐다고 문제까지 사라지는 게 아니라서 남겨 둔다.
_KNOWN_GAPS = (
    ("account", "3333-01-1234567", "카카오뱅크 계좌 형식 (4-2-7)"),
)


def check_known_gaps() -> list[str]:
    """rules.py의 알려진 구멍이 아직 그대로인지 확인한다."""
    still_broken = []
    for risk_type, value, label in _KNOWN_GAPS:
        hits = rules.find_all(f"입금 계좌는 {value}입니다")
        if not any(h["field"] == risk_type for h in hits):
            still_broken.append(f"{label}: '{value}' -> rules.py가 {risk_type}로 못 잡음")
    return still_broken


def _passes_luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def gen_account() -> str:
    """계좌번호. 체크섬이 없어서 형식만 맞추면 된다.

    단, **Luhn을 우연히 통과하는 값은 버린다.** 카드번호 탐지기가 12~19자리를 보기
    때문에 14자리 계좌번호가 10번에 1번꼴로 card로 잡힌다(실측 2026-09-12: 60건 중 3건).
    그렇게 잡히면 account 후보가 아니게 되어 학습 데이터로 못 쓴다.
    """
    while True:
        shape = random.choice(_ACCOUNT_SHAPES)
        groups = []
        for index, size in enumerate(shape):
            first = str(random.randint(1, 9)) if index == 0 else str(random.randint(0, 9))
            groups.append(first + "".join(str(random.randint(0, 9)) for _ in range(size - 1)))
        value = "-".join(groups)
        # 휴대폰으로 오인될 모양(01X-...)은 rules.py가 account에서 제외한다
        if value.startswith(("010", "011", "016", "017", "018", "019")):
            continue
        if _passes_luhn(value.replace("-", "")):     # 카드번호로 잡혀버린다
            continue
        return value


# 유선·인터넷전화 국번. rules.py의 PHONE_NUMBER_PATTERN이 잡는 범위와 맞춘다 —
# 여기 없는 번호를 만들면 후보가 안 돼서 학습 데이터로 쓸모가 없다.
_LANDLINE_PREFIXES = (
    ["02"] * 4                                        # 서울
    + [f"03{d}" for d in range(1, 4)]                 # 경기·강원·충북
    + [f"04{d}" for d in range(1, 5)]                 # 충남·대전·경북 일부
    + [f"05{d}" for d in range(1, 6)]                 # 부산·울산·경남·대구
    + [f"06{d}" for d in range(1, 5)]                 # 전남·광주·전북·제주
    + ["070"] * 3                                     # 인터넷전화
    + ["0504", "0505"]                                # 안심번호
)


def gen_phone_mobile() -> str:
    """휴대폰 번호. "문자 발송"·"본인확인"처럼 휴대폰이라야 말이 되는 문장에 쓴다."""
    prefix = random.choice(["010"] * 6 + ["011", "016", "017", "018", "019"])
    return f"{prefix}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"


def gen_phone_landline() -> str:
    """유선·인터넷전화 번호. 회사 대표번호·고객센터 문장에 쓴다.

    **이 번호들이 오탐의 주범이다.** 개인 집 전화와 회사 대표번호가 형식이 똑같아서
    숫자만 봐서는 못 가른다. 분류기가 옆 단어("담당자 연락처" vs "고객센터")를 보고
    갈라야 하는 자리다.
    """
    prefix = random.choice(_LANDLINE_PREFIXES)
    body = random.randint(100, 9999) if prefix == "02" else random.randint(100, 999)
    return f"{prefix}-{body}-{random.randint(1000, 9999)}"


def gen_phone() -> str:
    """기본 생성기. 휴대폰과 유선을 섞는다.

    섞는 이유: label 1은 휴대폰, label 0은 유선으로만 만들면 **분류기가 문맥이 아니라
    번호 모양을 외운다.** "01로 시작하면 개인정보"라고 배워버리면 회사 대표번호를
    쓰는 개인 연락처를 통째로 놓친다.
    """
    return gen_phone_mobile() if random.random() < 0.5 else gen_phone_landline()


def gen_emp_no() -> str:
    """사번. 회사마다 형식이 완전히 달라서 표준이 없다 — 일부러 여러 모양을 섞는다."""
    style = random.randint(0, 3)
    if style == 0:
        return f"{random.randint(2015, 2026)}-{random.randint(0, 9999):04d}"
    if style == 1:
        return f"{random.choice('ABCDEFGHJKMPRST')}{random.randint(0, 9999):04d}"
    if style == 2:
        return f"EMP-{random.randint(0, 99999):05d}"
    return f"{random.randint(10, 99)}-{random.randint(0, 99999):05d}"


def gen_emp_no_like_account() -> str:
    """사번처럼 보이면서 계좌번호 패턴(10~16자리)에도 걸리는 값.

    `account`의 label=0에 쓴다. gen_account()가 만드는 은행 형식(예: 512-55-9401-22268)을
    "사번"이라고 부르는 문장은 어색해서 학습에 도움이 안 된다. 사번스러운 자릿수로
    만들되 계좌 정규식에는 걸리게 해야 분류기가 실제로 판정할 거리가 된다.
    """
    style = random.randint(0, 2)
    if style == 0:
        return f"{random.randint(2015, 2026)}-{random.randint(0, 9999):04d}-{random.randint(0, 9999):04d}"
    if style == 1:
        return f"{random.randint(10, 99)}-{random.randint(0, 999999):06d}-{random.randint(0, 999):03d}"
    return f"{random.randint(100, 999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"


GENERATORS = {
    "account": gen_account,
    "biz_reg": gen_biz_reg,
    "emp_no": gen_emp_no,
    "phone": gen_phone,
    "card": gen_card,
    # 타입 이름이 아니라 문장별로 지정할 수 있는 생성기 (템플릿 3번째 칸에 이름을 쓴다)
    "emp_no_like_account": gen_emp_no_like_account,
    "phone_mobile": gen_phone_mobile,
    "phone_landline": gen_phone_landline,
}


# ---------------------------------------------------------------------------
# 레코드 만들기
# ---------------------------------------------------------------------------

PLACEHOLDER = "{value}"


def _unpack(entry) -> tuple[str, str, str]:
    """템플릿 항목을 (문장, 설명, 생성기이름)으로 푼다. 뒤 둘은 없어도 된다.

        "문장 {value}"                          -> 설명 없음, 타입 기본 생성기
        ("문장 {value}", "설명")                 -> 타입 기본 생성기
        ("문장 {value}", "설명", "생성기이름")     -> 그 문장만 다른 생성기를 쓴다
    """
    if isinstance(entry, tuple):
        return entry[0], entry[1], (entry[2] if len(entry) > 2 else "")
    return entry, "", ""


def build_records() -> tuple[list[dict], list[str]]:
    """TEMPLATES를 A의 규격대로 된 레코드 목록으로 바꾼다."""
    records: list[dict] = []
    problems: list[str] = []

    for risk_type, buckets in TEMPLATES.items():
        generate = GENERATORS[risk_type]
        for label in (1, 0):
            for template_index, entry in enumerate(buckets.get(label, []), start=1):
                template, note, generator_name = _unpack(entry)
                make_value = GENERATORS.get(generator_name, generate)

                if template.count(PLACEHOLDER) != 1:
                    problems.append(
                        f"{risk_type} label={label} {template_index}번 문장에 "
                        f"{PLACEHOLDER}가 {template.count(PLACEHOLDER)}개다 (정확히 1개여야 한다)"
                    )
                    continue

                # 같은 문장에서 나온 것들을 한 묶음으로 표시한다. A가 학습/평가를 나눌 때
                # 이 묶음이 양쪽으로 갈라지지 않게 통째로 한쪽에 넣는다 (데이터 누수 방지).
                group_id = f"{risk_type}_{'true' if label else 'false'}_{template_index:02d}"

                used: set[str] = set()
                for _ in range(RECORDS_PER_TEMPLATE):
                    value = make_value()
                    while value in used:              # 같은 묶음 안에서는 값이 겹치지 않게
                        value = make_value()
                    used.add(value)

                    start = len(template.split(PLACEHOLDER)[0])
                    text = template.replace(PLACEHOLDER, value)
                    record = {
                        "text": text,
                        "type": risk_type,
                        "start": start,
                        "end": start + len(value),
                        "label": label,
                        "group_id": group_id,
                    }
                    if note:
                        record["note"] = note
                    records.append(record)
    return records, problems


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------


def verify(records: list[dict]) -> tuple[list[str], dict[tuple[str, int], dict], list[str]]:
    """규격과 현실성을 둘 다 확인한다.

    1) text[start:end]가 정말 그 값인가          — 틀리면 학습이 엉뚱한 글자를 본다
    2) rules.py가 그 구간을 그 타입 후보로 잡는가 — 안 잡히면 분류기에 들어올 일이 없다

    통계는 (타입, 라벨)별로 따로 센다. 합쳐 세면 어느 칸이 문제인지 알 수 없다.
    """
    errors: list[str] = []
    detection: dict[tuple[str, int], dict] = {}
    missed: list[str] = []

    for record in records:
        text, start, end = record["text"], record["start"], record["end"]
        risk_type, label = record["type"], record["label"]
        stats = detection.setdefault(
            (risk_type, label), {"같은타입": 0, "다른타입": 0, "미탐지": 0}
        )

        value = text[start:end]
        if not value or value.strip() != value:
            errors.append(f"[{risk_type}] start/end가 값과 어긋난다: {text[:20]}...")
            continue

        hits = rules.find_all(text)
        same_span = [h for h in hits if h["start"] == start and h["end"] == end]
        if any(h["field"] == risk_type for h in same_span):
            stats["같은타입"] += 1
        elif same_span:
            stats["다른타입"] += 1
            missed.append(f"{risk_type} label={label} '{value}' -> {same_span[0]['field']}로 잡힘")
        else:
            stats["미탐지"] += 1
            missed.append(f"{risk_type} label={label} '{value}' -> rules.py가 못 잡음")
    return errors, detection, missed


def report(records: list[dict], detection: dict) -> bool:
    """칸별 진행 상황과 검증 결과를 표로 보여준다."""
    ready = True
    print(f"{'타입':<10s}{'라벨':^6s}{'문장':>4s}{'건수':>6s}{'더 필요':>9s}   rules.py 확인")
    print("-" * 72)
    for risk_type, buckets in TEMPLATES.items():
        for label in (1, 0):
            templates = len(buckets.get(label, []))
            count = sum(1 for r in records if r["type"] == risk_type and r["label"] == label)
            short = max(0, target_templates(risk_type, label) - templates)
            if short:
                ready = False
            stats = detection.get((risk_type, label), {})
            detail = ", ".join(f"{k} {v}" for k, v in stats.items() if v) or "-"
            print(f"{risk_type:<10s}{label:^6d}{templates:>4d}{count:>6d}"
                  f"{('문장 +' + str(short)) if short else '충족':>9s}   {detail}")
    print("-" * 72)
    goal = sum(target_templates(t, l) * RECORDS_PER_TEMPLATE
               for t in TEMPLATES for l in (1, 0))
    print(f"총 {len(records)}건 (목표 {goal}건)")
    return ready


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    records, problems = build_records()
    for problem in problems:
        print(f"[문장 오류] {problem}")

    errors, detection, missed = verify(records)
    for error in errors[:10]:
        print(f"[규격 오류] {error}")

    print()
    ready = report(records, detection)
    print()

    gaps = check_known_gaps()
    if gaps:
        print("⚠️ rules.py 미해결 (B-2 확인 필요):")
        for gap in gaps:
            print(f"  - {gap}")
        print()

    if missed:
        # 분류기는 rules.py가 잡은 후보만 넘겨받는다. 여기 뜨는 값은 실제로는
        # 분류기에 들어올 일이 없는 입력이라, 학습 데이터로서 값이 떨어진다.
        print(f"rules.py가 후보로 넘기지 못하는 값 {len(missed)}건 (중복 제외 예시):")
        for line in sorted(set(missed))[:6]:
            print(f"  - {line}")
        print()

    if errors:
        print(f"규격 오류 {len(errors)}건 — 저장하지 않는다.")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.date.today().strftime("%m%d")
    path = os.path.join(OUT_DIR, f"false_positive_{AUTHOR}_{stamp}_{BATCH:03d}.json")
    existed = os.path.exists(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)

    print(f"저장: {os.path.relpath(path, REPO_ROOT)}" + (" (덮어씀)" if existed else ""))
    if not ready:
        print(f"아직 목표 미달이다. 칸마다 문장 {MIN_TEMPLATES}개가 될 때까지 TEMPLATES에 추가할 것.")
        print("(A와 합의해서 목표를 낮춘 칸은 TEMPLATE_TARGET_OVERRIDES에 적는다.)")
        print("완성 전이라도 이대로 A에게 먼저 보내도 된다 — 추가분은 BATCH 번호를 올려서 새 파일로.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
