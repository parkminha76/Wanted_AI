from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.db.tables import TrainingProgress
from backend.shared.logging_config import get_logger, log_event
from backend.training.defender import generate_defender_report
from backend.training.scenarios import select_random_scenario
from backend.training.training_flow import (
    create_training_session,
    generate_attacker_message,
    process_user_reply,
)
from backend.training.training_service import (
    calculate_training_score,
    finish_training,
    grade_training_score,
)


logger = get_logger(__name__)
router = APIRouter(prefix="/training", tags=["training"])


class TrainingStartRequest(BaseModel):
    user_id: int
    level: int = Field(ge=1, le=5)


class TrainingReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


# MVP 제한: 서버 재시작 시 진행 세션과 상세 리포트는 사라진다.
_training_sessions: dict[int, dict] = {}
_training_reports: dict[int, dict] = {}


def _complete_training(
    *,
    db: Session,
    training_progress_id: int,
    session: dict,
) -> dict:
    defender_report = generate_defender_report(
        level=session["level"],
        scenario=session["scenario"],
        history=session["history"],
        shared_fields=session["shared_fields"],
    )
    score = calculate_training_score(defender_report)
    grade = grade_training_score(score)
    finish_training(
        db=db,
        training_progress_id=training_progress_id,
        final_score=score,
    )
    report = {
        "training_progress_id": training_progress_id,
        "level": session["level"],
        "score": score,
        "grade": grade,
        "risky_actions": defender_report["risky_actions"],
        "good_actions": defender_report["good_actions"],
        "improvements": defender_report["improvements"],
        "summary": defender_report["summary"],
    }
    _training_reports[training_progress_id] = report
    # 세션에는 치환된 대화만 있지만 완료 후 즉시 제거한다.
    _training_sessions.pop(training_progress_id, None)
    return report


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
        db.flush()

        scenario = select_random_scenario(request.level)
        session = create_training_session(request.level, scenario)
        attacker_message = generate_attacker_message(session)

        db.commit()
        db.refresh(progress)
        _training_sessions[progress.id] = session

        log_event(
            logger,
            logging.INFO,
            "training.started",
            training_level=request.level,
            scenario_id=scenario["id"],
            turn_no=session["turn_no"],
            training_status="in_progress",
        )
        return {
            "training_progress_id": progress.id,
            "level": request.level,
            "scenario_id": scenario["id"],
            "scenario_title": scenario["name"],
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
        ) from exc


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
        # Defender 호출만 실패한 경우 사용자가 같은 원문을 다시 보낼 필요 없이 재시도한다.
        if session["status"] == "awaiting_report":
            _complete_training(
                db=db,
                training_progress_id=training_progress_id,
                session=session,
            )
            return {
                "training_progress_id": training_progress_id,
                "turn_no": session["turn_no"],
                "is_finished": True,
                "attacker_message": None,
            }

        result = process_user_reply(session=session, user_reply=request.text)
        if result["is_finished"]:
            _complete_training(
                db=db,
                training_progress_id=training_progress_id,
                session=session,
            )
            next_message = None
        else:
            next_message = generate_attacker_message(session)

        log_event(
            logger,
            logging.INFO,
            "training.reply.processed",
            turn_no=result["turn_no"],
            training_status="finished" if result["is_finished"] else "in_progress",
            shared_field_types=result["shared_fields"],
        )
        return {
            "training_progress_id": training_progress_id,
            "turn_no": result["turn_no"],
            "is_finished": result["is_finished"],
            "attacker_message": next_message,
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        ) from exc


@router.get("/{training_progress_id}/report")
def get_training_report_api(
    training_progress_id: int,
    db: Session = Depends(get_session),
):
    progress = db.get(TrainingProgress, training_progress_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="훈련 기록을 찾을 수 없습니다.")

    report = _training_reports.get(training_progress_id)
    if report is not None:
        return report

    session = _training_sessions.get(training_progress_id)
    if session and session["status"] == "awaiting_report":
        try:
            return _complete_training(
                db=db,
                training_progress_id=training_progress_id,
                session=session,
            )
        except Exception as exc:
            db.rollback()
            log_event(
                logger,
                logging.ERROR,
                "training.report.failed",
                error_code=type(exc).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail="훈련 리포트 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            ) from exc

    raise HTTPException(
        status_code=409,
        detail="훈련이 아직 완료되지 않았거나 상세 리포트가 만료되었습니다.",
    )
