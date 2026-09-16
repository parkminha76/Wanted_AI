"""데이터 보존 정책 실행 — retention.md에 문서로만 있던 삭제 작업을 스크립트로 만든 것.

retention.md가 안내하는 정책 그대로다:
    scan_results(+findings, hidden_commands)  : created_at 기준 30일 지나면 삭제
    training_progress(+training_events)       : completed_at이 있고(=완료됨),
                                                 지정한 기준일보다 오래된 것만 삭제

둘 다 ON DELETE CASCADE가 걸려 있어서(backend/db/tables.py) 부모만 지우면
자식이 DB 레벨에서 자동으로 같이 지워진다 — findings/hidden_commands/
training_events를 따로 지울 필요가 없다.

사용법 (저장소 루트에서):
    python -m backend.db.retention_job                      # 무엇이 지워질지만 보여준다(기본값 = dry-run)
    python -m backend.db.retention_job --execute             # scan_results만 실제로 삭제
    python -m backend.db.retention_job --execute --training-before 2026-10-05
                                                               # + 그 날짜 이전에 완료된 training_progress까지 삭제

training_progress는 날짜를 명시적으로 안 주면 절대 안 지운다 — retention.md의 정책이
"30일" 같은 고정폭이 아니라 "해커톤 데모 종료 시점까지"라서, 스크립트에 아무 날짜나
박아두면 이벤트가 끝나기도 전에 데이터를 지우는 사고가 날 수 있다.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from backend.db.session import SessionLocal
from backend.db.tables import ScanResultRow, TrainingProgress

SCAN_RESULT_RETENTION_DAYS = 30


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="InfoGuard 데이터 보존 정책 실행")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 삭제한다. 안 주면 몇 건이 지워질지만 세어보고 끝낸다(dry-run).",
    )
    parser.add_argument(
        "--training-before",
        metavar="YYYY-MM-DD",
        default=None,
        help="이 날짜 이전에 '완료된' training_progress(+training_events)도 같이 삭제한다. "
        "안 주면 훈련 데이터는 절대 건드리지 않는다.",
    )
    return parser.parse_args()


def run(*, execute: bool, training_before: str | None) -> None:
    db = SessionLocal()
    try:
        scan_deadline = datetime.utcnow() - timedelta(days=SCAN_RESULT_RETENTION_DAYS)
        scan_query = db.query(ScanResultRow).filter(ScanResultRow.created_at < scan_deadline)
        scan_count = scan_query.count()
        print(
            f"[scan_results] created_at < {scan_deadline.isoformat()}Z 인 행 {scan_count}건"
            f" (findings/hidden_commands는 CASCADE로 같이 삭제됨)"
        )

        training_count = 0
        training_deadline: datetime | None = None
        if training_before:
            training_deadline = datetime.strptime(training_before, "%Y-%m-%d")
            training_query = db.query(TrainingProgress).filter(
                TrainingProgress.completed_at.isnot(None),
                TrainingProgress.completed_at < training_deadline,
            )
            training_count = training_query.count()
            print(
                f"[training_progress] completed_at < {training_deadline.date()} 인 완료된 행"
                f" {training_count}건 (training_events는 CASCADE로 같이 삭제됨)"
            )
        else:
            print("[training_progress] --training-before를 안 줘서 건드리지 않음")

        if not execute:
            print("\ndry-run이었습니다. 실제로 지우려면 --execute를 붙이세요.")
            return

        if scan_count:
            scan_query.delete(synchronize_session=False)
        if training_deadline is not None and training_count:
            training_query.delete(synchronize_session=False)
        db.commit()
        print(f"\n삭제 완료: scan_results {scan_count}건, training_progress {training_count}건")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    args = _parse_args()
    run(execute=args.execute, training_before=args.training_before)


if __name__ == "__main__":
    main()
