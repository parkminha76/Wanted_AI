"""
InfoGuard DB 테이블 정의
========================

- contract.py의 RiskType / Finding / ScanResult 필드명을 그대로 따른다.
- companies / scam_cases는 지금 스코프에서 비어있는 테이블이다 (자리만 마련).
- 연결/세션 설정은 db/session.py 참고.
"""

from __future__ import annotations

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
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------------------------
# 1. companies — 기업 계정 확장 자리. 지금은 로직 없음, row도 안 생김.
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    plan = Column(Enum("free", "enterprise", name="company_plan"), default="free")
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="company")


# ---------------------------------------------------------------------------
# 2. users — 정식 회원가입 없이 이름/사번 정도로 가벼운 세션 식별
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id"), nullable=True)
    role = Column(
        Enum("individual", "employee", "company_admin", name="user_role"),
        default="individual",
    )
    name = Column(String(100), nullable=False)
    employee_no = Column(String(50), nullable=True)
    department = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="users")
    scan_results = relationship("ScanResultRow", back_populates="user")
    training_progress = relationship("TrainingProgress", back_populates="user")


# ---------------------------------------------------------------------------
# 3. scan_results — contract.py의 ScanResult와 1:1 대응
# ---------------------------------------------------------------------------
class ScanResultRow(Base):
    __tablename__ = "scan_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)

    filename = Column(String(255), default="")
    raw_text = Column(Text, default="")          # findings의 start/end는 이 텍스트 기준
    masked_text = Column(Text, default="")

    risk_score = Column(Float, default=0.0)
    error = Column(Text, nullable=True)
    status = Column(
        Enum("완료", "취소", "실패", name="scan_status"), default="완료"
    )

    file_id = Column(String(100), default="")
    file_type = Column(String(20), default="")   # pdf/docx/xlsx/txt/md/image
    masked_path = Column(String(500), nullable=True)  # 서버 내부 경로. 절대 응답에 안 실음.
    expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="scan_results")
    findings = relationship(
        "FindingRow", back_populates="scan_result", cascade="all, delete-orphan"
    )
    hidden_commands = relationship(
        "HiddenCommandRow", back_populates="scan_result", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 4. findings — contract.py의 Finding과 1:1 대응
#    오탐 제거된 항목도 지우지 않고 excluded=True로 남긴다.
# ---------------------------------------------------------------------------
class FindingRow(Base):
    __tablename__ = "findings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scan_result_id = Column(BigInteger, ForeignKey("scan_results.id"), nullable=False)

    finding_ref = Column(String(10), nullable=True)  # contract.py의 "f_001" 표시용 id
    type = Column(String(30), nullable=False)         # RiskType 값 그대로 (예: "account", "emp_no")
    text = Column(Text, nullable=False)
    start = Column(Integer, nullable=False)
    end = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)
    source = Column(
        Enum("rule", "ner", "classifier", "format", "cnn", name="finding_source"),
        nullable=False,
    )
    reason = Column(String(255), default="")
    page = Column(Integer, nullable=True)
    bbox = Column(JSON, nullable=True)     # (x0, y0, x1, y1) — PDF/CNN 전용
    evidence = Column(JSON, default=dict)  # {"font_size":1.0,...} / {"prob_positive":0.93,...}
    excluded = Column(Boolean, default=False)  # 오탐 제거 분류기가 걸러냈는지

    scan_result = relationship("ScanResultRow", back_populates="findings")


# ---------------------------------------------------------------------------
# 5. hidden_commands — 숨은 명령/인젝션 확인 상태 추적
#    (API 응답 findings 배열은 하나로 합쳐 나가되, DB 내부적으로 사용자 처리 상태만 추적)
# ---------------------------------------------------------------------------
class HiddenCommandRow(Base):
    __tablename__ = "hidden_commands"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scan_result_id = Column(BigInteger, ForeignKey("scan_results.id"), nullable=False)
    finding_id = Column(BigInteger, ForeignKey("findings.id"), nullable=False)

    status = Column(
        Enum("확인필요", "제거함", "무시함", name="hidden_command_status"),
        default="확인필요",
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    scan_result = relationship("ScanResultRow", back_populates="hidden_commands")
    finding = relationship("FindingRow")


# ---------------------------------------------------------------------------
# 6. training_progress — 레벨 하나를 진행하는 세션 단위
# ---------------------------------------------------------------------------
class TrainingProgress(Base):
    __tablename__ = "training_progress"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)

    level = Column(Integer, nullable=False)
    status = Column(
        Enum("진행중", "완료", "중단", name="training_status"), default="진행중"
    )
    score = Column(Integer, default=0)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="training_progress")
    events = relationship(
        "TrainingEvent", back_populates="training_progress", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 7. training_events — 훈련 중 턴 단위 기록. Defender AI 리포트의 재료.
# ---------------------------------------------------------------------------
class TrainingEvent(Base):
    __tablename__ = "training_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    training_progress_id = Column(
        BigInteger, ForeignKey("training_progress.id"), nullable=False
    )
    # 이 턴의 답장을 scan_text()로 검사한 결과와 연결 (선택)
    scan_result_id = Column(BigInteger, ForeignKey("scan_results.id"), nullable=True)

    turn_no = Column(Integer, nullable=False)
    detected_field = Column(String(30), nullable=True)  # RiskType 값
    action = Column(
        Enum("경고표시", "전송강행", "취소", name="training_action"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    training_progress = relationship("TrainingProgress", back_populates="events")
    scan_result = relationship("ScanResultRow")


# ---------------------------------------------------------------------------
# 8. scam_cases — 본선용 RAG 사례 풀. 예선 스코프 아님, 테이블만 미리 생성.
# ---------------------------------------------------------------------------
class ScamCase(Base):
    __tablename__ = "scam_cases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    level = Column(Integer, nullable=False)
    category = Column(String(50), nullable=True)      # 스미싱/기관사칭/로맨스스캠 등
    text = Column(Text, nullable=False)
    embedding_json = Column(JSON, nullable=True)       # 임베딩 벡터 배열. 본선 전엔 항상 NULL.
    source = Column(String(255), nullable=True)        # 금감원/경찰청 등
    created_at = Column(DateTime, default=datetime.utcnow)