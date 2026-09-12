from scenarios import SCENARIO_LV2_IT


scenario = SCENARIO_LV2_IT

print("시나리오:", scenario["name"])
print("난이도:", scenario["level"])

print("\n=== 훈련 시작 ===")

current_state = "S1_APPROACH"

while current_state != "END":

    state = scenario["states"][current_state]

    print("\n현재 상태:", current_state)
    print("공격 목표:", state["goal"])
    print("Attacker:", state["example"])

    current_state = state["next"]

print("\n=== 훈련 종료 ===")


from prompts import ATTACKER_PROMPT

print("\n=== Attacker Prompt 테스트 ===")

prompt = ATTACKER_PROMPT.format(
    state="S1_APPROACH",
    state_goal="IT팀을 사칭해 신뢰를 얻는다.",
    history="",
    user_input="네, 무슨 일이죠?"
)

print(prompt)