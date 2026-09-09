# ml/data_generation/id_templates/idcard.py
from ml.data_generation.id_templates.driver_license_new import CLASSES  # 클래스 리스트 그대로 재사용

TEMPLATE_PATH = "data/raw/id_templates/idcard_sample.png"
CARD_SIZE = (1569, 1003)

PHOTO_BOX = {"x0": 1000, "y0": 100, "x1": 1495, "y1": 650}

FIELDS = {
    "name":            {"position": (217, 277), "font_size": 70,  "labeled": True, "bold": False},
    "resident_number": {"position": (161, 413), "font_size": 76,  "labeled": True, "bold": False},
    "address":         {"position": (144, 534), "font_size": 47,  "labeled": True, "bold": False,
                         "max_width": 1000 - 144 - 30},
    "issue_date":      {"position": (626, 782), "font_size": 54,  "labeled": True, "bold": False},

    "issuing_authority": {
        "position": (494, 851), "font_size": 78, "labeled": False, "bold": False,
        "align": "center",
    },
}