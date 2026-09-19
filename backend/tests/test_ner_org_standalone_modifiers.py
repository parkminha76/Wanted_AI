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


if __name__ == "__main__":
    unittest.main()
