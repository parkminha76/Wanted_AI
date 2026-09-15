"""User-selectable masking policy and standard partial masking rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.shared.schema import TYPE_LABELS


MASKING_ACTIONS = ("full", "standard")
DEFAULT_MASKING_POLICY = {"default": "full", "rules": {}}

# Descriptions are returned by GET /masking/options so the frontend does not
# need to duplicate backend behavior.
STANDARD_RULE_DESCRIPTIONS: dict[str, str] = {
    "person": "한글 이름은 첫 글자, 영문 이름은 앞 2글자를 남기고 마스킹",
    "birth_date": "연도만 남기고 월·일 마스킹",
    "phone": "뒤 4자리 마스킹",
    "address": "시·도/시·군·구/도로명 또는 읍·면·동까지 남기고 상세주소 마스킹",
    "email": "아이디가 3자 이하면 첫 1자, 4자 이상이면 앞 3자를 남기고 마스킹",
    "rrn": "뒷자리 첫 숫자만 남기고 나머지 6자리 마스킹",
    "foreign_reg": "뒷자리 첫 숫자만 남기고 나머지 6자리 마스킹",
    "corp_reg": "뒷자리 첫 숫자만 남기고 나머지 6자리 마스킹",
    "passport": "앞 6자리 이후 마스킹",
    "account": "숫자 앞 6자리 이후 마스킹",
    "driver_license": "숫자 앞 4자리 이후 마스킹",
    "card": "가운데 8자리 마스킹",
    "ip": "IPv4의 세 번째 옥텟 마스킹",
}


def normalize_policy(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and canonicalize a masking policy.

    Shape:
        {"default": "full", "rules": {"person": "standard"}}
    """
    if value is None:
        return {"default": "full", "rules": {}}
    if not isinstance(value, dict):
        raise ValueError("masking_policy는 JSON 객체여야 합니다")

    unknown = set(value) - {"default", "rules"}
    if unknown:
        raise ValueError(f"지원하지 않는 masking_policy 키: {sorted(unknown)}")

    default = value.get("default", "full")
    if default not in MASKING_ACTIONS:
        raise ValueError("masking_policy.default는 full 또는 standard여야 합니다")

    rules = value.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("masking_policy.rules는 객체여야 합니다")

    normalized_rules: dict[str, str] = {}
    for risk_type, action in rules.items():
        if risk_type not in TYPE_LABELS:
            raise ValueError(f"지원하지 않는 개인정보 유형: {risk_type}")
        if action not in MASKING_ACTIONS:
            raise ValueError(f"{risk_type}의 마스킹 방식은 full 또는 standard여야 합니다")
        normalized_rules[risk_type] = action

    return {"default": default, "rules": dict(sorted(normalized_rules.items()))}


def action_for(policy: dict[str, Any], risk_type: str) -> str:
    return policy["rules"].get(risk_type, policy["default"])


def _mask_after_n_digits(value: str, visible_digits: int) -> str:
    seen = 0
    out: list[str] = []
    for char in value:
        if char.isdigit():
            seen += 1
            out.append(char if seen <= visible_digits else "*")
        else:
            out.append(char)
    return "".join(out)


def _mask_digit_positions(value: str, start: int, end: int) -> str:
    index = 0
    out: list[str] = []
    for char in value:
        if char.isdigit():
            out.append("*" if start <= index < end else char)
            index += 1
        else:
            out.append(char)
    return "".join(out)


def _mask_person(value: str) -> str:
    if re.search(r"[가-힣]", value):
        out: list[str] = []
        visible = False
        for char in value:
            if char.isspace() or not (char.isalpha() or char.isdigit()):
                out.append(char)
                visible = False
            elif not visible:
                out.append(char)
                visible = True
            else:
                out.append("*")
        return "".join(out)

    remaining = 2
    out = []
    for char in value:
        if char.isalpha():
            if remaining:
                out.append(char)
                remaining -= 1
            else:
                out.append("*")
        else:
            out.append(char)
    return "".join(out)


def _mask_email(value: str) -> str:
    if "@" not in value:
        return value
    local, domain = value.rsplit("@", 1)
    visible = 1 if len(local) <= 3 else 3
    masked_local = local[:visible] + "*" * max(0, len(local) - visible)
    return f"{masked_local}@{domain}"


def _mask_address(value: str) -> str:
    parts = value.split()
    if len(parts) <= 3:
        return value
    return " ".join(parts[:3]) + " ****"


