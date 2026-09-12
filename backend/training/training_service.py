from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.db.tables import TrainingProgress, TrainingEvent
from backend.db.converters import record_training_event
from backend.scanner.scan import scan_text


def start_training(
    db: Session,
    user_id: int,
    level: int,
) -> TrainingProgress:
    """
    Training Mode 시작.

    사용자가 레벨을 선택하면 TrainingProgress를 생성하고
    진행 상태를 "진행중"으로 저장한다.
    """

    progress = TrainingProgress(
        user_id=user_id,
        level=level,
        status="진행중",
        score=0,
    )

    db.add(progress)
    db.commit()
    db.refresh(progress)

    return progress


def handle_user_reply(
    db: Session,
    training_progress_id: int,
    turn_no: int,
    user_reply: str,
):
    """
    사용자의 답장을 검사하고 TrainingEvent로 기록한다.

    처리 흐름:
    1. 실제 scanner의 scan_text()로 사용자 답장 검사
    2. ScanResult finalize()
    3. 위험 정보가 있으면 우선 action="경고표시"
    4. record_training_event()로 비식별 정보만 DB 저장
    5. ScanResult 반환

    주의:
    - 사용자 원문 자체는 DB에 저장하지 않는다.
    - 원문은 이 함수 실행 중에만 사용된다.
    """

    # 1. 사용자 답장 검사
    result = scan_text(user_reply)
    result.finalize()

    # 2. 탐지 결과에 따른 기본 action
    if result.findings:
        action = "경고표시"
        event_result = result
    else:
        action = None
        event_result = None

    # 3. 비식별 TrainingEvent 저장
    record_training_event(
        db=db,
        training_progress_id=training_progress_id,
        turn_no=turn_no,
        result=event_result,
        action=action,
    )

    db.commit()

    return result


def update_training_action(
    db: Session,
    training_progress_id: int,
    turn_no: int,
    action: str,
) -> TrainingEvent:
    """
    경고 표시 이후 사용자의 최종 선택을 저장한다.

    허용 action:
    - "취소"
    - "전송강행"

    같은 turn_no로 새 이벤트를 만들지 않고,
    기존 TrainingEvent의 action만 수정한다.
    """

    allowed_actions = {"취소", "전송강행"}

    if action not in allowed_actions:
        raise ValueError(
            f"허용되지 않은 action입니다: {action}. "
            f"허용값: {allowed_actions}"
        )

    event = (
        db.query(TrainingEvent)
        .filter_by(
            training_progress_id=training_progress_id,
            turn_no=turn_no,
        )
        .one()
    )

    event.action = action

    db.commit()
    db.refresh(event)

    return event


def calculate_training_score(
    db: Session,
    training_progress_id: int,
) -> int:
    """
    TrainingEvent 기록을 기반으로 최종 점수를 계산한다.

    현재 임시 점수 규칙:
    - 100점에서 시작
    - "전송강행"  : -20점
    - "경고표시"  : -10점
    - "취소"      : 감점 없음
    - action=None : 감점 없음

    최저 점수는 0점.
    """

    events = (
        db.query(TrainingEvent)
        .filter_by(training_progress_id=training_progress_id)
        .order_by(TrainingEvent.turn_no)
        .all()
    )

    score = 100

    for event in events:
        if event.action == "전송강행":
            score -= 20

        elif event.action == "경고표시":
            score -= 10

    return max(score, 0)


def finish_training(
    db: Session,
    training_progress_id: int,
    final_score: int | None = None,
) -> TrainingProgress:
    """
    Training Mode 종료.

    final_score가 전달되지 않으면
    calculate_training_score()를 이용해 자동 계산한다.

    TrainingProgress 상태를 "완료"로 변경하고
    최종 점수와 종료 시간을 저장한다.
    """

    progress = (
        db.query(TrainingProgress)
        .filter_by(id=training_progress_id)
        .one()
    )

    # 점수를 직접 전달하지 않았다면 자동 계산
    if final_score is None:
        final_score = calculate_training_score(
            db=db,
            training_progress_id=training_progress_id,
        )

    progress.status = "완료"
    progress.score = final_score
    progress.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(progress)

    return progress