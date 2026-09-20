from __future__ import annotations

import itertools
import unittest
from datetime import datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.db.tables import Base, TrainingEvent, TrainingProgress, User
from backend.training.router import _record_training_event, get_training_stats


def _assign_id_before_insert(mapper, connection, target):
    """BigInteger PK는 MySQL/TiDB에서는 자동 채번되지만, SQLite는 리터럴로
    'INTEGER PRIMARY KEY'가 아니면(=BigInteger면) rowid 별칭 취급을 안 해서
    NOT NULL 오류가 난다 — 테스트 DB(SQLite) 한정 문제라 여기서만 직접 채번한다."""
    if target.id is None:
        target.id = next(_assign_id_before_insert.counter)


_assign_id_before_insert.counter = itertools.count(1)


class RecordTrainingEventTest(unittest.TestCase):
    """실제 TiDB는 안 건드리고, 인메모리 SQLite에 같은 테이블을 만들어 검증한다."""

    def setUp(self) -> None:
        event.listen(TrainingEvent, "before_insert", _assign_id_before_insert)
        self.addCleanup(event.remove, TrainingEvent, "before_insert", _assign_id_before_insert)

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        # BigInteger PK는 SQLite에서 autoincrement가 안 붙어서 id를 직접 지정한다
        # (MySQL/TiDB에서는 문제없이 자동 채번된다 — 테스트 환경 한정 이슈).
        user = User(id=1, role="individual")
        self.db.add(user)
        self.db.flush()
        progress = TrainingProgress(id=1, user_id=user.id, level=1, status="진행중", score=0)
        self.db.add(progress)
        self.db.commit()
        self.progress_id = progress.id

    def tearDown(self) -> None:
        self.db.close()

    def test_records_first_shared_field_and_warns(self) -> None:
        _record_training_event(self.db, self.progress_id, turn_no=1, shared_fields=["phone", "account"])
        events = self.db.query(TrainingEvent).filter_by(training_progress_id=self.progress_id).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].turn_no, 1)
        self.assertEqual(events[0].detected_field, "phone")
        self.assertEqual(events[0].action, "경고표시")

    def test_no_shared_fields_records_null_event(self) -> None:
        _record_training_event(self.db, self.progress_id, turn_no=1, shared_fields=[])
        events = self.db.query(TrainingEvent).filter_by(training_progress_id=self.progress_id).all()
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].detected_field)
        self.assertIsNone(events[0].action)

    def test_duplicate_turn_no_is_swallowed_not_raised(self) -> None:
        _record_training_event(self.db, self.progress_id, turn_no=1, shared_fields=["email"])
        # (training_progress_id, turn_no) 유니크 제약 위반 — 예외가 밖으로 새면 안 된다.
        _record_training_event(self.db, self.progress_id, turn_no=1, shared_fields=["card"])
        events = self.db.query(TrainingEvent).filter_by(training_progress_id=self.progress_id).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].detected_field, "email")


class GetTrainingStatsTest(unittest.TestCase):
    """실제 TiDB는 안 건드리고, 인메모리 SQLite로 집계 로직만 검증한다."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(User(id=1, role="individual"))
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()

    def _add_progress(self, id_, level, score, *, completed=True) -> None:
        self.db.add(
            TrainingProgress(
                id=id_,
                user_id=1,
                level=level,
                status="완료" if completed else "진행중",
                score=score,
                completed_at=datetime(2026, 9, 16) if completed else None,
            )
        )

    def test_no_completed_training_returns_nulls_not_zero(self) -> None:
        self.db.commit()
        result = get_training_stats(level=1, score=None, db=self.db)
        self.assertEqual(result["completed_count"], 0)
        self.assertIsNone(result["average_score"])
        self.assertIsNone(result["percentile"])

    def test_average_and_grade_distribution(self) -> None:
        self._add_progress(1, level=2, score=95)  # 안전
        self._add_progress(2, level=2, score=75)  # 양호
        self._add_progress(3, level=2, score=55)  # 주의
        self._add_progress(4, level=2, score=30)  # 위험
        self.db.commit()

        result = get_training_stats(level=2, score=None, db=self.db)
        self.assertEqual(result["completed_count"], 4)
        self.assertEqual(result["average_score"], 63.8)
        self.assertEqual(
            result["grade_distribution"], {"안전": 1, "양호": 1, "주의": 1, "위험": 1}
        )

    def test_percentile_counts_ties_as_better_than(self) -> None:
        self._add_progress(1, level=3, score=50)
        self._add_progress(2, level=3, score=60)
        self._add_progress(3, level=3, score=90)
        self._add_progress(4, level=3, score=90)
        self.db.commit()

        result = get_training_stats(level=3, score=90, db=self.db)
        # 90점 이하가 4건 중 4건 -> 상위 100% (자기 자신 포함, 동점자도 포함)
        self.assertEqual(result["percentile"], 100)

        result_low = get_training_stats(level=3, score=10, db=self.db)
        # 10점 이하가 4건 중 0건
        self.assertEqual(result_low["percentile"], 0)

    def test_in_progress_training_is_excluded(self) -> None:
        self._add_progress(1, level=4, score=99, completed=False)
        self.db.commit()
        result = get_training_stats(level=4, score=None, db=self.db)
        self.assertEqual(result["completed_count"], 0)

    def test_other_levels_are_excluded(self) -> None:
        self._add_progress(1, level=1, score=80)
        self._add_progress(2, level=2, score=20)
        self.db.commit()
        result = get_training_stats(level=1, score=None, db=self.db)
        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["average_score"], 80.0)

    def test_unscored_interrupted_training_is_excluded(self) -> None:
        self._add_progress(1, level=3, score=80)
        self.db.add(
            TrainingProgress(
                id=2,
                user_id=1,
                level=3,
                status="중단",
                score=0,
                completed_at=datetime(2026, 9, 16),
            )
        )
        self.db.commit()

        result = get_training_stats(level=3, score=None, db=self.db)

        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["average_score"], 80.0)


if __name__ == "__main__":
    unittest.main()
