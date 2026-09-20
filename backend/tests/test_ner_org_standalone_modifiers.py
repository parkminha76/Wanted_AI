"""ner.detect()가 "공인"처럼 단독으로는 뜻이 안 서는 수식어를 조직명(org)으로
잘못 잡지 않는지 확인한다.

실측(2026-09-18, 저해상도 이력서 사진 865f267df9c220bf.jpg): "자격증" 섹션의
자격증 이름이 OCR로 "공인 임어시럽"처럼 깨져 읽혔는데, 모델이 그 문맥에서
"공인"만 떼어 회사명으로 오판했다(확신도 0.401). 신뢰도로 거르면 안 된다 —
같은 실측에서 진짜 회사명 "네이버"도 0.364로 이보다 낮게 나왔다.
"""

from __future__ import annotations

import unittest

from backend.scanner.detectors import ner


class NerOrgStandaloneModifierExclusionTest(unittest.TestCase):
    def test_standalone_modifier_word_is_not_flagged_as_org(self) -> None:
        """실측 재현: 해당 문서의 전체 raw_text 그대로 넣었을 때 재현된다
        (짧은 문장만 따로 넣으면 이 문맥 의존적인 오탐이 재현되지 않는다)."""
        text = (
            "이력서 이수민 1996.05.24 전화번호 123-456-7890\n"
            "123 Anywhere SL; Ary City ST 12345\n"
            "hellooreallyErcatsite\n"
            "'화력사항 기간 확교명 학위\n"
            "2019.03 2021 대학교 시각디지민\n"
            "2015.03 - 2019.02 대략교 시각디자인\n"
            "2015,02 고등사교\n"
            "경력사항 기간 2024 * 2025 FauBct 디자인터\n"
            "2022 2023 Liceria 디자인림\n"
            "2020 - 2021 프로모신 디자인\n"
            "2019 2020 Salford 디자인터\n"
            "자격증 수상 및 기타 능력\n"
            "공인 임어시럽 900점 2025.12\n"
            "디자인 공모진 우수상 2024.11"
        )
        findings = ner.detect(text)
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertNotIn("공인", org_values)

    def test_real_company_names_are_still_flagged(self) -> None:
        """"공인"만 뺀 것이지, 진짜 회사명까지 같이 죽이면 안 된다(회귀 방지)."""
        text = "카카오 계열사에서 백엔드 개발을 담당했습니다."
        findings = ner.detect(text)
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertTrue(
            any("카카오" in value for value in org_values),
            f"회사명이 필터에 같이 걸러졌다: {org_values}",
        )

    def test_modifier_as_a_prefix_of_a_longer_word_is_not_excluded(self) -> None:
        """"공인"이 값의 일부일 뿐 정확히 그 값 전체가 아니면(예: 모델이 어쩌다
        "공인중개사"를 통째로 회사명처럼 잡은 극단적인 경우) 이 필터가 손대면
        안 된다 — 정확히 일치할 때만 뺀다."""
        self.assertNotIn("공인중개사", ner._ORG_STANDALONE_MODIFIERS)


class NerContractClauseLabelExclusionTest(unittest.TestCase):
    """실측(2026-09-20, docX-ray 배포본): 계약서류 곳곳에서 짧은 업무 용어가
    회사명으로 반복 오탐됐다 — 표 라벨("법인카드"·"검수"), 표 값("변경 건에
    한함"), 마크다운 메타데이터("**대상 환경:** staging"), 법률 조항 제목
    ("제1조 (목적)", "제2조 (정산)") 순으로 문서 구조를 바꿔가며 계속
    발견됐다(매번 신뢰도 0.90 이상이라 확신도 문턱도 못 거름). 재학습으로
    구조 하나씩 쫓는 대신 확정 오탐 단어를 직접 차단한다."""

    def test_contract_article_title_words_are_not_flagged_as_org(self) -> None:
        text = (
            "제1조 (목적)\n"
            "본 계약은 갑(위탁자)과 을(수탁자) 사이의 데이터 처리 위탁 업무 범위와 "
            "책임을 정하는 것을 목적으로 한다.\n"
            "제2조 (정산)\n"
            "정산은 매월 말일을 기준으로 산정하며, 익월 10일에 위 계좌로 지급한다."
        )
        findings = ner.detect(text)
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertNotIn("목적", org_values)
        self.assertNotIn("정산", org_values)

    def test_markdown_metadata_label_is_not_flagged_as_org(self) -> None:
        findings = ner.detect("**대상 환경:** staging")
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertNotIn("대상 환경", org_values)

    def test_loanword_jargon_is_not_flagged_as_org(self) -> None:
        """실측(2026-09-20): "레거시"(0.91~0.92)·"스프린트"(0.919)도 회사명으로
        잘못 잡혔다 — 둘 다 외래어 차용어라 실제로 음역된 회사명(네이버·구글 등)과
        모델 입장에서 형태가 비슷해 confidence로는 못 가른다."""
        text = (
            "레거시 주문번호 419503-3127627 이관 완료\n"
            "신규 기능 배포 일정은 다음 스프린트 계획 회의에서 확정합니다."
        )
        findings = ner.detect(text)
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertNotIn("레거시", org_values)
        self.assertNotIn("스프린트", org_values)

    def test_real_company_names_survive_the_blocklist(self) -> None:
        """새로 추가한 단어들이 진짜 회사명까지 같이 죽이면 안 된다(회귀 방지)."""
        text = "발주사 블루웨이브 솔루션 주식회사"
        findings = ner.detect(text)
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertTrue(
            any("블루웨이브" in value for value in org_values),
            f"회사명이 필터에 같이 걸러졌다: {org_values}",
        )


if __name__ == "__main__":
    unittest.main()
