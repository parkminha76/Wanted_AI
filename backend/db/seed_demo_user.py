"""공모전 데모용 고정 사용자(id=1)를 안전하게 준비한다.

기존 id=1 사용자가 있으면 어떤 값도 변경하지 않는다.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from backend.db.session import SessionLocal
from backend.db.tables import User

DEMO_USER_ID = 1


def ensure_demo_user() -> tuple[int, str, bool]:
    """데모 사용자를 보장하고 (id, role, created)를 반환한다."""
    with SessionLocal() as db:
        existing = db.get(User, DEMO_USER_ID)
        if existing is not None:
            return existing.id, existing.role, False

        user = User(
            id=DEMO_USER_ID,
            company_id=None,
            role="individual",
            session_id=str(uuid4()),
            department=None,
        )
        db.add(user)

        try:
            db.commit()
        except IntegrityError:
            # 동시에 같은 시드가 실행된 경우 기존 행을 다시 확인한다.
            db.rollback()
            existing = db.get(User, DEMO_USER_ID)
            if existing is None:
                raise
            return existing.id, existing.role, False

        return user.id, user.role, True


def main() -> None:
    user_id, role, created = ensure_demo_user()
    result = "생성" if created else "기존 사용자 확인"
    print(f"데모 사용자 {result}: id={user_id}, role={role}")


if __name__ == "__main__":
    main()
