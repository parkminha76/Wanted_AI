"""오탐 제거 분류기에 **문장 안 정확한 위치**가 전달되는지 점검.

    uv run python backend/scanner/tests/classifier_position_check.py

왜 필요한가
-----------
분류기의 핵심 feature는 값을 `__VALUE__`로 바꿔치기한 문장이다
(`false_positive_filter.mask_candidate`). 그래서 **자리가 틀리면 모델이 아예 다른
문장을 본다.**

    정답   "입금 계좌는 __VALUE__ 이고 전표번호 512-55-9401-22268 은 회계 참조용입니다"
    틀림   "입금 계좌는 512-55-9401-22268 이고 전표번호 __VALUE__ 은 회계 참조용입니다"

`models.filter_false_positive`가 start/end를 인자로 받지 않고 `context.find(text)`로
다시 찾으면, 같은 값이 한 문장에 두 번 나올 때 **두 번째가 첫 번째 자리로 판정된다.**

학습 때는 이런 일이 없다 — 학습 데이터가 start/end를 필수로 들고 있고
(`load_training_data`의 assert), 그 값을 그대로 쓴다. 즉 학습과 추론이 어긋난다.

무엇을 보는가
-------------
내부 함수 시그니처가 아니라 **모델이 실제로 받은 문장**을 본다. `predict_proba`를
가로채서 `__VALUE__`가 어디에 찍혔는지 확인하므로, `_sentence_around`나
`filter_false_positive`의 인자가 어떻게 바뀌어도 이 점검은 그대로 돈다.

원문은 찍지 않는다 — 여기 쓰는 값은 전부 합성이다 (팀 규칙 2).
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.scanner import scan                      # noqa: E402
from backend.scanner.detectors import models          # noqa: E402

_failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  - ' + detail if detail else ''}")
    if not ok:
        _failures.append(label)


# 같은 계좌번호가 한 문장에 두 번. 앞은 진짜 입금 계좌, 뒤는 회계 참조번호다.
# 마침표가 없어서 문장이 쪼개지지 않는다 — 표·목록형 문서에서 흔한 모양이다.
ACCOUNT = "512-55-9401-22268"
SENTENCE = f"입금 계좌는 {ACCOUNT} 이고 전표번호 {ACCOUNT} 은 회계 참조용입니다"


def _positions(text: str, value: str) -> list[int]:
    out, at = [], text.find(value)
    while at >= 0:
        out.append(at)
        at = text.find(value, at + 1)
    return out


def _run_and_capture(text: str):
    """scan_text를 돌리면서 모델이 받은 (문장, start, end)를 모은다."""
    model = models._get_false_positive_model()
    seen: list[tuple[str, int, int]] = []
    original = model.predict_proba

    def spy(sentence, risk_type, start, end):
        seen.append((sentence, start, end))
        return original(sentence, risk_type, start, end)

    model.predict_proba = spy
    try:
        result = scan.scan_text(text)
    finally:
        model.predict_proba = original
    return result, seen


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if models._get_false_positive_model() is None:
        print("오탐 제거 모델이 없다. ml/models/fp_filter_v1.pkl을 만든 뒤 다시 돌릴 것.")
        return 2
    if not models.false_positive_model_ready("account"):
        print("모델이 account를 학습하지 않았다. 이 점검은 account로 한다.")
        return 2

    spots = _positions(SENTENCE, ACCOUNT)
    print(f"\n[1] 같은 값이 한 문장에 두 번 (자리 {spots[0]}, {spots[1]})")
    check(len(spots) == 2, "같은 값이 두 번 들어 있다", f"{len(spots)}번")

    result, seen = _run_and_capture(SENTENCE)
    found = sorted(
        [f for f in list(result.findings) + list(result.filtered_out) if f.type == "account"],
        key=lambda f: f.start,
    )
    check(len(found) == 2, "두 건 모두 후보로 잡힌다", f"{len(found)}건")
    if len(found) != 2:
        return 1
    check([f.start for f in found] == spots,
          "Finding.start가 각각 제 자리를 가리킨다", str([f.start for f in found]))

    print("\n[2] 모델이 받은 문장에서 __VALUE__가 제 자리에 오는가")
    check(len(seen) == 2, "모델이 두 건 모두에 대해 불렸다", f"{len(seen)}번")
    if len(seen) != 2:
        return 1

    from ml.training.false_positive_classifier.false_positive_filter import mask_candidate

    heads = []
    for sentence, start, end in seen:
        sliced = sentence[start:end] if 0 <= start < end <= len(sentence) else ""
        masked = mask_candidate(sentence, start, end) if sliced else ""
        head = masked.split("__VALUE__")[0].strip().split()[-1] if masked else "?"
        heads.append(head)
        print(f"        start/end=({start},{end}) -> 잘라보면 {sliced!r} / __VALUE__ 앞 단어 {head!r}")
        check(sliced == ACCOUNT, f"({start},{end})가 실제 값을 가리킨다", sliced or "빈 값")

    check(heads[0] != heads[1],
          "두 건의 __VALUE__ 자리가 다르다",
          f"{heads[0]} vs {heads[1]}"
          + ("  <- 같다. 두 번째가 첫 번째 자리로 판정되고 있다" if heads[0] == heads[1] else ""))

    print("\n[3] 두 건의 판정이 실제로 갈리는가")
    probs = [f.evidence.get("prob_positive") for f in found]
    print(f"        앞(입금 계좌)   확률 {probs[0]}  -> {'살림' if found[0] in result.findings else '걸러짐'}")
    print(f"        뒤(전표번호)   확률 {probs[1]}  -> {'살림' if found[1] in result.findings else '걸러짐'}")
    check(probs[0] != probs[1], "앞뒤 문맥이 다르므로 확률도 달라야 한다",
          f"{probs[0]} vs {probs[1]}")

    print("\n[4] 문장 경계를 못 찾는 긴 문서에서도 자리가 유지되는가")
    long_text = f"계좌 {ACCOUNT} 로 보냈습니다 " + "가" * 400 + f" 참조 {ACCOUNT} 끝"
    _, seen_long = _run_and_capture(long_text)
    tail_ok = False
    for sentence, start, end in seen_long:
        if sentence[start:end] == ACCOUNT and start > 100:
            tail_ok = True
    check(tail_ok,
          "뒤쪽 값이 자기 자리로 판정된다",
          "" if tail_ok else "잘라낸 문맥에 값이 두 번 들어 있어 앞쪽으로 밀렸다")

    print()
    if _failures:
        print(f"실패 {len(_failures)}건:")
        for name in _failures:
            print(f"  - {name}")
        print("\n고치는 방법은 이 파일 맨 위 docstring 참고.")
        return 1
    print("전부 통과 — 분류기에 문장 안 정확한 위치가 전달된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
