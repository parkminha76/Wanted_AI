from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.db.tables import TrainingProgress
from backend.training.training_flow import (
    create_training_session,
    generate_attacker_message,
    process_user_reply,
)


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
        db.commit()
        db.refresh(progress)

        session = create_training_session()

        _training_sessions[progress.id] = session

        attacker_message = generate_attacker_message(session)

        return {
                "training_progress_id": progress.id,
                "level": request.level,
                "state": session["state"],
                "turn_no": session["turn_no"],
                "attacker_message": attacker_message,
        }

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"훈련 시작 중 오류가 발생했습니다: {exc}",
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

        return {
                "training_progress_id": training_progress_id,
                "state": session["state"],
                "turn_no": session["turn_no"],
                "scan_result": result,
                "attacker_message": next_message,
        }

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"답장 처리 중 오류가 발생했습니다: {exc}",
        )