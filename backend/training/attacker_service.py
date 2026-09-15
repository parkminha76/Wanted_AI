from backend.training.anthropic_client import AnthropicClient
from backend.training.prompts import build_attacker_prompt


class AttackerService:
    def __init__(self):
        self.llm = AnthropicClient()

    def generate_message(
        self,
        *,
        state: str,
        level: int,
        scenario: dict,
        messages: list[dict],
    ) -> str:
        system_prompt = build_attacker_prompt(
            state=state,
            level=level,
            scenario=scenario,
        )
        return self.llm.generate(system_prompt=system_prompt, messages=messages)
