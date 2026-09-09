"""
Custom Generator — Faker가 못 커버하는 필드 생성
==================================================

Faker(ko_KR)가 커버 못 하는 4개 필드를 직접 생성한다:
  - 운전면허번호  (형식만 검증 가능 — 체크섬 알고리즘 비공개)
  - 외국인등록번호 (체크섬 검증 가능)
  - 사업자등록번호 (체크섬 검증 가능)
  - 계좌번호       (은행별 자릿수만 존재, 체크섬 없음)

담당: A. validators.py와 세트로 관리한다 — 생성 함수는 전부 validators.py를
거쳐서 "형식/체크섬이 맞는 값만" 반환한다. 검증 없이 값을 만들면 신분증 CNN
학습 데이터에 애초에 무효한 값이 섞여 들어간다.
"""

from __future__ import annotations

import random

from ml.data_generation.validators import (
    BANK_ACCOUNT_DIGIT_LENGTHS,
    VALID_LICENSE_REGION_CODES,
    validate_account_length,
    validate_biz_reg,
    validate_driver_license_format,
    validate_foreign_reg,
)


# ---------------------------------------------------------------------------
# 사업자등록번호 — 체크섬을 만족하는 값을 직접 역산해서 생성 (재시도 불필요)
# ---------------------------------------------------------------------------

def generate_biz_reg() -> str:
    """XXX-XX-XXXXX. 앞 9자리를 무작위로 만들고 체크섬(10번째 자리)을 역산한다."""
    front9 = [random.randint(0, 9) for _ in range(9)]
    # 국세청 코드 관례상 4~5번째 자리(사업자 구분코드)는 01~99 범위지만
    # 학습 데이터 다양성 목적이므로 완전 무작위로 둔다.

    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(d * w for d, w in zip(front9, weights))
    total += (front9[8] * 5) // 10
    check = (10 - total % 10) % 10

    digits = front9 + [check]
    number = f"{''.join(map(str, digits[0:3]))}-{''.join(map(str, digits[3:5]))}-{''.join(map(str, digits[5:10]))}"

    assert validate_biz_reg(number), f"생성 로직 오류: {number}"  # 역산이므로 항상 통과해야 함
    return number


# ---------------------------------------------------------------------------
# 외국인등록번호 — 생년월일 + 성별코드는 의미 있게, 나머지는 역산
# ---------------------------------------------------------------------------

def generate_foreign_reg(birth_year: int | None = None) -> str:
    """XXXXXX-XXXXXXX. 앞 6자리는 생년월일(YYMMDD), 7번째는 외국인 성별코드(5/6/7/8)."""
    if birth_year is None:
        birth_year = random.randint(1960, 2005)

    yy = birth_year % 100
    mm = random.randint(1, 12)
    dd = random.randint(1, 28)  # 월별 일수 차이는 학습 데이터 다양성에 큰 영향 없어 28로 고정
    front6 = f"{yy:02d}{mm:02d}{dd:02d}"

    gender_code = random.choice([5, 6] if birth_year < 2000 else [7, 8])

    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    serial5 = [random.randint(0, 9) for _ in range(5)]
    digits = [int(c) for c in front6] + [gender_code] + serial5 + [0]
    total = sum(d * w for d, w in zip(digits[:12], weights))
    check = (11 - total % 11) % 10
    digits[12] = check

    number = f"{''.join(map(str, digits[0:6]))}-{''.join(map(str, digits[6:13]))}"

    assert validate_foreign_reg(number), f"생성 로직 오류: {number}"
    return number


# ---------------------------------------------------------------------------
# 운전면허번호 — 체크섬 알고리즘이 비공개라 형식(자릿수/지역코드)만 맞춰 생성
# ---------------------------------------------------------------------------

def generate_driver_license() -> str:
    """XX-XX-XXXXXX-XX. 뒤 2자리(검증번호)는 실제 알고리즘을 모르므로 무작위.

    학습용 합성 이미지에만 쓰는 값이라 실제 발급 시스템 검증을 통과할 필요는
    없다 — validate_driver_license_format()이 확인하는 건 자릿수/지역코드
    유효 범위뿐이다.
    """
    region = random.choice(sorted(VALID_LICENSE_REGION_CODES))
    year = f"{random.randint(0, 99):02d}"
    serial = f"{random.randint(0, 999999):06d}"
    check = f"{random.randint(0, 99):02d}"  # 실제 검증번호 산출 불가 — 무작위

    number = f"{region}-{year}-{serial}-{check}"

    assert validate_driver_license_format(number), f"생성 로직 오류: {number}"
    return number


# ---------------------------------------------------------------------------
# 계좌번호 — 은행별 자릿수에 맞춰 무작위 숫자 채우기 (체크섬 없음)
# ---------------------------------------------------------------------------

def generate_account(bank: str | None = None) -> tuple[str, str]:
    """(계좌번호, 은행명) 반환. bank 지정 안 하면 무작위로 은행도 같이 고른다.

    포맷은 은행마다 하이픈 위치가 다르므로 여기서는 하이픈 없이 순수 자릿수만
    만들고, 화면/문서에 넣을 때 하이픈은 호출부에서 원하는 스타일로 넣는다.
    """
    if bank is None:
        bank = random.choice(list(BANK_ACCOUNT_DIGIT_LENGTHS.keys()))

    length = BANK_ACCOUNT_DIGIT_LENGTHS[bank]
    number = "".join(str(random.randint(0, 9)) for _ in range(length))

    assert validate_account_length(number, bank), f"생성 로직 오류: {number} ({bank})"
    return number, bank

# 중복 검사
_USED_NUMBERS: set[str] = set()

def generate_biz_reg_unique() -> str:
    while True:
        number = generate_biz_reg()
        if number not in _USED_NUMBERS:
            _USED_NUMBERS.add(number)
            return number


# ---------------------------------------------------------------------------
# 자체 테스트 — 각 함수를 여러 번 돌려서 항상 검증을 통과하는지 확인
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    N = 1000

    for _ in range(N):
        biz = generate_biz_reg()
        assert validate_biz_reg(biz)
    print(f"사업자등록번호 {N}건 생성 및 검증 통과. 예시: {generate_biz_reg()}")

    for _ in range(N):
        fr = generate_foreign_reg()
        assert validate_foreign_reg(fr)
    print(f"외국인등록번호 {N}건 생성 및 검증 통과. 예시: {generate_foreign_reg()}")

    for _ in range(N):
        dl = generate_driver_license()
        assert validate_driver_license_format(dl)
    print(f"운전면허번호 {N}건 생성 및 형식 통과. 예시: {generate_driver_license()}")

    for _ in range(N):
        acc, bank = generate_account()
        assert validate_account_length(acc, bank)
    acc, bank = generate_account()
    print(f"계좌번호 {N}건 생성 및 자릿수 통과. 예시: {acc} ({bank})")

    print("\n모든 생성 함수 검증 통과")