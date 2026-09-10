"""
InfoGuard DB 연결 및 세션 관리 (TiDB Cloud, MySQL 프로토콜 호환)
==============================================================

.env 예시 (프로젝트 루트):
    DB_HOST = gateway01.ap-northeast-1.prod.aws.tidbcloud.com
    DB_PORT = 4000
    DB_USERNAME = xxx.root
    DB_PASSWORD = ***********
    DB_DATABASE = infoguard

로컬 도커 MySQL로 개발할 땐 아래 DATABASE_URL 생성부에서 ssl 옵션 없는 쪽으로
바꿔서 쓴다 (차이는 사실상 ssl 옵션 유무뿐).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.tables import Base

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "")
DB_PORT = os.environ.get("DB_PORT", "4000")
DB_USERNAME = os.environ.get("DB_USERNAME", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_DATABASE = os.environ.get("DB_DATABASE", "infoguard")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_DATABASE}"
    f"?ssl_verify_cert=true&ssl_verify_identity=true"
)

# 로컬 도커 MySQL로 개발할 땐 이걸로 덮어써서 쓴다 (SSL 옵션 없이).
# DATABASE_URL = "mysql+pymysql://root:password@localhost:3306/infoguard"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """테이블이 없으면 전부 생성한다. companies/scam_cases도 이때 같이 생기지만
    row는 안 넣는다 (자리만 마련)."""
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """전체 테이블을 삭제한다. 되돌릴 수 없으니 개발 중 스키마를 갈아엎을 때만 쓴다.

    FK 의존성이 있어도 SQLAlchemy가 참조 순서를 알아서 계산해서 지우므로
    schema.sql처럼 순서를 직접 신경 쓸 필요는 없다.
    """
    Base.metadata.drop_all(bind=engine)


def reset_db() -> None:
    """drop_db() 후 init_db() — 스키마가 바뀌었을 때(v1 -> v2 등) 전체 재생성."""
    drop_db()
    init_db()


def get_session():
    """FastAPI 의존성 주입용. 사용 예:
        def route(db: Session = Depends(get_session)): ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    if "--reset" in sys.argv:
        confirm = input(
            f"'{DB_DATABASE}' 데이터베이스의 모든 테이블과 데이터를 삭제하고 "
            "새로 만듭니다. 계속하려면 'yes' 입력: "
        )
        if confirm.strip().lower() != "yes":
            print("취소되었습니다.")
            sys.exit(0)
        reset_db()
        print(f"재생성 완료: {list(Base.metadata.tables.keys())}")
    elif "--drop" in sys.argv:
        confirm = input(
            f"'{DB_DATABASE}' 데이터베이스의 모든 테이블을 삭제합니다. "
            "계속하려면 'yes' 입력: "
        )
        if confirm.strip().lower() != "yes":
            print("취소되었습니다.")
            sys.exit(0)
        drop_db()
        print("전체 테이블 삭제 완료.")
    else:
        init_db()
        print(f"테이블 생성 완료: {list(Base.metadata.tables.keys())}")