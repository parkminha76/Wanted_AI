"""ner.detect()가 학교명을 조직명(org)으로 마스킹하지 않는지 확인한다.

사용자 결정(2026-09-17): 학교명은 전화번호·주소처럼 연락·사칭 위험으로 이어지지
않고 이력서에 흔히 공개되는 정보라 마스킹 대상에서 뺐다. 또한 NER이 회사명과
학교명을 구분 없이 "조직명" 태그로 잡다 보니 같은 문서에서 "신안산대학교"는
잡히고 "안산고등학교"는 안 잡히는 등 들쭉날쭉했는데, 학교명 자체를 빼면 이
비일관성도 같이 사라진다.
"""

from __future__ import annotations

import unittest

from backend.scanner.detectors import ner


class NerSchoolExclusionTest(unittest.TestCase):
    def test_university_and_high_school_are_not_flagged_as_org(self) -> None:
        text = "학력사항 학교명 기간 전공 안산고등학교 2016년 3월 - 2019년 2월 인문계 졸업 신안산대학교 2019년 3월 - 2021년 2월 식품위생학과 학사 졸업"
        findings = ner.detect(text)
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertFalse(
            any("안산고등학교" in value or "안산대학교" in value for value in org_values),
            f"학교명이 조직명으로 잡혔다: {org_values}",
        )

    def test_real_company_names_are_still_flagged(self) -> None:
        """학교명만 뺀 것이지, 진짜 회사명까지 같이 죽이면 안 된다(회귀 방지)."""
        text = "2022 - 2023 Liceria & Co. 비 디자인 디자인팀"
        findings = ner.detect(text)
        org_values = [f["value"] for f in findings if f["field"] == "org"]
        self.assertTrue(
            any("Liceria" in value for value in org_values),
            f"회사명이 학교명 필터에 같이 걸러졌다: {org_values}",
        )

    def test_truncated_school_entity_is_still_excluded(self) -> None:
        """실측 버그: NER이 "신안산대학교"의 꼬리("학교")를 잘라 "신안산대"만
        개체로 내놓는 경우가 있다. 잡힌 범위 뒤에 "학교"가 바로 이어지면
        마찬가지로 학교명으로 보고 뺀다(`_is_education_institution`)."""
        self.assertTrue(ner._is_education_institution("신안산대학교", 0, 4))
        self.assertFalse(ner._is_education_institution("Liceria & Co.", 0, 7))


if __name__ == "__main__":
    unittest.main()
