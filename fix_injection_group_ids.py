import json
from collections import defaultdict
from pathlib import Path

BASE = Path("sample_data/injection")

TARGETS = [
    BASE / "injection_C_0910_003.json",
    BASE / "injection_C_0910_004.json",
]

def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

def collect_group_ids(paths):
    occurrences = defaultdict(list)

    for path in paths:
        data = load_json(path)

        for idx, row in enumerate(data):
            gid = row.get("group_id")
            if gid:
                occurrences[gid].append({
                    "file": path.name,
                    "index": idx,
                    "text": row.get("text", ""),
                    "label": row.get("label"),
                })

    return occurrences

def main():
    for path in TARGETS:
        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    before = collect_group_ids(TARGETS)

    conflicts = {
        gid: rows
        for gid, rows in before.items()
        if len({row["file"] for row in rows}) > 1
    }

    print("=" * 70)
    print(f"[수정 전] 서로 다른 파일에 걸친 중복 group_id: {len(conflicts)}개")
    print("=" * 70)

    for gid, rows in sorted(conflicts.items()):
        print(f"\n- {gid}")
        for row in rows:
            preview = row["text"].replace("\n", " ")[:70]
            print(
                f'  {row["file"]} | index={row["index"]} | '
                f'label={row["label"]} | {preview}'
            )

    if not conflicts:
        print("\n수정할 충돌이 없습니다.")
        return

    # 기준:
    # _003은 유지하고, _004에서 충돌하는 group_id만 파일 고유 prefix로 변경한다.
    target_path = BASE / "injection_C_0910_004.json"
    data = load_json(target_path)

    changed = []

    for idx, row in enumerate(data):
        old_gid = row.get("group_id")

        if old_gid in conflicts:
            new_gid = f"c004_{old_gid}"

            row["group_id"] = new_gid

            changed.append({
                "index": idx,
                "old": old_gid,
                "new": new_gid,
                "text": row.get("text", ""),
            })

    save_json(target_path, data)

    after = collect_group_ids(TARGETS)
    remaining = {
        gid: rows
        for gid, rows in after.items()
        if len({row["file"] for row in rows}) > 1
    }

    print("\n" + "=" * 70)
    print(f"[수정 완료] 변경 샘플: {len(changed)}개")
    print("=" * 70)

    for item in changed:
        print(f'{item["old"]} -> {item["new"]}')

    print("\n" + "=" * 70)
    print(f"[검증] 파일 간 중복 group_id: {len(remaining)}개")
    print("=" * 70)

    if remaining:
        print("⚠ 아직 중복 group_id가 남아 있습니다.")
        for gid in sorted(remaining):
            print("-", gid)
        raise SystemExit(1)

    # text 중복 검사
    texts = defaultdict(list)
    for path in TARGETS:
        for idx, row in enumerate(load_json(path)):
            text = row.get("text", "").strip()
            if text:
                texts[text].append((path.name, idx))

    duplicate_texts = {
        text: rows
        for text, rows in texts.items()
        if len(rows) > 1
    }

    print(f"[검증] 완전 동일 text 중복: {len(duplicate_texts)}개")

    # label 분포 검사
    for path in TARGETS:
        data = load_json(path)
        counts = defaultdict(int)
        for row in data:
            counts[row.get("label")] += 1

        print(
            f'[분포] {path.name}: '
            f'label=0 {counts.get(0, 0)}건 / '
            f'label=1 {counts.get(1, 0)}건 / '
            f'전체 {len(data)}건'
        )

    print("\n✅ group_id 정리 및 기본 검증 완료")


if __name__ == "__main__":
    main()
