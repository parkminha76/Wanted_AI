from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

RUBRIC_KEYS = (
    "verified_identity",
    "used_official_channel",
    "shared_personal_info",
    "shared_auth_info",
    "accepted_money_request",
    "accepted_suspicious_link",
    "maintained_verification_under_pressure",
)
LIST_KEYS = ("risky_actions", "good_actions", "improvements")
DEFENDER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "training_defender_report",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                **{key: {"type": "boolean"} for key in RUBRIC_KEYS},
                **{
                    key: {"type": "array", "items": {"type": "string"}}
                    for key in LIST_KEYS
                },
                "summary": {"type": "string"},
            },
            "required": [*RUBRIC_KEYS, *LIST_KEYS, "summary"],
            "additionalProperties": False,
        },
    },
}


def _normalize_report(raw: dict[str, Any], shared_fields: list[str]) -> dict:
    report = {key: raw.get(key) is True for key in RUBRIC_KEYS}
    # 명확한 형식이 치환된 경우 모델 판정보다 서버 관측값을 우선한다.
    if shared_fields:
        report["shared_personal_info"] = True

    for key in LIST_KEYS:
        value = raw.get(key, [])
        report[key] = [str(item) for item in value] if isinstance(value, list) else []

    report["summary"] = str(raw.get("summary", ""))
    return _ensure_korean_feedback(report)


def _contains_korean(value: str) -> bool:
    return any("가" <= char <= "힣" for char in value)


_NON_DISCLOSURE_PHRASES = (
    "제공하지 않",
    "공유하지 않",
    "전달하지 않",
    "알려주지 않",
    "응하지 않",
    "거부",
)


def _describes_non_disclosure(value: str) -> bool:
    """Detect feedback that praises withholding requested information."""
    return any(phrase in value for phrase in _NON_DISCLOSURE_PHRASES)


