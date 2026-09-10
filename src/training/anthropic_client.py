import os

from anthropic import Anthropic
from dotenv import load_dotenv


load_dotenv()


class AnthropicClient:

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되어 있지 않습니다."
            )

        self.client = Anthropic(
            api_key=api_key
        )

        self.model = os.getenv(
            "ANTHROPIC_MODEL",
            "claude-sonnet-5"
        )

    def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 300
    ) -> str:

        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages
        )

        texts = []

        for block in response.content:
            if block.type == "text":
                texts.append(block.text)

        return "\n".join(texts).strip()