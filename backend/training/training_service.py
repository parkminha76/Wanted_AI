from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.db.tables import TrainingProgress


RUBRIC_WEIGHTS = {
    "verified_identity": 15,
    "used_official_channel": 15,
    "did_not_share_personal_info": 20,
    "did_not_share_auth_info": 20,
    "rejected_money_request": 15,
    "rejected_suspicious_link": 10,
    "maintained_verification_under_pressure": 5,
}
SAFE_OUTCOME_BONUS = 25


def start_training(db: Session, user_id: int, level: int) -> TrainingProgress:
    progress = TrainingProgress(
        user_id=user_id,
        level=level,
        status="진행중",
        score=0,
    )
    db.add(progress)
    db.commit()
    db.refresh(progress)
    return progress


def calculate_training_score(report: dict) -> int:
    checks = {
        "verified_identity": report["verified_identity"],
        "used_official_channel": report["used_official_channel"],
        "did_not_share_personal_info": not report["shared_personal_info"],
        "did_not_share_auth_info": not report["shared_auth_info"],
        "rejected_money_request": not report["accepted_money_request"],
        "rejected_suspicious_link": not report["accepted_suspicious_link"],
        "maintained_verification_under_pressure": report[
            "maintained_verification_under_pressure"
        ],
    }
    score = sum(weight for key, weight in RUBRIC_WEIGHTS.items() if checks[key])

    # 신원·공식 채널 확인 절차를 밟지 않았더라도 실제 피해(개인정보/인증정보 공유,
    # 송금·링크 수락)를 하나도 안 냈다면 그 자체로 "안전" 등급(90점) 바닥을 보장한다
    # (65점 + 25점 보너스 = 90). 절차까지 지켰다면 그만큼 90~100 사이에서 더 올라간다.
    # 완벽 점수는 100으로 제한한다.
    avoided_all_harm = all(
        (
            not report["shared_personal_info"],
            not report["shared_auth_info"],
            not report["accepted_money_request"],
            not report["accepted_suspicious_link"],
        )
    )
    if avoided_all_harm:
        score += SAFE_OUTCOME_BONUS

    return min(score, 100)


def grade_training_score(score: int) -> str:
    if score >= 90:
        return "안전"
    if score >= 70:
        return "양호"
    if score >= 50:
        return "주의"
    return "위험"


def finish_training(
    db: Session,
    training_progress_id: int,
    final_score: int,
) -> TrainingProgress:
    progress = db.query(TrainingProgress).filter_by(id=training_progress_id).one()
    progress.status = "완료"
    progress.score = final_score
    progress.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(progress)
    return progress