def _deduplicate(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def _remove_completed_improvements(report: dict) -> None:
    """Drop recommendations for verification steps already completed."""
    improvements = report["improvements"]
    if report["verified_identity"]:
        improvements = [
            item
            for item in improvements
            if not ("신원" in item and any(word in item for word in ("확인", "검증")))
        ]
    if report["used_official_channel"]:
        improvements = [
            item
            for item in improvements
            if not (
                "공식" in item
                and any(word in item for word in ("채널", "연락처", "대표번호"))
            )
        ]
    report["improvements"] = improvements


def _ensure_korean_feedback(report: dict) -> dict:
    """모델이 영문 키/문장을 반환해도 화면용 피드백은 한국어로 고정한다."""
    _remove_completed_improvements(report)
    generated_good = []
    generated_risky = []
    generated_improvements = []

    if report["verified_identity"]:
        generated_good.append("발신자의 신원을 확인했습니다.")
    else:
        generated_improvements.append("요청에 응하기 전에 발신자의 신원을 확인하세요.")

    if report["used_official_channel"]:
        generated_good.append("공식 채널을 이용해 요청을 다시 확인했습니다.")
    else:
        generated_improvements.append("알려진 공식 연락처로 직접 재확인하세요.")

    if report["shared_personal_info"]:
        generated_risky.append("발신자를 확인하기 전에 개인정보를 공유했습니다.")
        generated_improvements.append("신원이 확인되기 전에는 개인정보를 제공하지 마세요.")
    else:
        generated_good.append("개인정보나 연락처 요청에 응하지 않고 정보를 제공하지 않았습니다.")
    if report["shared_auth_info"]:
        generated_risky.append("비밀번호나 인증정보를 공유했습니다.")
        generated_improvements.append("인증정보는 누구에게도 전달하지 마세요.")
    if report["accepted_money_request"]:
        generated_risky.append("검증되지 않은 금전 요청을 받아들였습니다.")
        generated_improvements.append("송금·결제 요청은 별도 결재 절차로 확인하세요.")
    if report["accepted_suspicious_link"]:
        generated_risky.append("확인되지 않은 링크나 파일 요청을 받아들였습니다.")
        generated_improvements.append("링크나 파일은 출처를 확인한 뒤 이용하세요.")

    if report["maintained_verification_under_pressure"]:
        generated_good.append("압박 상황에서도 확인 절차를 유지했습니다.")
    else:
        generated_improvements.append("급한 요청일수록 멈추고 확인 절차를 유지하세요.")

    # 모델이 "요청받았으나 제공하지 않음"을 위험 행동으로 잘못 표현하는
    # 경우가 있다. 비공개·거부는 안전 행동이므로 의미를 기준으로 이동시킨다.
    moved_to_good = [
        item for item in report["risky_actions"] if _describes_non_disclosure(item)
    ]
    if moved_to_good:
        report["risky_actions"] = [
            item for item in report["risky_actions"] if item not in moved_to_good
        ]
        report["good_actions"] = [*report["good_actions"], *moved_to_good]

    replacements = {
        "risky_actions": generated_risky,
        "good_actions": generated_good,
        "improvements": generated_improvements,
    }
    for key, fallback in replacements.items():
        if any(not _contains_korean(item) for item in report[key]):
            report[key] = fallback
        report[key] = _deduplicate(report[key])

    if not _contains_korean(report["summary"]):
        if generated_risky:
            report["summary"] = "일부 위험 행동이 확인되었습니다. 다음에는 요청을 수행하기 전에 발신자와 경로를 먼저 확인하세요."
        elif not report["verified_identity"] or not report["used_official_channel"]:
            report["summary"] = "위험한 요청에는 응하지 않았습니다. 발신자 신원과 공식 채널 확인까지 더하면 더욱 안전한 대응입니다."
        else:
            report["summary"] = "위험한 요청을 피하고 확인 절차를 유지해 안전하게 대응했습니다."

    return report


def generate_defender_report(
    *,
    level: int,
    scenario: dict,
    history: list[dict],
    shared_fields: list[str],
) -> dict:
    """치환된 대화만 OpenAI에 전달해 고정 Rubric의 판정값을 받는다."""
    client = OpenAI()
    payload = {
        "level": level,
        "scenario": {
            "id": scenario["id"],
            "name": scenario["name"],
            "goal": scenario["goal"],
        },
        "history": history,
        "server_observed_shared_fields": shared_fields,
    }
    prompt = f"""
다음 보안 훈련 대화를 고정 Rubric으로 판정하세요.
대화의 마커([PHONE], [EMAIL], [ACCOUNT], [CARD], [RRN])는 사용자가 실제 정보를 공유했다는 뜻입니다.
점수나 등급은 만들지 마세요. 각 boolean은 대화에서 확인되는 행동만 근거로 판정하세요.
마침표나 물음표 등 구두점만 있는 사용자 응답은 어떤 행동의 근거로도 사용하지 마세요.
개인정보·담당자 성함·직통 연락처 등을 요청받았지만 제공하지 않은 행동은 위험 행동이 아니라 잘한 행동입니다.
요청받았다는 사실과 사용자가 실제로 제공했다는 사실을 구분하세요.
모든 risky_actions, good_actions, improvements, summary 값은 자연스러운 한국어 문장으로 작성하세요.
영어 문장이나 verified_identity 같은 필드명을 배열 값으로 사용하지 마세요.

판정 항목:
- verified_identity: 발신자의 신원을 검증했는가
- used_official_channel: 알려진 공식 채널로 직접 재확인했는가
- shared_personal_info: 개인정보를 공유했는가
- shared_auth_info: 비밀번호, OTP, 인증코드 등 인증정보를 공유했는가
- accepted_money_request: 송금·결제·계좌변경 요청을 수락했는가
- accepted_suspicious_link: 의심 링크·파일·외부 업로드 요청을 수락했는가
- maintained_verification_under_pressure: 압박 중에도 확인 절차를 유지했는가

반드시 다음 키만 가진 JSON 객체로 답하세요:
verified_identity, used_official_channel, shared_personal_info, shared_auth_info,
accepted_money_request, accepted_suspicious_link,
maintained_verification_under_pressure, risky_actions, good_actions,
improvements, summary

훈련 데이터:
{json.dumps(payload, ensure_ascii=False)}
""".strip()

    response = client.chat.completions.create(
        model=os.getenv("OPENAI_DEFENDER_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": "당신은 보안 훈련 대화를 일관된 기준으로 판정하는 Defender입니다. JSON만 반환합니다.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format=DEFENDER_RESPONSE_FORMAT,
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    raw = json.loads(content)
    if not isinstance(raw, dict):
        raise ValueError("Defender 응답이 JSON 객체가 아닙니다.")
    return _normalize_report(raw, shared_fields)
