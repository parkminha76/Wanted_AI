"""임계값 점검 — 숨긴 문서와 정상 문서를 한 번에 돌려 놓침/오탐을 센다.

    uv run python backend/scanner/tests/check_thresholds.py

읽는 법
-------
    hidden/  탐지 0건이면 **놓침**  (그물이 성글다 -> 임계값을 내린다)
    clean/   탐지 1건 이상이면 **오탐** (그물이 촘촘하다 -> 임계값을 올린다)

목표는 **놓침 0 / 오탐 0**이다. 둘이 동시에 나오면 숫자로는 가를 수 없다는 뜻이고,
그때는 임계값이 아니라 조건을 하나 더 달아야 한다 (복원 검사, 이모지 예외 같은 것).

임계값을 고칠 곳은 `backend/scanner/detectors/hidden.py` 맨 위다.
한 번에 하나만 바꾸고 이 스크립트를 다시 돌린다. 두 개를 같이 바꾸면 무엇이
효과가 있었는지 알 수 없다.

원문은 찍지 않는다. 탐지 건수와 근거 이름만 나온다 (팀 규칙 2).
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.scanner.detectors import hidden          # noqa: E402
from backend.scanner.parser import parse              # noqa: E402

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
HIDDEN_DIR = os.path.join(TESTS_DIR, "hidden")
CLEAN_DIR = os.path.join(TESTS_DIR, "clean")


def _thresholds() -> str:
    return (
        f"A급 개수 >= {hidden.INVISIBLE_A_MIN_COUNT} | "
        f"B급 개수 >= {hidden.INVISIBLE_B_MIN_COUNT} 또는 밀도 > "
        f"{hidden.INVISIBLE_B_MAX_DENSITY:.0%} (span {hidden.INVISIBLE_DENSITY_MIN_LENGTH}자 이상) "
        f"+ 복원 통과 | 색 거리 < {hidden.COLOR_DISTANCE_THRESHOLD} | "
        f"글자 < {hidden.MIN_READABLE_FONT_SIZE}pt"
    )


def _run(path: str) -> list[dict]:
    doc = parse.load(path)
    if doc.spans:
        return hidden.detect(doc.spans)
    return hidden.detect_text(doc.raw_text)


def _signal_names(findings: list[dict]) -> str:
    names: list[str] = []
    for finding in findings:
        for name in finding.get("evidence", {}).get("signals", []):
            if name not in names:
                names.append(name)
    return ", ".join(names)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not os.path.isdir(HIDDEN_DIR):
        print("샘플이 없다. 먼저 만들 것: uv run python backend/scanner/tests/make_samples.py")
        return 2

    print(f"임계값: {_thresholds()}\n")

    misses: list[str] = []
    false_positives: list[str] = []

    print("=== hidden/ — 잡아야 한다 ===")
    for name in sorted(os.listdir(HIDDEN_DIR)):
        findings = _run(os.path.join(HIDDEN_DIR, name))
        if findings:
            print(f"  [잡음] {name:36s} {len(findings)}건  {_signal_names(findings)}")
        else:
            misses.append(name)
            print(f"  [놓침] {name:36s} 0건  <- 임계값을 내려야 한다")

    print("\n=== clean/ — 잡으면 안 된다 ===")
    for name in sorted(os.listdir(CLEAN_DIR)):
        findings = _run(os.path.join(CLEAN_DIR, name))
        if findings:
            false_positives.append(name)
            print(f"  [오탐] {name:36s} {len(findings)}건  {_signal_names(findings)}"
                  f"  <- 임계값을 올리거나 조건을 달아야 한다")
        else:
            print(f"  [통과] {name:36s} 0건")

    total_hidden = len(os.listdir(HIDDEN_DIR))
    total_clean = len(os.listdir(CLEAN_DIR))
    print(
        f"\n놓침 {len(misses)}/{total_hidden}건 · 오탐 {len(false_positives)}/{total_clean}건"
    )
    if misses or false_positives:
        print("아직 통과가 아니다. hidden.py 맨 위의 임계값을 하나만 고치고 다시 돌린다.")
        return 1

    print("통과. 이 값과 오늘 날짜를 backend/scanner/tests/README.md에 적어 둘 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
