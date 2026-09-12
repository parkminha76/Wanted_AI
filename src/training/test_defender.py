from src.training.defender import generate_defender_report

from backend.db.session import SessionLocal
from backend.db.tables import (
    User,
    TrainingProgress,
    TrainingEvent,
)


def create_test_training_data(db):
    print("테스트용 TrainingProgress 생성 중...")

    # 1. 기존 사용자 확인
    user = db.query(User).first()

    # 2. 사용자가 한 명도 없으면 테스트 사용자 생성
    if user is None:
        print("기존 User가 없어 테스트용 User를 생성합니다.")

        user = User(
            role="individual"
        )

        db.add(user)
        db.flush()

        print(f"테스트 User 생성 완료: user_id = {user.id}")

    else:
        print(f"기존 User 사용: user_id = {user.id}")

    # 3. TrainingProgress 생성
    progress = TrainingProgress(
        user_id=user.id,
        level=2,
        status="완료",
        score=78,
    )

    db.add(progress)
    db.flush()

    # 4. 턴별 이벤트 생성
    events = [
        TrainingEvent(
            training_progress_id=progress.id,
            turn_no=1,
            detected_field="email",
            action="경고표시",
        ),
        TrainingEvent(
            training_progress_id=progress.id,
            turn_no=2,
            detected_field="phone",
            action="전송강행",
        ),
    ]

    db.add_all(events)
    db.commit()

    print(
        f"테스트 데이터 생성 완료: "
        f"TrainingProgress ID = {progress.id}"
    )

    return progress


def main():
    db = SessionLocal()

    try:
        print("DB 연결 확인 중...")

        # 가장 최근 TrainingProgress 조회
        progress = (
            db.query(TrainingProgress)
            .order_by(TrainingProgress.id.desc())
            .first()
        )

        # 데이터가 없으면 테스트 데이터 생성
        if progress is None:
            print("TrainingProgress 데이터가 없습니다.")
            progress = create_test_training_data(db)

        print(f"\nTrainingProgress ID: {progress.id}")
        print(f"Level: {progress.level}")
        print(f"Status: {progress.status}")
        print(f"Score: {progress.score}")

        # DB에 저장된 TrainingEvent 조회
        events = (
            db.query(TrainingEvent)
            .filter_by(training_progress_id=progress.id)
            .order_by(TrainingEvent.turn_no)
            .all()
        )

        print(f"\nTrainingEvent 개수: {len(events)}")

        for event in events:
            print(
                f"Turn {event.turn_no} | "
                f"Action: {event.action} | "
                f"Detected: {event.detected_field}"
            )

        # Defender AI 호출
        print("\nDefender AI 리포트 생성 시작...")

        report = generate_defender_report(
            db=db,
            training_progress_id=progress.id,
        )

        print("\n=== Defender AI 리포트 ===")
        print(report)

    except Exception as e:
        db.rollback()

        print("\n[ERROR]")
        print(type(e).__name__)
        print(e)

    finally:
        db.close()


if __name__ == "__main__":
    main()