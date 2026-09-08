# ml/data_generation/run_test_idcard.py
from ml.data_generation.id_templates import idcard
from ml.data_generation.idcard_generators import gen_idcard_values
from ml.data_generation.compose import compose_card, save_sample

values = gen_idcard_values()
img, labels = compose_card(idcard, values, photo_path=None)

save_sample(
    img, labels,
    out_image_path="data/processed/images/train/idcard_test.png",
    out_label_path="data/processed/labels/train/idcard_test.txt",
    classes=idcard.CLASSES,
)
print(values)