"""find_all 안의 not_overlapping이 O(후보 수 × claimed 수)였던 문제를 고친다.

실측(2026-09-20, DocXray_합성데이터_5MB.log 2MB 슬라이스): 계좌번호 후보
9,941건마다 이미 확정된 탐지 16,723건 전체를 선형으로 훑어 19.00초가 걸렸다
(claimed를 시작 위치로 정렬하고 접두사 최댓값을 이진 탐색하는 구조로 바꿔
19.00초 -> 수십 ms대로 줄었다). 전체 파일(4.4MB) 기준 rules.find_all
자체가 105초 -> 4.29초로 줄었다.

이 파일은 (1) 겹침 제외 로직이 여전히 올바른 값만 남기는지 정확성을
확인하고, (2) 텍스트가 커질 때 시간이 대략 선형으로 늘어나는지(제곱으로
악화되지 않는지) 확인한다.
"""

from __future__ import annotations

import time
import unittest

from backend.scanner.detectors import rules


class NotOverlappingCorrectnessTest(unittest.TestCase):
    def test_business_registration_number_is_not_shadowed_by_account_number(self) -> None:
        """사업자등록번호(체크섬 통과, 우선순위 높음)가 같은 자리를 잡는 계좌번호
        후보에 밀려나면 안 된다 — find_all 자체 docstring이 설명하는 실측 버그."""
        text = "사업자등록번호는 123-45-67891 입니다."
        findings = rules.find_all(text)
        types_at_span = {f["field"] for f in findings if f["start"] <= text.index("123-45-67891")}
        self.assertIn("biz_reg", types_at_span)
        self.assertNotIn("account", types_at_span)

    def test_non_overlapping_account_number_still_detected(self) -> None:
        """다른 탐지기와 안 겹치는 진짜 계좌번호 후보는 여전히 통과해야 한다."""
        text = "계좌번호 512-55-9401-22268 로 입금해 주세요."
        findings = rules.find_all(text)
        self.assertTrue(any(f["field"] == "account" for f in findings))


class NotOverlappingScalingTest(unittest.TestCase):
    def test_time_grows_roughly_linearly_not_quadratically(self) -> None:
        """500줄과 4000줄(8배) 사이에서, 제곱이면 ~64배, 선형이면 ~8배 늘어야 한다.
        예전 O(n²) 구조에서는 이 비율이 수십 배로 나왔다(실측 위 docstring 참고)."""

        def make_text(n_lines: int) -> str:
            return "\n".join(
                f"{i:08x} phone=010-{i % 10000:04d}-0000 email=user{i}@example.com "
                f"account=512-55-{i % 100000:05d}-{(i * 7) % 100000:05d}"
                for i in range(n_lines)
            )

        small = make_text(500)
        large = make_text(4000)  # 8x

        t0 = time.time()
        rules.find_all(small)
        small_time = time.time() - t0

        t0 = time.time()
        rules.find_all(large)
        large_time = time.time() - t0

        # 8배 입력에 20배 이상 시간이 걸리면(제곱이면 64배) 다시 O(n²)로
        # 되돌아간 것으로 본다. 노이즈가 있는 소규모 벤치라 넉넉히 잡는다.
        self.assertLess(
            large_time,
            max(small_time * 20, 2.0),
            f"small={small_time:.3f}s large={large_time:.3f}s — 다시 제곱 시간대로 보임",
        )


if __name__ == "__main__":
    unittest.main()
