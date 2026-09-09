from ml.data_generation.id_templates.driver_license_new import CLASSES as _BASE_CLASSES

CLASSES = _BASE_CLASSES + ["passport_number", "date_of_birth", "sex", "mrz"]

TEMPLATE_PATH = "data/raw/id_templates/passport_sample.png"
CARD_SIZE = (1024, 600)

PHOTO_BOX = {"x0": 47, "y0": 125, "x1": 299, "y1": 440}

FIELDS = {
    "type": {"position": (341, 112), "font_size": 26, "labeled": False},
    "nationality": {"position": (342, 379), "font_size": 24, "labeled": False},

    "passport_number": {"position": (612, 112), "font_size": 26, "labeled": True},
    "surname":         {"position": (342, 163), "font_size": 28, "labeled": True, "class_name": "name"},
    "given_names":     {"position": (342, 214), "font_size": 28, "labeled": True, "class_name": "name"},
    "korean_name":     {"position": (342, 264), "font_size": 26, "labeled": True, "class_name": "name"},
    "date_of_birth":   {"position": (342, 315), "font_size": 24, "labeled": True},
    "sex":             {"position": (612, 315), "font_size": 26, "labeled": True},
    "issue_date":      {"position": (342, 429), "font_size": 24, "labeled": True},
    "expiry_date":     {"position": (612, 429), "font_size": 24, "labeled": True},

    "mrz": {
        "position": (45, 510), "font_size": 22, "labeled": True,
        "font": "mono", "line_height": 55,
    },
}