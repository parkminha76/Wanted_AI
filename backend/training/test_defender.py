from backend.training.defender import generate_defender_report

from backend.db.session import SessionLocal
from backend.db.tables import TrainingProgress, TrainingEvent


def main():
    db = SessionLocal()

    try:
        print("DB 연결 확인 중...")

        # 가장 최근 TrainingProgress 가져오기
        progress = (
            db.query(TrainingProgress)
            .order_by(TrainingProgress.id.desc())
            .first()
        )

        # 훈련 기록이 아직 없는 경우
        if progress is None:
            print("TrainingProgress 데이터가 없습니다.")
            print("테스트용 훈련 데이터를 먼저 만들어야 합니다.")
            return

        print(f"TrainingProgress ID: {progress.id}")
        print(f"Level: {progress.level}")
        print(f"Status: {progress.status}")
        print(f"Score: {progress.score}")

        # 해당 훈련의 이벤트 조회
        events = (
            db.query(TrainingEvent)
            .filter_by(training_progress_id=progress.id)
            .order_by(TrainingEvent.turn_no)
            .all()
        )

        print(f"TrainingEvent 개수: {len(events)}")

        for event in events:
            print(
                f"Turn {event.turn_no} | "
                f"Action: {event.action} | "
                f"Detected: {event.detected_field}"
            )

        if not events:
            print("TrainingEvent가 없습니다.")
            print("테스트용 이벤트를 먼저 만들어야 합니다.")
            return

        # Defender AI 실행
        print("\nDefender AI 리포트 생성 시작...")

        report = generate_defender_report(
            db=db,
            training_progress_id=progress.id,
        )

        print("\n=== Defender AI 리포트 ===")
        print(report)

    except Exception as e:
        print("\n[ERROR]")
        print(type(e).__name__)
        print(e)

    finally:
        db.close()


if __name__ == "__main__":
    main()