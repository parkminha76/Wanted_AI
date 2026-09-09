# ml/data_generation/make_data_yaml.py
import yaml
from ml.data_generation.id_templates import passport

data = {
    "path": ".",
    "train": "data/processed/images/train",
    "val": "data/processed/images/val",
    "nc": len(passport.CLASSES),
    "names": passport.CLASSES,
}

with open("data.yaml", "w", encoding="utf-8") as f:
    yaml.dump(data, f, allow_unicode=True, sort_keys=False)

print(f"data.yaml 생성 완료 - 클래스 {len(passport.CLASSES)}개")
for i, name in enumerate(passport.CLASSES):
    print(i, name)