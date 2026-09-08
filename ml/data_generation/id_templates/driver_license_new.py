# ml/data_generation/id_templates/driver_license.py
TEMPLATE_PATH = "data/raw/id_templates/new_driver_sample.png"
CARD_SIZE = (445, 279)

CLASSES = [
    "face",
    "name",
    "resident_number",
    "license_number",
    "address",
    "issue_date",
    "expiry_date",
    "signature",
]

PHOTO_BOX = {"x0": 15, "y0": 73, "x1": 160, "y1": 254}  # 실측값 유지

FIELDS = {
    # PII
    "license_number":  {"position": (171, 47), "font_size": 17, "labeled": True, "bold": True,
                         "letter_spacing": 2},        # ← 추가: 숫자 사이 자간
    "name":            {"position": (171, 81),  "font_size": 12, "labeled": True},
    "resident_number": {"position": (171, 99),  "font_size": 13, "labeled": True},
    "address":         {"position": (171, 120), "font_size": 10, "labeled": True},   # 2줄
    "issue_date":      {"position": (171, 256), "font_size": 13, "labeled": True},
    "expiry_date":     {"position": (231, 194), "font_size": 10, "labeled": True},

    # 장식용
    "vehicle_class":      {"position": (6, 12),   "font_size": 9,  "labeled": False},
    "aptitude_label":     {"position": (171, 178), "font_size": 10, "labeled": False},
    "aptitude_test_date": {"position": (242, 178), "font_size": 10, "labeled": False},
    "period_label":       {"position": (171, 194), "font_size": 10, "labeled": False},
    "condition_label":    {"position": (171, 210), "font_size": 10, "labeled": False},  # ← 추가: "조건 :" 줄
    "secondary_code":     {"position": (377, 195), "font_size": 12, "labeled": False},

    # ← 수정: position의 x(265)는 이제 안 씀. issue_date 뒤에 자동으로 붙음
    "issuing_authority":  {"position": (0, 256), "font_size": 13, "labeled": False,
                            "anchor_after": "issue_date", "gap": 8},
}