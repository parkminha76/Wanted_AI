"""
InfoGuard DB 테이블 정의 (v3)
==============================

v2 -> v3 변경 요약은 db/CHANGELOG_v3.md, 컬럼별 근거는 db/schema.sql 상단
주석 참고. 핵심만 요약:
  - reason/error를 고정 코드로 (db/codes.py)
  - evidence는 화이트리스트 검증 통과분만 (db/codes.py:sanitize_evidence)
  - hidden_commands.scan_result_id 제거, finding_id만 유지
  - 부모-자식 관계에 CASCADE 삭제
  - 필수 컬럼 NOT NULL
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship, validates

Base = declarative_base()


REASON_CODES = (
    "format_match", "checksum_pass", "checksum_fail", "ner_match",
    "classifier_high_confidence", "classifier_low_confidence",
    "hidden_text_detected", "injection_pattern_match", "cnn_detection",
)

ERROR_CODES = (
    "parse_failed", "unsupported_format", "file_too_large", "timeout", "unknown",
)


# ---------------------------------------------------------------------------
# 1. companies
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    plan = Column(Enum("free", "enterprise", name="company_plan"), nullable=False, default="free")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    users = relationship("User", back_populates="company")


# ---------------------------------------------------------------------------
# 2. users
#
# session_id: 로그인 인증 토큰이 아니라 비인증 세션 토큰이다. 같은 브라우저의
# 기록을 이어주는 용도이며, 직접 식별자(이름/사번)는 제거했지만 이 값 자체로
# 시간에 걸친 이력 연결은 가능하므로 완전한 비식별화는 아니다.
# department는 조직 통계 기능이 실제로 쓰일 때만 채운다 (기본 NULL 권장).
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id"), nullable=True)
    role = Column(
        Enum("individual", "employee", "company_admin", name="user_role"),
        nullable=False, default="individual",
    )
    session_id = Column(
        String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    department = Column(String(100), nullable=True)  # 조직 통계 기능 쓸 때만 채울 것
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    company = relationship("Company", back_populates="users")
    scan_results = relationship(
        "ScanResultRow", back_populates="user", cascade="all, delete-orphan"
    )
    training_progress = relationship(
        "TrainingProgress", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 3. scan_results — 원문 없이 "집계 및 탐지 메타데이터" 저장
# ---------------------------------------------------------------------------
class ScanResultRow(Base):
    __tablename__ = "scan_results"
    __table_args__ = (
        Index("idx_scan_results_user_created", "user_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    file_extension = Column(String(10), nullable=False, default="")
    risk_score = Column(Float, nullable=False, default=0.0)
    error_code = Column(Enum(*ERROR_CODES, name="error_code"), nullable=True)
    status = Column(
        Enum("완료", "취소", "실패", name="scan_status"), nullable=False, default="완료"
    )
    finding_counts = Column(JSON, nullable=False, default=dict)
    # 주의: default=dict는 SQLAlchemy ORM이 flush 시점에 파이썬 레벨에서 채워주는
    # 것이지, DB 자체의 DEFAULT 제약이 아니다(schema.sql 참고 — JSON 컬럼은 SQL
    # DEFAULT를 못 건다). 원시 SQL로 직접 INSERT하는 경로가 있다면 이 default는
    # 적용되지 않으므로 그 경로에서도 반드시 '{}'를 명시할 것.
    filtered_count = Column(Integer, nullable=False, default=0)
    has_hidden_command = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="scan_results")
    findings = relationship(
        "FindingRow", back_populates="scan_result", cascade="all, delete-orphan"
    )

    @validates("finding_counts")
    def _validate_finding_counts(self, key, value):
        """키(RiskType)와 값(0 이상 정수) 둘 다 검증한다.

        범위: 이 데코레이터는 `scan_result.finding_counts = {...}`처럼 속성을
        **통째로 재할당**할 때만 실행된다. ORM을 거치지 않는 bulk insert/update
        (Session.execute(insert(...)), bulk_insert_mappings 등)나, 이미 대입된
        dict를 `scan_result.finding_counts["account"] = 5`처럼 **내부에서만
        변형**하는 경우는 이 검증을 거치지 않는다. finding_counts는 항상
        `add_finding_count()`로 갱신할 것 — 내부 변형이 아니라 새 dict를 만들어
        재할당하므로 검증을 우회하지 않는다.
        """
        from backend.db.codes import validate_risk_type

        value = value or {}
        for risk_type, count in value.items():
            if not validate_risk_type(risk_type):
                raise ValueError(f"finding_counts에 알 수 없는 RiskType: {risk_type}")
            if not isinstance(count, int) or count < 0:
                raise ValueError(
                    f"finding_counts[{risk_type}]는 0 이상의 정수여야 함: {count!r}"
                )
        return value

    def add_finding_count(self, risk_type: str, delta: int = 1) -> None:
        """finding_counts를 안전하게 갱신하는 유일한 방법.

        `self.finding_counts[risk_type] = ...`처럼 dict 내부를 직접 고치면
        위 _validate_finding_counts가 호출되지 않는다 (속성 재할당이 아니라
        기존 객체의 __setitem__이기 때문 — SQLAlchemy validates는 재할당에만
        반응한다). 이 메서드는 새 dict를 만들어 통째로 재할당하므로 검증을
        반드시 거친다.
        """
        updated = dict(self.finding_counts or {})
        updated[risk_type] = updated.get(risk_type, 0) + delta
        self.finding_counts = updated  # 재할당 -> _validate_finding_counts 실행됨


# ---------------------------------------------------------------------------
# 4. findings — 개별 탐지 메타데이터. reason은 고정 코드, evidence는
#    화이트리스트 검증 통과분만 (db/codes.py:sanitize_evidence 반드시 거칠 것).
# ---------------------------------------------------------------------------
class FindingRow(Base):
    __tablename__ = "findings"
    __table_args__ = (
        Index("idx_findings_scan_excluded", "scan_result_id", "excluded"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scan_result_id = Column(
        BigInteger, ForeignKey("scan_results.id", ondelete="CASCADE"), nullable=False
    )

    finding_ref = Column(String(10), nullable=True)
    type = Column(String(30), nullable=False)
    confidence = Column(Float, nullable=False)
    source = Column(
        Enum("rule", "ner", "classifier", "format", "cnn", name="finding_source"),
        nullable=False,
    )
    reason_code = Column(Enum(*REASON_CODES, name="reason_code"), nullable=False)
    page = Column(Integer, nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)  # sanitize_evidence() 통과분만
    excluded = Column(Boolean, nullable=False, default=False)

    scan_result = relationship("ScanResultRow", back_populates="findings")
    hidden_command = relationship(
        "HiddenCommandRow", back_populates="finding", uselist=False,
        cascade="all, delete-orphan",
    )

    @validates("type")
    def _validate_type(self, key, value):
        """`finding.type = ...`처럼 속성을 재할당(객체 생성 시 포함)할 때만
        실행된다. Session.execute(insert(FindingRow), [...]) 같은 Core 레벨
        bulk insert는 ORM 인스턴스를 거치지 않으므로 이 검증을 우회한다 —
        그런 경로를 추가한다면 삽입 직전에 validate_risk_type()을 명시적으로
        호출해야 한다.
        """
        from backend.db.codes import validate_risk_type

        if not validate_risk_type(value):
            raise ValueError(f"findings.type에 알 수 없는 RiskType: {value}")
        return value

    @validates("evidence")
    def _validate_evidence(self, key, value):
        """converter 검증 + ORM 속성 재할당 시 재검증.

        이 데코레이터는 `finding.evidence = {...}`처럼 속성 자체를 새로
        대입할 때만 실행된다. 아래 두 경우는 이 검증을 거치지 않는다:
          1) bulk insert/update, Session.execute(text(...)) 같은 Core/원시
             SQL 경로 — ORM 인스턴스의 속성 set 이벤트 자체가 발생하지 않음
          2) `finding.evidence["key"] = value`처럼 이미 있는 dict를 내부에서
             변형하는 경우 — 이건 dict의 __setitem__이지 속성 재할당이
             아니라서 SQLAlchemy가 감지하지 못함
        evidence를 바꿔야 하면 반드시 set_evidence()를 쓸 것 (내부 변형이
        아니라 새 dict를 만들어 통째로 재할당하므로 검증을 우회하지 않는다).
        새로운 bulk/원시 SQL 저장 경로를 추가할 경우, 그 경로 안에서
        sanitize_evidence()/validate_risk_type()을 직접 호출해야 한다 —
        이 데코레이터가 대신 막아주지 않는다.
        """
        from backend.db.codes import sanitize_evidence

        return sanitize_evidence(value or {})

    def set_evidence(self, evidence: dict) -> None:
        """evidence를 안전하게 설정하는 유일한 방법.
        `finding.evidence["key"] = value` 형태의 직접 변형은 절대 쓰지 말 것 —
        위 _validate_evidence의 검증을 거치지 않는다.
        """
        from backend.db.codes import sanitize_evidence

        self.evidence = sanitize_evidence(evidence)  # 재할당 -> _validate_evidence 실행됨


# ---------------------------------------------------------------------------
# 5. hidden_commands — finding_id만 유지 (scan_result_id 제거).
#    scan_result가 필요하면 finding.scan_result로 조인해서 구한다.
# ---------------------------------------------------------------------------
class HiddenCommandRow(Base):
    __tablename__ = "hidden_commands"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    finding_id = Column(
        BigInteger, ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )

    status = Column(
        Enum("확인필요", "제거함", "무시함", name="hidden_command_status"),
        nullable=False, default="확인필요",
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    finding = relationship("FindingRow", back_populates="hidden_command")

    @property
    def scan_result(self):
        """scan_result_id 컬럼을 따로 안 두고, finding을 거쳐서 구한다."""
        return self.finding.scan_result


# ---------------------------------------------------------------------------
# 6. training_progress
# ---------------------------------------------------------------------------
class TrainingProgress(Base):
    __tablename__ = "training_progress"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    level = Column(Integer, nullable=False)
    status = Column(
        Enum("진행중", "완료", "중단", name="training_status"), nullable=False, default="진행중"
    )
    score = Column(Integer, nullable=False, default=0)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="training_progress")
    events = relationship(
        "TrainingEvent", back_populates="training_progress", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 7. training_events
# ---------------------------------------------------------------------------
class TrainingEvent(Base):
    __tablename__ = "training_events"
    __table_args__ = (
        UniqueConstraint("training_progress_id", "turn_no", name="uq_training_events_turn"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    training_progress_id = Column(
        BigInteger, ForeignKey("training_progress.id", ondelete="CASCADE"), nullable=False
    )

    turn_no = Column(Integer, nullable=False)
    detected_field = Column(String(30), nullable=True)
    action = Column(
        Enum("경고표시", "전송강행", "취소", name="training_action"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    training_progress = relationship("TrainingProgress", back_populates="events")

    @validates("detected_field")
    def _validate_detected_field(self, key, value):
        """속성 재할당 시에만 실행됨 (범위는 FindingRow._validate_type 주석
        참고 — bulk insert/원시 SQL 경로는 이 검증을 거치지 않음)."""
        from backend.db.codes import validate_risk_type

        if not validate_risk_type(value):
            raise ValueError(f"training_events.detected_field에 알 수 없는 RiskType: {value}")
        return value


# ---------------------------------------------------------------------------
# 8. scam_cases — 본선 스코프, 변경 없음
# ---------------------------------------------------------------------------
class ScamCase(Base):
    __tablename__ = "scam_cases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    level = Column(Integer, nullable=False)
    category = Column(String(50), nullable=True)
    text = Column(Text, nullable=False)
    embedding_json = Column(JSON, nullable=True)
    source = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)