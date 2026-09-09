SCENARIO_LV2_IT = {
    "name": "사내 IT팀 사칭",
    "level": 2,

    "states": {
        "S1_APPROACH": {
            "goal": "IT팀을 사칭해 신뢰를 얻는다.",
            "example": "비정상 로그인 시도가 감지되어 연락드렸습니다.",
            "next": "S2_LINK"
        },

        "S2_LINK": {
            "goal": "가짜 보안 링크 접속을 유도한다.",
            "example": "아래 보안 페이지에서 확인해주세요.",
            "next": "S3_INFO"
        },

        "S3_INFO": {
            "goal": "업무 이메일 등 개인정보를 요구한다.",
            "example": "업무 이메일 주소를 알려주시겠어요?",
            "next": "S4_PRESSURE"
        },

        "S4_PRESSURE": {
            "goal": "긴급성을 이용해 판단 시간을 줄인다.",
            "example": "지금 확인하지 않으면 계정이 잠길 수 있습니다.",
            "next": "S5_VERIFY"
        },

        "S5_VERIFY": {
            "goal": "OTP 등 인증정보를 요구한다.",
            "example": "6자리 인증번호를 알려주세요.",
            "next": "END"
        }
    }
}