import re


STATE_S1 = "S1_APPROACH"
STATE_S2 = "S2_INFO_REQUEST"
STATE_S3 = "S3_URGENCY_PRESSURE"
STATE_END = "END"


_SUSPICIOUS_WORDS = (
    "왜", "이상", "의심", "공식", "확인", "대표번호", "직접 연락",
    "싫", "안 할", "못", "필요", "누구", "증명",
)
_FINAL_REFUSALS = (
    "더 이상", "신고", "차단", "응하지 않", "제공하지 않", "안 알려",
    "거절", "종료", "연락하지 마", "공식 채널로 확인",
)


def is_evaluable_reply(user_message: str) -> bool:
    """Return whether a reply contains content that can be evaluated.

    Punctuation-only placeholders such as ``.``, ``...`` or ``?`` are part of
    the conversation, but they do not express a security decision. They must
    therefore neither advance the attack state nor consume a scored turn.
    """
    return re.search(r"[0-9A-Za-z가-힣]", user_message) is not None


def get_next_state(current_state: str, user_message: str) -> str:
    """사용자의 의심·거부 행동에 따라 공격 단계를 조정한다."""
    normalized = user_message.lower().strip()

    if not is_evaluable_reply(normalized):
        return current_state

    if current_state == STATE_S1:
        if any(word in normalized for word in _SUSPICIOUS_WORDS):
            return STATE_S3
        return STATE_S2

    if current_state == STATE_S2:
        if any(word in normalized for word in _SUSPICIOUS_WORDS):
            return STATE_S3
        return STATE_S2

    if current_state == STATE_S3:
        if any(word in normalized for word in _FINAL_REFUSALS):
            return STATE_END
        return STATE_S3

    return STATE_END