def _mask_ip(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 4 or not all(part.isdigit() for part in parts):
        return value
    parts[2] = "***"
    return ".".join(parts)


def standard_mask(risk_type: str, value: str, fallback: str) -> str:
    """Return the standard partial representation or the full-mask fallback."""
    if not value:
        return fallback

    if risk_type == "person":
        masked = _mask_person(value)
    elif risk_type == "birth_date":
        masked = _mask_after_n_digits(value, 4)
    elif risk_type == "phone":
        digit_count = sum(char.isdigit() for char in value)
        masked = _mask_digit_positions(value, max(0, digit_count - 4), digit_count)
    elif risk_type == "address":
        masked = _mask_address(value)
    elif risk_type == "email":
        masked = _mask_email(value)
    elif risk_type in {"rrn", "foreign_reg", "corp_reg"}:
        masked = _mask_after_n_digits(value, 7)
    elif risk_type == "passport":
        seen = 0
        chars: list[str] = []
        for char in value:
            if char.isalnum():
                seen += 1
                chars.append(char if seen <= 6 else "*")
            else:
                chars.append(char)
        masked = "".join(chars)
    elif risk_type == "account":
        masked = _mask_after_n_digits(value, 6)
    elif risk_type == "driver_license":
        masked = _mask_after_n_digits(value, 4)
    elif risk_type == "card":
        masked = _mask_digit_positions(value, 4, 12)
    elif risk_type == "ip":
        masked = _mask_ip(value)
    else:
        return fallback

    # A standard rule that cannot hide anything for this input must fail closed.
    return masked if masked != value and "*" in masked else fallback


@dataclass(frozen=True)
class ReplacementFinding:
    """Finding-compatible view with a policy-selected replacement string."""

    original: Any
    replacement: str

    def __getattr__(self, name: str):
        return getattr(self.original, name)

    @property
    def placeholder(self) -> str:
        return self.replacement


def apply_policy(findings, policy: dict[str, Any] | None):
    normalized = normalize_policy(policy)
    selected = []
    for finding in findings:
        action = action_for(normalized, finding.type)
        if action == "standard" and finding.type in STANDARD_RULE_DESCRIPTIONS:
            replacement = standard_mask(finding.type, finding.text, finding.placeholder)
            selected.append(ReplacementFinding(finding, replacement))
        else:
            selected.append(finding)
    return selected


def normalize_selection(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate per-finding selections sent after the preview scan."""
    if not isinstance(value, dict) or set(value) != {"selections"}:
        raise ValueError("선택 정보는 selections 배열만 포함한 JSON 객체여야 합니다")
    rows = value["selections"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("마스킹할 항목을 하나 이상 선택해야 합니다")
    if len(rows) > 10_000:
        raise ValueError("한 번에 선택할 수 있는 항목 수를 초과했습니다")

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    required = {"id", "type", "start", "end", "action"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("각 선택 항목에는 id, type, start, end, action이 필요합니다")
        finding_id = row["id"]
        risk_type = row["type"]
        start, end = row["start"], row["end"]
        action = row["action"]
        if not isinstance(finding_id, str) or not finding_id:
            raise ValueError("선택 항목 id가 올바르지 않습니다")
        if risk_type not in TYPE_LABELS:
            raise ValueError(f"지원하지 않는 개인정보 유형: {risk_type}")
        if type(start) is not int or type(end) is not int or not (0 <= start < end):
            raise ValueError("선택 항목 start/end가 올바르지 않습니다")
        if action not in MASKING_ACTIONS:
            raise ValueError("선택 항목 action은 full 또는 standard여야 합니다")
        key = (finding_id, risk_type, start, end)
        if key in seen:
            raise ValueError("동일한 마스킹 항목이 중복 선택됐습니다")
        seen.add(key)
        normalized.append(
            {"id": finding_id, "type": risk_type, "start": start, "end": end, "action": action}
        )
    return normalized


def apply_selection(findings, selections: list[dict[str, Any]]):
    """Resolve a UI selection against a fresh scan, failing on any mismatch."""
    actions = {
        (row["id"], row["type"], row["start"], row["end"]): row["action"]
        for row in selections
    }
    selected = []
    matched: set[tuple[str, str, int, int]] = set()
    for finding in findings:
        key = (finding.id, finding.type, finding.start, finding.end)
        action = actions.get(key)
        if action is None:
            continue
        matched.add(key)
        if action == "standard" and finding.type in STANDARD_RULE_DESCRIPTIONS:
            replacement = standard_mask(finding.type, finding.text, finding.placeholder)
            selected.append(ReplacementFinding(finding, replacement))
        else:
            selected.append(finding)

    if matched != set(actions):
        raise ValueError("선택한 항목이 현재 파일의 재검사 결과와 일치하지 않습니다")
    return selected


def options_payload() -> dict[str, Any]:
    return {
        "default": DEFAULT_MASKING_POLICY,
        "actions": [
            {"value": "full", "label": "전체 마스킹"},
            {"value": "standard", "label": "표준 부분 마스킹"},
        ],
        "types": [
            {
                "type": risk_type,
                "label": label,
                "supports_standard": risk_type in STANDARD_RULE_DESCRIPTIONS,
                "standard_description": STANDARD_RULE_DESCRIPTIONS.get(
                    risk_type, "표준 부분 마스킹 미지원: 전체 마스킹 적용"
                ),
            }
            for risk_type, label in TYPE_LABELS.items()
        ],
        "request_example": {
            "default": "full",
            "rules": {
                "person": "standard",
                "phone": "standard",
                "address": "standard",
            },
        },
        "selection_example": {
            "selections": [
                {
                    "id": "f_001",
                    "type": "phone",
                    "start": 4,
                    "end": 17,
                    "action": "standard",
                }
            ]
        },
    }

