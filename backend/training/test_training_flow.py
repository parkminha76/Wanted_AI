from backend.db.session import SessionLocal
from backend.db.tables import User, TrainingEvent

from backend.training.training_service import (
    start_training,
    update_training_action,
    finish_training,
)

from backend.training.training_flow import (
    create_training_session,
    generate_attacker_message,
    process_user_reply,
)

from backend.training.defender import generate_defender_report


def get_or_create_test_user(db):
    user = db.query(User).first()

    if user is None:
        print("기존 User가 없어 테스트용 User를 생성합니다.")

        user = User(role="individual")

        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"테스트 User 생성 완료: user_id = {user.id}")

    else:
        print(f"기존 User 사용: user_id = {user.id}")

    return user


def print_events(db, training_progress_id):
    events = (
        db.query(TrainingEvent)
        .filter_by(training_progress_id=training_progress_id)
        .order_by(TrainingEvent.turn_no)
        .all()
    )

    print("\n[TrainingEvent 확인]")

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
        print("=== Attacker AI + Training Mode 전체 테스트 시작 ===")

        # 1. User 확보
        user = get_or_create_test_user(db)

        # 2. Training 시작
        progress = start_training(
            db=db,
            user_id=user.id,
            level=2,
        )

        print("\n[Training 시작]")
        print(f"training_progress_id = {progress.id}")

        # 3. Attacker 세션 생성
        session = create_training_session()

        print("\n[초기 상태]")
        print(f"state = {session['state']}")
        print(f"turn_no = {session['turn_no']}")

        # ---------------------------------
        # Turn 1
        # ---------------------------------

        print("\n=== Turn 1 ===")

        attacker_message_1 = generate_attacker_message(session)

        print("\n[Attacker AI]")
        print(attacker_message_1)

        user_reply_1 = "왜 이런 확인이 필요한가요?"

        print("\n[User]")
        print(user_reply_1)

        result1 = process_user_reply(
            db=db,
            training_progress_id=progress.id,
            session=session,
            user_reply=user_reply_1,
        )

        print("\n[상태 전환]")
        print(
            f"{result1['previous_state']} "
            f"→ {result1['next_state']}"
        )

        print(
            f"탐지 개수 = "
            f"{len(result1['scan_result'].findings)}"
        )

        # ---------------------------------
        # Turn 2
        # ---------------------------------

        print("\n=== Turn 2 ===")

        attacker_message_2 = generate_attacker_message(session)

        print("\n[Attacker AI]")
        print(attacker_message_2)

        user_reply_2 = "제 이메일은 test@example.com 입니다."

        print("\n[User]")
        print(user_reply_2)

        result2 = process_user_reply(
            db=db,
            training_progress_id=progress.id,
            session=session,
            user_reply=user_reply_2,
        )

        print("\n[상태 전환]")
        print(
            f"{result2['previous_state']} "
            f"→ {result2['next_state']}"
        )

        print(
            f"탐지 개수 = "
            f"{len(result2['scan_result'].findings)}"
        )

        # 위험 정보가 탐지되었다면
        # 사용자가 "전송강행"했다고 가정
        if result2["scan_result"].findings:
            event = update_training_action(
                db=db,
                training_progress_id=progress.id,
                turn_no=2,
                action="전송강행",
            )

            print(
                f"Turn 2 최종 행동 = {event.action}"
            )

        # ---------------------------------
        # Turn 3
        # ---------------------------------

        if not result2["is_finished"]:

            print("\n=== Turn 3 ===")

            attacker_message_3 = generate_attacker_message(session)

            print("\n[Attacker AI]")
            print(attacker_message_3)

            user_reply_3 = "이상한데요. 더 이상 진행하지 않겠습니다."

            print("\n[User]")
            print(user_reply_3)

            result3 = process_user_reply(
                db=db,
                training_progress_id=progress.id,
                session=session,
                user_reply=user_reply_3,
            )

            print("\n[상태 전환]")
            print(
                f"{result3['previous_state']} "
                f"→ {result3['next_state']}"
            )

            print(
                f"is_finished = "
                f"{result3['is_finished']}"
            )

        # ---------------------------------
        # DB 이벤트 확인
        # ---------------------------------

        print_events(
            db=db,
            training_progress_id=progress.id,
        )

        # ---------------------------------
        # Training 종료
        # ---------------------------------

        finished = finish_training(
            db=db,
            training_progress_id=progress.id,
        )

        print("\n[Training 종료]")
        print(f"status = {finished.status}")
        print(f"score = {finished.score}")

        # ---------------------------------
        # Defender AI
        # ---------------------------------

        print("\n[Defender AI 리포트 생성]")

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