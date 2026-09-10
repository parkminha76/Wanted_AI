# ml/test_inference_augmented.py
import random, glob
import albumentations as A
import numpy as np
import os
import json
from PIL import Image, ImageDraw
from ultralytics import YOLO

from ml.data_generation.id_templates import driver_license_new, idcard, passport
from ml.data_generation.compose import compose_card
# 아래 3개 generator 함수 import는 실제 파일/함수명에 맞게 조정
from ml.data_generation.generators import gen_driver_license_values
from ml.data_generation.idcard_generators import gen_idcard_values
from ml.data_generation.passport_generators import gen_passport_values

MODEL_PATH = "runs/detect/infoguard_v1/weights/best.pt"
FACE_POOL = glob.glob("data/raw/faces/*.png") + glob.glob("data/raw/faces/*.jpg")

os.makedirs("data/test/test_img", exist_ok=True)
os.makedirs("data/test/test_json", exist_ok=True)

# 학습 때 안 쓴 변형 위주 — 실제 폰카 촬영을 흉내냄
transform = A.Compose([
    A.Rotate(limit=15, p=1.0, border_mode=0),
    A.Perspective(scale=(0.02, 0.06), p=0.7),
    A.RandomBrightnessContrast(brightness_limit=0.3, contrast_limit=0.3, p=0.8),
    A.GaussianBlur(blur_limit=(3, 7), p=0.5),
    A.ISONoise(p=0.4),
    A.ImageCompression(quality_range=(40, 80), p=0.6),
])

model = YOLO(MODEL_PATH)
colors = ["red","blue","green","orange","purple","brown","pink","gray","olive","cyan","magenta","yellow"]

configs = [
    (driver_license_new, gen_driver_license_values, "driver"),
    (idcard, gen_idcard_values, "idcard"),
    (passport, gen_passport_values, "passport"),
]

for i in range(5):
    for config, gen_fn, prefix in configs:
        values = gen_fn()
        photo_path = random.choice(FACE_POOL) if FACE_POOL else None
        img, _ = compose_card(config, values, photo_path=photo_path)

        aug = transform(image=np.array(img))["image"]
        aug_img = Image.fromarray(aug)
        aug_path = f"data/test/test_img/aug_{prefix}_{i}.png"
        aug_img.save(aug_path)

        results = model.predict(aug_path, conf=0.3, verbose=False)[0]
        class_names = results.names
        draw_img = aug_img.copy()
        draw = ImageDraw.Draw(draw_img)

        detected = []
        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            label = class_names[cls_id]
            x0, y0, x1, y1 = box.xyxy[0].tolist()
            color = colors[cls_id % len(colors)]
            draw.rectangle([x0, y0, x1, y1], outline=color, width=3)
            draw.text((x0, max(0, y0 - 15)), f"{label} {conf:.2f}", fill=color)
            detected.append({"label": label, "confidence": round(conf, 3),
                              "bbox": [round(v, 1) for v in (x0, y0, x1, y1)]})

        result_path = f"data/test/test_img/aug_{prefix}_{i}_result.png"
        draw_img.save(result_path)

        # 정답값 + 탐지결과를 JSON으로 저장
        info = {
            "ground_truth": {k: str(v) for k, v in values.items()},
            "detected": detected,
        }
        json_path = f"data/test/test_json/aug_{prefix}_{i}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        print(f"{prefix}_{i}: {len(detected)}개 탐지 -> {result_path} (+ {json_path})")

print("끝")