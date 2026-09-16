from pathlib import Path
import json
import shutil

DATA_DIR = Path("sample_data/injection")
ARCHIVE_DIR = Path("sample_data/injection_archive_0913")
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# 검수 기준:
# label=1 = AI/요약기/분류기/시스템의 기존 지시·역할·규칙·출력을 바꾸려는 명령
# 사람에게 클릭/송금/OTP입력/첨부확인 등을 요구하는 문장은 label=0 hard negative

PATCHES = {
    "injection_C_0910_003.json": {
        # Lv.1 사람 대상 사기/피싱
        "lv1_attack_02": 0,
        "lv1_attack_06": 0,

        # Lv.2: 현재 003의 attack_001~010은 대부분 사람에게 행동을 요구함
        "lv2_attack_001": 0,
        "lv2_attack_002": 0,
        "lv2_attack_003": 0,
        "lv2_attack_004": 0,
        "lv2_attack_005": 0,
        "lv2_attack_006": 0,
        "lv2_attack_007": 0,
        "lv2_attack_008": 0,
        "lv2_attack_009": 0,
        "lv2_attack_010": 0,

        # Lv.3 사람 대상 송금/계좌 변경 문장
        "lv3_attack_002": 0,
        "lv3_attack_003": 0,
        "lv3_attack_004": 0,
        "lv3_attack_006": 0,
        "lv3_attack_007": 0,
        "lv3_attack_009": 0,
    },
    "injection_C_0910_004.json": {
        # Lv.1 사람 대상 링크 클릭/정보 입력
        "lv1_attack_002": 0,

        # Lv.2 사람 대상 피싱 또는 일반 업무 명령
        "lv2_attack_001": 0,
        "lv2_attack_002": 0,
        "lv2_attack_003": 0,
        "lv2_attack_006": 0,
        "lv2_attack_007": 0,

        # Lv.3 사람 대상 송금/계좌 변경 요청
        "lv3_transaction_001": 0,
        "lv3_transaction_002": 0,
        "lv3_transaction_004": 0,
        "lv3_transaction_005": 0,
        "lv3_transaction_006": 0,
        "lv3_transaction_007": 0,
    },
}

def patch_file(path: Path, patch_map: dict):
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = []

    # 원본 백업
    backup = ARCHIVE_DIR / path.name
    shutil.copy2(path, backup)

    for row in data:
        gid = row.get("group_id")
        if gid in patch_map:
            before = row.get("label")
            row["label"] = patch_map[gid]

            # label=0으로 바뀐 행은 공격 타입을 제거하고 hard negative로 명시
            if row["label"] == 0:
                row.pop("attack_type", None)
                row["source"] = "hard_negative"

            changed.append({
                "group_id": gid,
                "before": before,
                "after": row["label"],
                "text": row.get("text", "")
            })

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return changed

def validate_ai_target(data):
    """label=1 중 AI 대상 표현이 전혀 없는 문장을 2차 검수 후보로 출력."""
    ai_terms = [
        "AI", "ai", "시스템", "요약", "분류", "챗봇", "봇",
        "모델", "지침", "규칙", "필터", "정책", "역할", "출력"
    ]
    suspects = []
    for row in data:
        if row.get("label") == 1:
            text = row.get("text", "")
            if not any(term in text for term in ai_terms):
                suspects.append(row)
    return suspects

all_changed = []
all_suspects = []

for filename, patch_map in PATCHES.items():
    path = DATA_DIR / filename
    if not path.exists():
        print(f"[SKIP] 파일 없음: {path}")
        continue

    changed = patch_file(path, patch_map)
    all_changed.extend([(filename, x) for x in changed])

    data = json.loads(path.read_text(encoding="utf-8"))
    suspects = validate_ai_target(data)
    all_suspects.extend([(filename, x) for x in suspects])

print(f"\n수정 완료: {len(all_changed)}건")
for filename, x in all_changed:
    print(f"- {filename} | {x['group_id']} | {x['before']} -> {x['after']} | {x['text']}")

print(f"\n추가 수동 검수 후보(label=1인데 AI 대상 표현이 약함): {len(all_suspects)}건")
for filename, row in all_suspects:
    print(f"- {filename} | {row.get('group_id')} | {row.get('text')}")

print("\n원본 백업 폴더:", ARCHIVE_DIR)
