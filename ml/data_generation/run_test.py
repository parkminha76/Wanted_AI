import glob
import random

from ml.data_generation.id_templates import passport
from ml.data_generation.passport_generators import gen_passport_values
from ml.data_generation.compose import compose_card, save_sample

FACE_DIR = "data/raw/faces"
FACE_POOL = (
    glob.glob(f"{FACE_DIR}/*.png")
    + glob.glob(f"{FACE_DIR}/*.jpg")
    + glob.glob(f"{FACE_DIR}/*.jpeg")
)
photo_path = random.choice(FACE_POOL) if FACE_POOL else None
print(f"얼굴 placeholder {len(FACE_POOL)}장 로드됨, 사용: {photo_path}")

values = gen_passport_values()
for k, v in values.items():
    print(k, repr(v))

img, labels = compose_card(passport, values, photo_path=photo_path)
save_sample(img, labels, "passport_test.png", "passport_test.txt", passport.CLASSES)
print("passport_test.png / passport_test.txt 저장됨")