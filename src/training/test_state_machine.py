from src.training.state_machine import get_next_state


state = "S1_APPROACH"

print("현재 상태:", state)

state = get_next_state(
    state,
    "네, 무슨 일이시죠?"
)

print("다음 상태:", state)


state = get_next_state(
    state,
    "그건 왜 필요하신가요? 좀 이상한데요."
)

print("다음 상태:", state)


state = get_next_state(
    state,
    "싫습니다."
)

print("다음 상태:", state)