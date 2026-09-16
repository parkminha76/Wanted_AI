from __future__ import annotations

import itertools
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.db.tables import Base, TrainingEvent, TrainingProgress, User
from backend.training.router import _record_training_event


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


if __name__ == "__main__":
    unittest.main()
