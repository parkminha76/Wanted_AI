"""rules.API_KEY_OR_TOKEN_PATTERN의 ghp_(GitHub 토큰) 길이 조건을 확인한다.

실측(2026-09-19, 개발문서.md): 정규식이 접두어 뒤 정확히 36자(`{36}`)만 받았는데,
데모용 더미 값이 32자라 정확히 안 맞아서 놓쳤다. sk-처럼 최소 길이만 보게
(`{36,}`) 바꿨다 — 진짜 GitHub 토큰(접두어 뒤 36자)은 그대로 잡히고, 그보다
길어도 놓치지 않는다.
"""

from __future__ import annotations

import unittest

from backend.scanner.detectors import rules


class GithubTokenLengthTest(unittest.TestCase):
    def test_exact_length_token_is_still_matched(self) -> None:
        token = "ghp_" + "a" * 36
        self.assertTrue(rules.API_KEY_OR_TOKEN_PATTERN.fullmatch(token))

    def test_longer_token_is_matched_too(self) -> None:
        token = "ghp_" + "a" * 40
        self.assertTrue(rules.API_KEY_OR_TOKEN_PATTERN.fullmatch(token))

    def test_shorter_value_is_not_matched(self) -> None:
        """32자짜리 더미 값처럼 접두어 뒤가 36자 미만이면 여전히 안 잡는다 —
        진짜 GitHub 토큰 형식이 아니므로 늘려 받으면 안 된다."""
        token = "ghp_" + "a" * 32
        self.assertIsNone(rules.API_KEY_OR_TOKEN_PATTERN.fullmatch(token))


if __name__ == "__main__":
    unittest.main()
