# ml/data_generation/compose.py
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "ml/data_generation/assets/fonts/NanumGothic.otf"
BOLD_FONT_PATH = "ml/data_generation/assets/fonts/NanumGothicBold.otf"


def _draw_line(draw, x, y, text, font, fill, letter_spacing=0):
    """
    한 줄 텍스트를 그리고 (min_x, min_y, max_x, max_y)를 반환.
    letter_spacing > 0이면 글자를 하나씩 찍으면서 x를 강제로 벌림
    (draw.text로 통째로 찍으면 폰트 기본 자간이라 레퍼런스처럼 안 벌어짐).
    """
    if letter_spacing <= 0:
        draw.text((x, y), text, font=font, fill=fill)
        return draw.textbbox((x, y), text, font=font)

    cur_x = x
    min_x, min_y, max_x, max_y = x, y, x, y
    for ch in text:
        draw.text((cur_x, y), ch, font=font, fill=fill)
        bx0, by0, bx1, by1 = draw.textbbox((cur_x, y), ch, font=font)
        min_x, min_y = min(min_x, bx0), min(min_y, by0)
        max_x, max_y = max(max_x, bx1), max(max_y, by1)
        adv = draw.textlength(ch, font=font)
        cur_x += adv + letter_spacing
    return (min_x, min_y, max_x, max_y)


def wrap_text(text, font, max_width, draw):
    """max_width(px)를 넘으면 자동 줄바꿈. 한 글자씩 폭을 누적해서 체크함."""
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        w = draw.textlength(test, font=font)
        if w > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return "\n".join(lines)


def compose_card(config, values: dict, photo_path: str | None = None):
    """
    config   : id_templates 모듈 (TEMPLATE_PATH, FIELDS, PHOTO_BOX, CLASSES 가진 모듈)
    values   : gen_driver_license_values() / gen_idcard_values() 같은 리턴값 딕셔너리
    photo_path: 합성할 얼굴 이미지 경로. None이면 회색 placeholder로 채움
    """
    img = Image.open(config.TEMPLATE_PATH).convert("RGB")
    draw = ImageDraw.Draw(img)
    labels = []
    field_bboxes = {}  # 필드별로 실제 그려진 bbox 저장 → 다른 필드가 참조(anchor_after)할 수 있게

    # 1) 사진 합성
    box = config.PHOTO_BOX
    box_w, box_h = box["x1"] - box["x0"], box["y1"] - box["y0"]

    if photo_path:
        photo = Image.open(photo_path).convert("RGB").resize((box_w, box_h))
        img.paste(photo, (box["x0"], box["y0"]))
    else:
        draw.rectangle([box["x0"], box["y0"], box["x1"], box["y1"]], fill=(200, 200, 200))

    labels.append(("face", (box["x0"], box["y0"], box["x1"], box["y1"])))
    field_bboxes["face"] = (box["x0"], box["y0"], box["x1"], box["y1"])

    # 2) 텍스트 필드 그리기
    for field_name, cfg in config.FIELDS.items():
        value = values[field_name]
        path = BOLD_FONT_PATH if cfg.get("bold", False) else FONT_PATH
        font = ImageFont.truetype(path, cfg["font_size"])

        x, y = cfg["position"]

        # anchor_after가 있으면, 그 필드가 실제로 그려진 오른쪽 끝(max_x) + gap으로 x를 재계산
        anchor = cfg.get("anchor_after")
        if anchor:
            assert anchor in field_bboxes, (
                f"'{field_name}'이 '{anchor}'를 anchor_after로 참조하는데, "
                f"'{anchor}'가 FIELDS에서 '{field_name}'보다 뒤에 있음. 순서를 앞으로 옮겨줘."
            )
            gap = cfg.get("gap", 6)
            x = field_bboxes[anchor][2] + gap

        # max_width가 있으면 자동 줄바꿈 (예: 긴 주소가 사진 박스를 침범하는 것 방지)
        if "max_width" in cfg:
            value = wrap_text(value, font, cfg["max_width"], draw)

        # align="center"면 실제 텍스트 폭을 재서 center_range 안에서 가운데로 x를 재계산
        if cfg.get("align") == "center":
            text_width = draw.textlength(value, font=font)
            cx0, cx1 = cfg.get("center_range", (0, config.CARD_SIZE[0]))
            x = cx0 + (cx1 - cx0 - text_width) / 2

        line_height = cfg["font_size"] + 4
        letter_spacing = cfg.get("letter_spacing", 0)
        lines = value.split("\n")
        min_x, min_y, max_x, max_y = x, y, x, y

        for i, line in enumerate(lines):
            if not line:
                continue
            line_y = y + i * line_height
            bx0, by0, bx1, by1 = _draw_line(draw, x, line_y, line, font, (20, 20, 20), letter_spacing)
            min_x, min_y = min(min_x, bx0), min(min_y, by0)
            max_x, max_y = max(max_x, bx1), max(max_y, by1)

        field_bboxes[field_name] = (min_x, min_y, max_x, max_y)

        if cfg.get("labeled", True):
            labels.append((field_name, (min_x, min_y, max_x, max_y)))

    return img, labels


def to_yolo_label(field_name: str, bbox: tuple, img_w: int, img_h: int, classes: list[str]) -> str:
    class_id = classes.index(field_name)
    x0, y0, x1, y1 = bbox

    x_center = (x0 + x1) / 2 / img_w
    y_center = (y0 + y1) / 2 / img_h
    width = (x1 - x0) / img_w
    height = (y1 - y0) / img_h

    return f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def save_sample(img, labels, out_image_path: str, out_label_path: str, classes: list[str]):
    img.save(out_image_path)
    img_w, img_h = img.size
    with open(out_label_path, "w") as f:
        for field_name, bbox in labels:
            f.write(to_yolo_label(field_name, bbox, img_w, img_h, classes) + "\n")