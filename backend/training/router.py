from __future__ import annotations

import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.db.tables import TrainingProgress
from backend.db.converters import build_defender_payload
from backend.shared.logging_config import get_logger, log_event
from backend.training.defender import generate_defender_report
from backend.training.training_flow import (
    create_training_session,
    generate_attacker_message,
    process_user_reply,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/training",
    tags=["training"],
)


# ---------------------------------------------------------
# 요청 데이터 형식
# ---------------------------------------------------------

class TrainingStartRequest(BaseModel):
    user_id: int
    level: int = Field(ge=1, le=5)


class TrainingReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


# ---------------------------------------------------------
# 임시 세션 저장소
# ---------------------------------------------------------
# training_flow.py의 TrainingSession은 현재 DB 모델이 아니라
# 파이썬 객체이므로 우선 메모리에 보관한다.
#
# 서버 재시작 시 사라지는 MVP용 구조.
_training_sessions: dict[int, object] = {}


# ---------------------------------------------------------
# 훈련 시작
# ---------------------------------------------------------

@router.post("/start")
def start_training_api(
    request: TrainingStartRequest,
    db: Session = Depends(get_session),
):
    try:
        progress = TrainingProgress(
            user_id=request.user_id,
            level=request.level,
            status="진행중",
            score=0,
        )

        db.add(progress)

        # 아직 최종 저장(commit)하지 않고 ID만 생성
        db.flush()

        session = create_training_session()

        # Claude 호출
        attacker_message = generate_attacker_message(session)

        # Claude 호출까지 성공했을 때만 DB 최종 저장
        db.commit()
        db.refresh(progress)

        _training_sessions[progress.id] = session

        log_event(
            logger,
            logging.INFO,
            "training.started",
            training_level=request.level,
            turn_no=session["turn_no"],
            training_status="in_progress",
        )

        return {
            "training_progress_id": progress.id,
            "level": request.level,
            "state": session["state"],
            "turn_no": session["turn_no"],
            "attacker_message": attacker_message,
        }

    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            logging.ERROR,
            "training.start.failed",
            training_level=request.level,
            error_code=type(exc).__name__,
        )

        raise HTTPException(
            status_code=500,
            detail="훈련 시작 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )


# ---------------------------------------------------------
# 사용자 답장 처리
# ---------------------------------------------------------

@router.post("/{training_progress_id}/reply")
def reply_training_api(
    training_progress_id: int,
    request: TrainingReplyRequest,
    db: Session = Depends(get_session),
):
    session = _training_sessions.get(training_progress_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="진행 중인 훈련 세션을 찾을 수 없습니다.",
        )

    try:
        result = process_user_reply(
            db=db,
            training_progress_id=training_progress_id,
            session=session,
            user_reply=request.text,
        )

        next_message = generate_attacker_message(session)

        scan_result = result["scan_result"]
        log_event(
            logger,
            logging.INFO,
            "training.reply.processed",
            turn_no=result["turn_no"],
            training_status="finished" if result["is_finished"] else "in_progress",
            total_findings=len(scan_result.findings),
            filtered_out=len(scan_result.filtered_out),
            finding_counts=dict(
                sorted(Counter(f.type for f in scan_result.findings).items())
            ),
            risk_levels={scan_result.level: 1},
        )

        return {
                "training_progress_id": training_progress_id,
                "state": session["state"],
                "turn_no": session["turn_no"],
                "scan_result": result,
                "attacker_message": next_message,
        }

    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            logging.ERROR,
            "training.reply.failed",
            error_code=type(exc).__name__,
        )

        raise HTTPException(
            status_code=500,
            detail="답장 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )

# ---------------------------------------------------------
# 훈련 결과 리포트 조회
# ---------------------------------------------------------

@router.get("/{training_progress_id}/report")
def get_training_report_api(
    training_progress_id: int,
    db: Session = Depends(get_session),
):
    # 1. 실제 존재하는 훈련인지 확인
    progress = db.get(TrainingProgress, training_progress_id)

    if progress is None:
        raise HTTPException(
            status_code=404,
            detail="훈련 기록을 찾을 수 없습니다.",
        )

    try:
        # 2. DB에서 비식별화된 훈련 기록 조회
        payload = build_defender_payload(
            db=db,
            training_progress_id=training_progress_id,
        )

        # 3. Defender AI 최종 분석 생성
        report = generate_defender_report(
            db=db,
            training_progress_id=training_progress_id,
        )

        log_event(
            logger,
            logging.INFO,
            "training.report.generated",
            training_level=payload["level"],
            training_status="completed",
        )

        # 4. 프론트엔드용 응답
        return {
            "training_progress_id": training_progress_id,
            "level": payload["level"],
            "final_score": payload["final_score"],
            "turns": payload["turns"],
            "report": report,
        }

    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "training.report.failed",
            error_code=type(exc).__name__,
        )

        raise HTTPException(
            status_code=500,
            detail="훈련 리포트 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )
