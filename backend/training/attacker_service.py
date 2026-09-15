from backend.training.anthropic_client import AnthropicClient
from backend.training.prompts import build_attacker_prompt


class AttackerService:

    def __init__(self):
        self.llm = AnthropicClient()

    from backend.training.anthropic_client import AnthropicClient
from backend.training.prompts import build_attacker_prompt


class AttackerService:

    def __init__(self):
        self.llm = AnthropicClient()

    def generate_message(
        self,
        state: str,
        level: int,
        messages: list[dict],
    ) -> str:

        system_prompt = build_attacker_prompt(
            state=state,
            level=level,
        )

        attacker_message = self.llm.generate(
            system_prompt=system_prompt,
            messages=messages,
        )

        return attacker_message

        attacker_message = self.llm.generate(
            system_prompt=system_prompt,
            messages=messages
        )

        return attacker_message
