STATE_S1 = "S1_APPROACH"
STATE_S2 = "S2_INFO_REQUEST"
STATE_S3 = "S3_URGENCY_PRESSURE"
STATE_END = "END"


def get_next_state(current_state, user_message):
    """
    현재 state와 사용자 말을 보고
    다음 state를 결정한다.
    """

    # S1에서는 사용자가 반응하면 S2로 이동
    if current_state == STATE_S1:
        return STATE_S2

    # S2에서는 사용자가 의심/거부하면 S3로 이동
    if current_state == STATE_S2:
        suspicious_words = [
            "왜",
            "이상",
            "싫",
            "안 할",
            "못",
            "의심",
            "필요"
        ]

        for word in suspicious_words:
            if word in user_message:
                return STATE_S3

        # 아직 거부하지 않았으면 S2 유지
        return STATE_S2

    # S3 이후에는 일단 종료
    if current_state == STATE_S3:
        return STATE_END

    return STATE_END