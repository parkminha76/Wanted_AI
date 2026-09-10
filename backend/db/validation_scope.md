# 검증(`@validates`)이 실제로 커버하는 범위

`db/tables.py`의 `@validates` 데코레이터(`FindingRow.type`, `FindingRow.evidence`,
`ScanResultRow.finding_counts`, `TrainingEvent.detected_field`)는 **SQLAlchemy
ORM 인스턴스의 속성 재할당**에만 반응한다. 이건 SQLAlchemy 공식 문서에
명시된 동작이다: https://docs.sqlalchemy.org/en/20/orm/mapped_attributes.html

## 커버됨 (지금 코드베이스에서 실제로 쓰는 경로)

- `FindingRow(type="account", evidence={...})` — 객체 생성 시 키워드 인자 대입
- `finding.type = "account"` — 생성 후 속성 재할당
- `scan_result.finding_counts = {...}` — 통째로 재할당
- `db/converters.py`의 `save_scan_result()`, `record_training_event()`가
  전부 이 방식(ORM 객체 생성)으로 저장하므로, **지금 코드베이스의 유일한
  저장 경로는 이미 이중으로 보호되어 있다** (converter의 명시적 호출 +
  ORM 속성 할당 시 재검증).

## 커버 안 됨 — 앞으로 이런 경로를 추가한다면 주의

| 경로 | 왜 안 걸리나 | 새로 추가할 경우 해야 할 것 |
|---|---|---|
| `Session.execute(insert(FindingRow), [...])` (Core bulk insert) | ORM 인스턴스를 아예 안 거침 | 삽입할 dict를 만들 때 `sanitize_evidence()`, `validate_risk_type()`을 직접 호출 |
| `session.bulk_insert_mappings(FindingRow, [...])` | 위와 동일 | 위와 동일 |
| 원시 SQL (`db.execute(text("INSERT INTO findings ..."))`) | ORM을 아예 안 씀 | 애초에 이 경로를 쓰지 말 것. 꼭 써야 하면 삽입 전 애플리케이션 코드에서 수동 검증 |
| `finding.evidence["key"] = value` (dict 내부 변형) | 속성 **재할당**이 아니라 기존 dict의 `__setitem__` — SQLAlchemy가 감지하는 이벤트가 아님 | 절대 이렇게 쓰지 말 것. `finding.set_evidence({...})` 사용 |
| `scan_result.finding_counts["account"] += 1` (dict 내부 변형) | 위와 동일 | `scan_result.add_finding_count("account")` 사용 |

## 지금 팀에 필요한 조치

1. **지금은 안전함** — B/C가 `db/converters.py`의 함수만 통해서 저장하고
   있다면 위 표의 위험한 경로는 하나도 안 쓰고 있는 것이다.
2. **앞으로 성능 최적화 등의 이유로 bulk insert를 도입하게 되면**, 이
   문서를 다시 보고 해당 경로에 검증을 수동으로 추가할 것.
3. **evidence/finding_counts를 갱신할 일이 생기면** 항상 `set_evidence()`,
   `add_finding_count()`를 쓰고, dict 내부를 직접 고치지 말 것 — 코드
   리뷰 시 `["..."] = ` 형태의 대입이 evidence/finding_counts에 있으면
   지적할 것.