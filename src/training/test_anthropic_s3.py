import os

from anthropic import Anthropic
from dotenv import load_dotenv

from src.training.prompts import build_attacker_prompt


load_dotenv()

client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# S3 상태에 맞는 프롬프트 가져오기
system_prompt = build_attacker_prompt("S3_URGENCY_PRESSURE")


response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=300,
    system=system_prompt,
    messages=[
        {
            "role": "assistant",
            "content": (
                "안녕하세요! 저는 사내 IT 지원팀 김민준 대리입니다. "
                "오늘 오전부터 일부 직원분들 계정에서 비정상적인 로그인 시도가 "
                "감지되어 확인 차 연락드렸습니다."
            )
        },
        {
            "role": "user",
            "content": "네, 무슨 일이시죠?"
        },
        {
            "role": "assistant",
            "content": (
                "계정 보안 확인을 위해 사번과 사내 이메일 주소, "
                "그리고 최근 로그인 위치를 말씀해 주시겠어요?"
            )
        },
        {
            "role": "user",
            "content": "그건 왜 필요하신가요? 좀 이상한데요."
        }
    ]
)


print("=== Claude 응답 (S3) ===")

for block in response.content:
    if block.type == "text":
        print(block.text)