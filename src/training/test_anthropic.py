import os

from anthropic import Anthropic
from dotenv import load_dotenv

from src.training.prompts import build_attacker_prompt


load_dotenv()

client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# 현재 state에 맞는 프롬프트 가져오기
system_prompt = build_attacker_prompt("S1_APPROACH")


response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=300,
    system=system_prompt,
    messages=[
        {
            "role": "user",
            "content": "무슨 일인가요?"
        }
    ]
)


print("=== Claude 응답 ===")

for block in response.content:
    if block.type == "text":
        print(block.text)
