import os

from anthropic import Anthropic
from dotenv import load_dotenv

from src.training.prompts import build_attacker_prompt
from src.training.state_machine import get_next_state


load_dotenv()

client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)


def call_attacker(state, messages):
    """
    현재 state에 맞는 프롬프트를 만들고
    Claude에게 답변을 요청한다.
    """

    system_prompt = build_attacker_prompt(state)

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        system=system_prompt,
        messages=messages
    )

    for block in response.content:
        if block.type == "text":
            return block.text

    return ""


# 대화 시작 상태
state = "S1_APPROACH"

messages = [
    {
        "role": "user",
        "content": "무슨 일인가요?"
    }
]


# -------------------------
# S1
# -------------------------

print("\n현재 상태:", state)

attacker_message = call_attacker(
    state,
    messages
)

print("Attacker:", attacker_message)

messages.append({
    "role": "assistant",
    "content": attacker_message
})


# 사용자 답장
user_message = "네, 무슨 일이시죠?"

messages.append({
    "role": "user",
    "content": user_message
})

# 다음 state 결정
state = get_next_state(
    state,
    user_message
)


# -------------------------
# S2
# -------------------------

print("\n현재 상태:", state)

attacker_message = call_attacker(
    state,
    messages
)

print("Attacker:", attacker_message)

messages.append({
    "role": "assistant",
    "content": attacker_message
})


# 사용자 의심
user_message = "그건 왜 필요한가요? 좀 이상한데요."

messages.append({
    "role": "user",
    "content": user_message
})

state = get_next_state(
    state,
    user_message
)


# -------------------------
# S3
# -------------------------

print("\n현재 상태:", state)

attacker_message = call_attacker(
    state,
    messages
)

print("Attacker:", attacker_message)