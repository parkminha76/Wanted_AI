"""3-3-7 계좌번호가 내부 사업자등록번호 부분 매칭에 밀리지 않는지 확인한다."""

import unittest

from backend.scanner.detectors import rules


class Account337PatternTest(unittest.TestCase):
    def test_full_account_wins_over_valid_biz_reg_suffix(self):
        # 뒤의 123-4567891은 단독으로 쓰면 체크섬이 유효한 사업자등록번호다.
        value = "999-123-4567891"
        text = f"입금 계좌는 {value}입니다"

        findings = rules.find_all(text)

        self.assertTrue(
            any(f["field"] == "account" and f["value"] == value for f in findings)
        )
        self.assertFalse(any(f["field"] == "biz_reg" for f in findings))

    def test_standalone_business_registration_number_still_matches(self):
        value = "123-45-67891"
        findings = rules.find_all(f"사업자등록번호는 {value}입니다")

        self.assertTrue(
            any(f["field"] == "biz_reg" and f["value"] == value for f in findings)
        )


if __name__ == "__main__":
    unittest.main()
