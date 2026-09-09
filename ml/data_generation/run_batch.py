# ml/data_generation/run_batch.py
import os
import glob
import random

from ml.data_generation.id_templates import driver_license_new
from ml.data_generation.generators import gen_driver_license_values
from ml.data_generation.compose import compose_card, save_sample

N = 700
VAL_RATIO = 0.1

# ← 추가: m1~m5, w1~w3 얼굴 이미지 목록 (확장자 모를 수 있어서 png/jpg 둘 다 찾음)
FACE_DIR = "data/raw/faces"
FACE_POOL = (
    glob.glob(f"{FACE_DIR}/*.png")
    + glob.glob(f"{FACE_DIR}/*.jpg")
    + glob.glob(f"{FACE_DIR}/*.jpeg")
)
print(f"얼굴 placeholder {len(FACE_POOL)}장 로드됨: {FACE_POOL}")

for split in ["train", "val"]:
    os.makedirs(f"data/processed/images/{split}", exist_ok=True)
    os.makedirs(f"data/processed/labels/{split}", exist_ok=True)

for i in range(N):
    values = gen_driver_license_values()

    # ← 추가: 매번 8장 중 랜덤으로 하나 골라서 씀
    photo_path = random.choice(FACE_POOL) if FACE_POOL else None
    img, labels = compose_card(driver_license_new, values, photo_path=photo_path)

    split = "val" if random.random() < VAL_RATIO else "train"
    out_img = f"data/processed/images/{split}/driver_{i:04d}.png"
    out_label = f"data/processed/labels/{split}/driver_{i:04d}.txt"

    save_sample(img, labels, out_img, out_label, driver_license_new.CLASSES)

    if (i + 1) % 50 == 0:
        print(f"{i + 1}/{N} 완료")

print("끝")