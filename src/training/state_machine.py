from scenarios import SCENARIO_LV2_IT


class TrainingStateMachine:
    def __init__(self):
        self.scenario = SCENARIO_LV2_IT
        self.current_state = "S1_APPROACH"

    def get_current_state(self):
        return self.scenario["states"][self.current_state]

    def move_next(self):
        next_state = self.get_current_state()["next"]
        self.current_state = next_state

    def is_finished(self):
        return self.current_state == "END"