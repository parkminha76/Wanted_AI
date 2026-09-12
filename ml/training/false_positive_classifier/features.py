"""오탐 제거 분류기의 재사용 가능한 feature 함수.

학습 스크립트를 ``python -m``으로 실행해도 pickle이 함수를
``__main__``으로 기록하지 않도록 별도 모듈에 둔다.
"""

from kiwipiepy import Kiwi


_kiwi = Kiwi()


def tokenize(text: str) -> list[str]:
    """형태소 단위 토큰화. 명사/동사/형용사/외국어/숫자 위주로 필터링한다."""
    tokens = _kiwi.tokenize(text)
    return [token.form for token in tokens if token.tag.startswith(("N", "V", "SL", "SN"))]
