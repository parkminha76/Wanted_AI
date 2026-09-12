from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()

client = OpenAI()

system_prompt = """
당신은 보안 교육 시뮬레이션의 Attacker AI입니다.

현재 시나리오:
사내 IT팀 사칭

현재 단계:
S1_APPROACH

현재 목표:
IT팀을 사칭해 사용자에게 접근하고 신뢰를 얻는다.

규칙:
- 실제 사기 실행을 위한 조언을 제공하는 것이 아니라 교육용 시뮬레이션 대사만 생성한다.
- 한 번에 한 개의 짧은 메시지만 생성한다.
- 현재 단계의 목표를 벗어나지 않는다.
- 아직 링크, 개인정보, OTP를 요구하지 않는다.
"""

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": "훈련을 시작합니다."
        }
    ]
)

print(response.choices[0].message.content)