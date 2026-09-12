from __future__ import annotations

from sqlalchemy.orm import Session

from backend.training.attacker_service import AttackerService
from backend.training.state_machine import (
    STATE_S1,
    STATE_END,
    get_next_state,
)

from backend.training.training_service import (
    handle_user_reply,
)


# =========================
# Attacker AI 객체
# =========================

attacker_service = AttackerService()


# =========================
# 1. Training 대화 세션 시작
# =========================

def create_training_session() -> dict:
    """
    Attacker AI 대화를 위한 임시 세션 상태를 만든다.

    주의:
    messages에는 실제 대화 원문이 들어가지만
    DB에는 저장하지 않고 실행 중 메모리에서만 사용한다.
    """

    return {
        "state": STATE_S1,
        "turn_no": 1,
        "messages": [],
    }


# =========================
# 2. Attacker AI 메시지 생성
# =========================

def generate_attacker_message(
    session: dict,
) -> str:
    """
    현재 state와 대화 내용을 기반으로
    Attacker AI의 다음 메시지를 생성한다.
    """

    messages = session["messages"]

    # 첫 호출에서는 Claude API가 빈 messages를 허용하지 않으므로
    # 시작용 메시지를 임시로 전달
    if not messages:
        messages_for_llm = [
            {
                "role": "user",
                "content": "보안 훈련 시뮬레이션을 시작하세요.",
            }
        ]
    else:
        messages_for_llm = messages

    attacker_message = attacker_service.generate_message(
        state=session["state"],
        messages=messages_for_llm,
    )

    # 실제 세션에는 Attacker 응답만 기록
    session["messages"].append(
        {
            "role": "assistant",
            "content": attacker_message,
        }
    )

    return attacker_message


# =========================
# 3. 사용자 답장 처리
# =========================

def process_user_reply(
    db: Session,
    training_progress_id: int,
    session: dict,
    user_reply: str,
) -> dict:
    """
    사용자 답장 한 턴을 처리한다.

    흐름:
    1. 사용자 답장 scan
    2. TrainingEvent 기록
    3. 대화 세션에 사용자 답장 임시 저장
    4. 상태머신으로 다음 state 결정
    5. 다음 turn으로 이동
    """

    current_state = session["state"]
    turn_no = session["turn_no"]

    # ---------------------------------
    # 1. 사용자 답장 검사 + DB 이벤트 기록
    # ---------------------------------
    scan_result = handle_user_reply(
        db=db,
        training_progress_id=training_progress_id,
        turn_no=turn_no,
        user_reply=user_reply,
    )

    # ---------------------------------
    # 2. Attacker AI 문맥용 임시 대화 기록
    # ---------------------------------
    session["messages"].append(
        {
            "role": "user",
            "content": user_reply,
        }
    )

    # ---------------------------------
    # 3. 상태머신으로 다음 state 결정
    # ---------------------------------
    next_state = get_next_state(
        current_state=current_state,
        user_message=user_reply,
    )

    session["state"] = next_state
    session["turn_no"] += 1

    # ---------------------------------
    # 4. 결과 반환
    # ---------------------------------
    return {
        "scan_result": scan_result,
        "previous_state": current_state,
        "next_state": next_state,
        "turn_no": turn_no,
        "is_finished": next_state == STATE_END,
    }