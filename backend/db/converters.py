"""
contract.py의 dataclass(ScanResult, Finding) <-> DB row(ScanResultRow, FindingRow) 변환
=======================================================================================

B가 scan_file()/scan_text()로 만든 결과(메모리상 dataclass)를 DB에 저장할 때,
또는 DB에서 읽어와 다시 API 응답으로 내보낼 때 이 함수들을 거친다.

원칙: contract.py는 절대 건드리지 않는다. 여기서만 변환한다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from db.tables import FindingRow, HiddenCommandRow, ScanResultRow
from backend.shared.schemas import Finding, ScanResult  # B의 계약 파일


def save_scan_result(db: Session, user_id: int, result: ScanResult) -> ScanResultRow:
    """스캔 끝난 직후 한 번 호출. ScanResult 전체(findings, filtered_out 포함)를
    관련 테이블에 나눠서 저장하고, 저장된 ScanResultRow를 돌려준다.
    """
    row = ScanResultRow(
        user_id=user_id,
        filename=result.filename,
        raw_text=result.raw_text,
        masked_text=result.masked_text,
        risk_score=result.risk_score,
        error=result.error,
        status="실패" if result.error else "완료",
        file_id=result.file_id,
        file_type=result.file_type,
        masked_path=result.masked_path,
    )
    db.add(row)
    db.flush()  # row.id를 미리 받기 위해 flush (commit은 호출부에서)

    # findings: excluded=False인 것과 filtered_out(오탐 제거된 것, excluded=True)을
    # 전부 findings 테이블에 같이 넣는다. 지우지 않고 남겨두는 게 원칙(스키마 주석 참고).
    all_findings = list(result.findings) + list(result.filtered_out)
    finding_rows: dict[str, FindingRow] = {}  # finding.id -> FindingRow (hidden_command 연결용)

    for f in all_findings:
        frow = FindingRow(
            scan_result_id=row.id,
            finding_ref=f.id,
            type=f.type,
            text=f.text,
            start=f.start,
            end=f.end,
            confidence=f.confidence,
            source=f.source,
            reason=f.reason,
            page=f.page,
            bbox=list(f.bbox) if f.bbox else None,
            evidence=f.evidence,
            excluded=f in result.filtered_out,
        )
        db.add(frow)
        db.flush()
        finding_rows[f.id] = frow

    # 숨은 명령/인젝션은 findings 안에서 type으로 걸러서 hidden_commands에도 상태 추적용으로 추가
    for f in all_findings:
        if f.type in ("hidden_text", "injection"):
            db.add(HiddenCommandRow(
                scan_result_id=row.id,
                finding_id=finding_rows[f.id].id,
                status="확인필요",
            ))

    return row


def scan_result_from_row(row: ScanResultRow) -> ScanResult:
    """DB에서 읽은 row를 다시 contract.py의 ScanResult로 복원.
    화면(D)에 API로 내려줄 때 이 형태로 맞춰서 .to_dict() 호출.
    """
    findings = []
    filtered_out = []
    for frow in row.findings:
        f = Finding(
            id=frow.finding_ref or f"f_{frow.id:03d}",
            type=frow.type,
            text=frow.text,
            start=frow.start,
            end=frow.end,
            confidence=frow.confidence,
            source=frow.source,
            reason=frow.reason,
            page=frow.page,
            bbox=tuple(frow.bbox) if frow.bbox else None,
            evidence=frow.evidence or {},
        )
        (filtered_out if frow.excluded else findings).append(f)

    result = ScanResult(
        filename=row.filename,
        raw_text=row.raw_text,
        findings=findings,
        risk_score=row.risk_score,
        masked_text=row.masked_text,
        error=row.error,
        filtered_out=filtered_out,
        file_id=row.file_id,
        file_type=row.file_type,
    )
    return result