# ml/data_generation/run_batch_idcard.py
import os
import glob
import random

from ml.data_generation.id_templates import idcard
from ml.data_generation.idcard_generators import gen_idcard_values
from ml.data_generation.compose import compose_card, save_sample

N = 300
VAL_RATIO = 0.1

FACE_DIR = "data/raw/faces"
FACE_POOL = (
    glob.glob(f"{FACE_DIR}/*.png")
    + glob.glob(f"{FACE_DIR}/*.jpg")
    + glob.glob(f"{FACE_DIR}/*.jpeg")
)
print(f"얼굴 placeholder {len(FACE_POOL)}장 로드됨")

for split in ["train", "val"]:
    os.makedirs(f"data/processed/images/{split}", exist_ok=True)
    os.makedirs(f"data/processed/labels/{split}", exist_ok=True)

for i in range(N):
    values = gen_idcard_values()

    photo_path = random.choice(FACE_POOL) if FACE_POOL else None
    img, labels = compose_card(idcard, values, photo_path=photo_path)

    split = "val" if random.random() < VAL_RATIO else "train"
    # 파일명 앞에 idcard_ 붙여서 driver_ 파일들이랑 안 섞이게
    out_img = f"data/processed/images/{split}/idcard_{i:04d}.png"
    out_label = f"data/processed/labels/{split}/idcard_{i:04d}.txt"

    save_sample(img, labels, out_img, out_label, idcard.CLASSES)

    if (i + 1) % 50 == 0:
        print(f"{i + 1}/{N} 완료")

print("끝")