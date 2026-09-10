"""
backend/shared/schema.py의 dataclass <-> DB row 변환 (v3)
=============================================================

v2 -> v3 핵심 변경:
  - Finding.reason(자유 텍스트)을 그대로 저장하지 않고 derive_reason_code()로
    고정 코드 변환.
  - ScanResult.error(자유 텍스트)도 derive_error_code()로 고정 코드 변환.
  - Finding.evidence는 sanitize_evidence()의 화이트리스트를 반드시 거친다.
  - hidden_commands는 finding_id만 받는다 (scan_result_id 없음).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.tables import FindingRow, HiddenCommandRow, ScanResultRow, TrainingEvent, TrainingProgress
from backend.db.codes import derive_error_code, derive_reason_code, sanitize_evidence
from backend.shared.schema import ScanResult


def save_scan_result(
    db: Session, user_id: int, result: ScanResult, file_extension: str = ""
) -> ScanResultRow:
    """스캔 직후 한 번 호출. 원문/마스킹 사본은 저장하지 않고, 원문 없이
    집계 및 탐지 메타데이터만 저장한다.

    실제 원문이 필요한 화면(하이라이트, 마스킹 비교)은 이 함수 호출 전에
    result.to_dict()를 그대로 API 응답으로 내려보낸 뒤 버려야 한다.
    """
    all_findings = list(result.findings) + list(result.filtered_out)

    finding_counts: dict[str, int] = {}
    for f in result.findings:
        finding_counts[f.type] = finding_counts.get(f.type, 0) + 1

    row = ScanResultRow(
        user_id=user_id,
        file_extension=file_extension,
        risk_score=result.risk_score,
        error_code=derive_error_code(result.error),
        status="실패" if result.error else "완료",
        finding_counts=finding_counts,
        filtered_count=len(result.filtered_out),
        has_hidden_command=result.has_hidden_command,
    )
    db.add(row)
    db.flush()

    finding_rows: dict[str, FindingRow] = {}
    for f in all_findings:
        clean_evidence = sanitize_evidence(f.evidence)
        frow = FindingRow(
            scan_result_id=row.id,
            finding_ref=f.id,
            type=f.type,
            confidence=f.confidence,
            source=f.source,
            reason_code=derive_reason_code(f.type, f.source, f.confidence, clean_evidence),
            page=f.page,
            evidence=clean_evidence,
            excluded=f in result.filtered_out,
        )
        db.add(frow)
        db.flush()
        finding_rows[f.id] = frow

    for f in all_findings:
        if f.type in ("hidden_text", "injection"):
            db.add(HiddenCommandRow(
                finding_id=finding_rows[f.id].id,
                status="확인필요",
            ))

    return row


def get_hidden_commands_for_scan(db: Session, scan_result_id: int) -> list[HiddenCommandRow]:
    """이 스캔에 속한 hidden_command들을 findings를 통해 조인해서 구한다.
    hidden_commands 테이블 자체엔 scan_result_id가 없다 (v3에서 제거).
    """
    return (
        db.query(HiddenCommandRow)
        .join(FindingRow, HiddenCommandRow.finding_id == FindingRow.id)
        .filter(FindingRow.scan_result_id == scan_result_id)
        .all()
    )


def record_training_event(
    db: Session,
    training_progress_id: int,
    turn_no: int,
    result: ScanResult | None,
    action: str,
) -> TrainingEvent:
    """훈련 중 답장 스캔 결과를 턴 단위로 기록. 사용자가 입력한 원문은
    애초에 인자로 받지 않는다 — result에서 detected_field만 뽑아 쓴다.
    """
    detected_field = result.findings[0].type if (result and result.findings) else None
    event = TrainingEvent(
        training_progress_id=training_progress_id,
        turn_no=turn_no,
        detected_field=detected_field,
        action=action,
    )
    db.add(event)
    return event


def build_defender_payload(db: Session, training_progress_id: int) -> dict:
    """Defender AI에게 넘길 비식별 행동 로그. 원문 대화 내용은 포함하지 않는다.

    반환 형식:
        {
          "level": 2,
          "turns": [
            {"turn": 1, "action": "경고표시", "detected_type": "email"},
            {"turn": 2, "action": "취소", "detected_type": null}
          ],
          "final_score": 78
        }
    """
    progress = db.query(TrainingProgress).filter_by(id=training_progress_id).one()
    events = (
        db.query(TrainingEvent)
        .filter_by(training_progress_id=training_progress_id)
        .order_by(TrainingEvent.turn_no)
        .all()
    )

    return {
        "level": progress.level,
        "turns": [
            {"turn": e.turn_no, "action": e.action, "detected_type": e.detected_field}
            for e in events
        ],
        "final_score": progress.score,
    }


def scan_summary_from_row(row: ScanResultRow) -> dict:
    """DB에서 읽은 요약을 API 응답 형태로. 원문/하이라이트는 여기서 복원 불가
    (애초에 저장 안 했음) — 스캔 이력 목록/카드 화면 정도에만 쓴다.
    """
    return {
        "id": row.id,
        "file_extension": row.file_extension,
        "risk_score": row.risk_score,
        "status": row.status,
        "error_code": row.error_code,
        "finding_counts": row.finding_counts,
        "filtered_count": row.filtered_count,
        "has_hidden_command": row.has_hidden_command,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }