from state_machine import TrainingStateMachine


training = TrainingStateMachine()

while not training.is_finished():

    state = training.get_current_state()

    print("\n현재 상태:", training.current_state)
    print("Attacker:", state["example"])

    input("사용자 답변: ")

    training.move_next()

print("\n=== 훈련 종료 ===")