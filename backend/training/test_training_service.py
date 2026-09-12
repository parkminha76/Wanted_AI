from backend.db.session import SessionLocal
from backend.db.tables import User, TrainingEvent

from src.training.training_service import (
    start_training,
    handle_user_reply,
    update_training_action,
    calculate_training_score,
    finish_training,
)

from src.training.defender import generate_defender_report


def get_or_create_test_user(db):
    """
    기존 User가 있으면 사용하고,
    없으면 테스트용 User를 하나 생성한다.
    """

    user = db.query(User).first()

    if user is None:
        print("기존 User가 없어 테스트용 User를 생성합니다.")

        user = User(
            role="individual"
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"테스트 User 생성 완료: user_id = {user.id}")

    else:
        print(f"기존 User 사용: user_id = {user.id}")

    return user


def print_events(db, training_progress_id):
    """
    현재 TrainingEvent 기록을 출력한다.
    """

    events = (
        db.query(TrainingEvent)
        .filter_by(training_progress_id=training_progress_id)
        .order_by(TrainingEvent.turn_no)
        .all()
    )

    print("\n[TrainingEvent 확인]")
    print(f"이벤트 개수 = {len(events)}")

    for event in events:
        print(
            f"Turn {event.turn_no} | "
            f"Action: {event.action} | "
            f"Detected: {event.detected_field}"
        )

    return events


def main():
    db = SessionLocal()

    try:
        print("=== Training Mode 전체 흐름 테스트 시작 ===")

        # ---------------------------------
        # 1. 테스트 User 확보
        # ---------------------------------
        user = get_or_create_test_user(db)

        # ---------------------------------
        # 2. Training 시작
        # ---------------------------------
        progress = start_training(
            db=db,
            user_id=user.id,
            level=2,
        )

        print("\n[Training 시작]")
        print(f"training_progress_id = {progress.id}")
        print(f"level = {progress.level}")
        print(f"status = {progress.status}")
        print(f"score = {progress.score}")

        # ---------------------------------
        # 3. Turn 1
        # 위험 정보 입력
        # ---------------------------------
        print("\n[Turn 1 검사]")

        result1 = handle_user_reply(
            db=db,
            training_progress_id=progress.id,
            turn_no=1,
            user_reply="제 이메일은 test@example.com 입니다.",
        )

        print(f"탐지 개수: {len(result1.findings)}")

        for finding in result1.findings:
            print(
                f"- type={finding.type}, "
                f"confidence={finding.confidence}"
            )

        # 경고 후 사용자가 취소 선택
        if result1.findings:
            event1 = update_training_action(
                db=db,
                training_progress_id=progress.id,
                turn_no=1,
                action="취소",
            )

            print(
                f"Turn 1 최종 행동: {event1.action}"
            )

        # ---------------------------------
        # 4. Turn 2
        # 위험 정보 입력
        # ---------------------------------
        print("\n[Turn 2 검사]")

        result2 = handle_user_reply(
            db=db,
            training_progress_id=progress.id,
            turn_no=2,
            user_reply="제 전화번호는 010-1234-5678 입니다.",
        )

        print(f"탐지 개수: {len(result2.findings)}")

        for finding in result2.findings:
            print(
                f"- type={finding.type}, "
                f"confidence={finding.confidence}"
            )

        # 경고 후 사용자가 전송강행 선택
        if result2.findings:
            event2 = update_training_action(
                db=db,
                training_progress_id=progress.id,
                turn_no=2,
                action="전송강행",
            )

            print(
                f"Turn 2 최종 행동: {event2.action}"
            )

        # ---------------------------------
        # 5. TrainingEvent 확인
        # ---------------------------------
        print_events(
            db=db,
            training_progress_id=progress.id,
        )

        # ---------------------------------
        # 6. 자동 점수 계산
        # ---------------------------------
        score = calculate_training_score(
            db=db,
            training_progress_id=progress.id,
        )

        print("\n[점수 계산]")
        print(f"자동 계산 점수 = {score}")

        # ---------------------------------
        # 7. Training 종료
        # ---------------------------------
        finished = finish_training(
            db=db,
            training_progress_id=progress.id,
        )

        print("\n[Training 종료]")
        print(f"status = {finished.status}")
        print(f"score = {finished.score}")
        print(f"completed_at = {finished.completed_at}")

        # ---------------------------------
        # 8. Defender AI 리포트
        # ---------------------------------
        print("\n[Defender AI 리포트 생성 시작]")

        report = generate_defender_report(
            db=db,
            training_progress_id=progress.id,
        )

        print("\n=== Defender AI 최종 리포트 ===")
        print(report)

        print("\n=== 전체 테스트 완료 ===")

    except Exception as e:
        db.rollback()

        print("\n[ERROR]")
        print(type(e).__name__)
        print(e)

    finally:
        db.close()


if __name__ == "__main__":
    main()