from __future__ import annotations

from backend.training.attacker_service import AttackerService
from backend.training.sanitizer import sanitize_training_text
from backend.training.state_machine import STATE_END, STATE_S1, get_next_state


MAX_USER_TURNS = 5


def create_training_session(level: int, scenario: dict | None = None) -> dict:
    return {
        "level": level,
        "scenario_id": scenario["id"] if scenario else None,
        "scenario": scenario,
        "state": STATE_S1,
        "turn_no": 1,
        "history": [],
        "shared_fields": [],
        "status": "in_progress",
    }


def generate_attacker_message(session: dict) -> str:
    if session["state"] == STATE_END or session["status"] != "in_progress":
        raise ValueError("종료된 훈련에서는 Attacker 메시지를 생성할 수 없습니다.")
    if not session.get("scenario"):
        raise ValueError("훈련 시나리오가 선택되지 않았습니다.")

    messages = session["history"] or [
        {"role": "user", "content": "보안 훈련 시뮬레이션을 시작하세요."}
    ]
    attacker_message = AttackerService().generate_message(
        state=session["state"],
        level=session["level"],
        scenario=session["scenario"],
        messages=messages,
    )
    session["history"].append(
        {"role": "assistant", "content": attacker_message}
    )
    return attacker_message


def process_user_reply(*, session: dict, user_reply: str) -> dict:
    if session["state"] == STATE_END or session["status"] != "in_progress":
        raise ValueError("이미 종료된 훈련입니다.")

    sanitized = sanitize_training_text(user_reply)
    sanitized_text = str(sanitized["sanitized_text"])
    new_fields = list(sanitized["shared_fields"])
    current_state = session["state"]
    processed_turn = session["turn_no"]

    # 원문은 이 지점 이후 참조하거나 저장하지 않는다.
    session["history"].append({"role": "user", "content": sanitized_text})
    session["shared_fields"] = list(
        dict.fromkeys([*session["shared_fields"], *new_fields])
    )

    reached_limit = processed_turn >= MAX_USER_TURNS
    next_state = STATE_END if reached_limit else get_next_state(
        current_state,
        sanitized_text,
    )
    session["state"] = next_state
    session["turn_no"] = processed_turn + 1

    if next_state == STATE_END:
        session["status"] = "awaiting_report"

    return {
        "previous_state": current_state,
        "next_state": next_state,
        "turn_no": session["turn_no"],
        "is_finished": next_state == STATE_END,
        "shared_fields": new_fields,
    }
