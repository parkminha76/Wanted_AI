from openai import OpenAI
from dotenv import load_dotenv

from backend.db.converters import build_defender_payload


load_dotenv()

client = OpenAI()


def generate_defender_report(db, training_progress_id: int) -> str:

    # 1. DB에서 비식별 훈련 기록 가져오기
    payload = build_defender_payload(
        db=db,
        training_progress_id=training_progress_id,
    )

    # 2. Defender AI 프롬프트 구성
    prompt = f"""
당신은 보안 훈련 결과를 분석하는 Defender AI입니다.

아래 기록에는 실제 사용자의 대화 원문이 포함되어 있지 않습니다.
비식별화된 행동 기록만을 이용해서 분석하세요.

레벨: {payload["level"]}
최종 점수: {payload["final_score"]}
턴별 기록: {payload["turns"]}

다음 내용을 쉽게 설명해주세요.

1. 가장 위험했던 행동
2. 취약했던 정보 유형
3. 잘 대응한 점
4. 다음 훈련에서 개선할 점

사용자를 비난하지 말고,
보안 교육을 받는 일반 사용자가 이해하기 쉽게 설명하세요.
"""

    # 3. OpenAI API 호출
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "당신은 개인정보 보호 및 보안 훈련을 돕는 Defender AI입니다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content