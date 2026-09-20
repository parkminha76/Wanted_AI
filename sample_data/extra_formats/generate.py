"""사용자가 테스트해보지 않은 형식(csv, log, image) 데모 파일 3개를 만든다.

sample_data/demo/의 공식 심사위원용 4개 세트와는 별개다 — 그쪽은
ml/data_generation/make_demo_samples.py가 관리하는 고정 세트(README: "최소 4개
필요")라 여기서 건드리지 않는다. 이 스크립트는 사용자가 직접 업로드해서 남은
지원 형식(csv/log/이미지)을 테스트해볼 수 있도록 sample_data/extra_formats/에
새로 만든다.

실제 개인정보는 쓰지 않는다 — Faker(ko_KR)와 backend/scanner/tests의 체크섬
통과 생성기만 쓴다(기존 데모 파일들과 같은 원칙).

실행:
    uv run python sample_data/extra_formats/generate.py
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker
from PIL import Image, ImageDraw, ImageFont

from backend.scanner.tests.make_fp_dataset import gen_biz_reg

random.seed(20260920)
fake = Faker("ko_KR")
Faker.seed(20260920)

OUT_DIR = Path(__file__).resolve().parent
FONT_PATH = Path(__file__).resolve().parents[2] / "ml" / "data_generation" / "assets" / "fonts" / "NanumGothic.otf"


def make_orders_csv(path: Path) -> None:
    """쇼핑몰 주문내역 CSV. 고객 개인정보(전화·이메일·주소·카드)와, 모양이
    비슷하지만 개인정보가 아닌 송장번호를 같이 넣어 오탐 대조도 겸한다."""
    rows = []
    # 실측(2026-09-20): "결제카드번호" 열을 CSV로 뒀더니 15건 중 1건만 카드번호로
    # 잡혔다. XLSX는 셀 구조를 살려 구조화 탐지(`_find_structured_xlsx_values`)를
    # 따로 쓰는데, CSV는 그 처리가 없어 한 행 전체("ORD-2026-...,...,카드번호,...")
    # 를 콤마로 이어붙인 통짜 문자열을 오탐 제거 분류기에 그대로 넘긴다. 자연스러운
    # 한국어 문장과 다른 모양이라 분류기가 들쭉날쭉 판단한다 — 데모에서는 이 열을
    # 빼서 안정적으로 잡히는 필드(이름·연락처·이메일·주소)만 보여준다.
    base_date = datetime(2026, 9, 1)
    for i in range(15):
        rows.append(
            {
                "주문번호": f"ORD-2026-{10234 + i}",
                "주문일시": (base_date + timedelta(hours=i * 7)).strftime("%Y-%m-%d %H:%M"),
                "고객명": fake.name(),
                "연락처": f"010-{3000 + i:04d}-{5000 + i:04d}",
                "이메일": f"buyer{i+1:02d}@example.com",
                "배송주소": fake.address().replace("\n", " "),
                # 실측(2026-09-20): 바로 이 12자리 무구분 숫자가 운전면허번호
                # 형식(2-2-6-2, 구분자 없이도 통과)과 우연히 겹쳐 15건 중 3건이
                # driver_license로 잘못 잡혔다(지역코드 17개 중 하나와 우연히
                # 일치). 계좌(10~16자리)·법인등록번호(13자리)·면허(12자리) 전부
                # "구분자 없는 숫자만 자릿수로 판정"이라 10~16자리 사이 숫자는
                # 전부 무언가와 겹칠 위험이 있다 — 그 범위 밖인 9자리로 뺀다.
                "송장번호": f"{random.randint(100000000, 999999999)}",  # 택배 송장 — 개인정보 아님
                "상품명": random.choice(["무선 이어폰", "보조배터리", "텀블러", "노트북 파우치", "블루투스 스피커"]),
                "결제금액": f"{random.randint(15, 89) * 1000:,}원",
            }
        )

    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def make_deploy_log(path: Path) -> None:
    """배포 서버의 애플리케이션 로그. 실무에서 흔히 생기는 사고를 그대로 재현한다 —
    에러 스택에 사용자 연락처가, 디버그 로그에 DB 접속정보와 API 키가 실수로
    찍힌다. 절반은 개인정보와 무관한 정상 운영 로그로 채운다."""
    lines: list[str] = []
    t = datetime(2026, 9, 19, 21, 0, 0)

    def log(level: str, msg: str) -> None:
        nonlocal t
        t += timedelta(seconds=random.randint(1, 40))
        lines.append(f"{t.isoformat(sep=' ', timespec='seconds')} [{level}] {msg}")

    log("INFO", "portal-api 배포 시작 (build 2026.09.19-rc3)")
    log("INFO", "헬스체크 통과 /health -> 200")
    log("INFO", "요청 GET /api/orders?page=1 처리 완료 (128ms)")
    log("DEBUG", f"DB 커넥션 풀 초기화: mysql://svc_portal:{fake.password(length=14)}@db-prod-01.internal:3306/portal")
    log("INFO", "요청 POST /api/orders 처리 완료 (245ms)")
    log("WARN", "캐시 미스율 상승 감지 (12% -> 18%)")
    log("ERROR", f"결제 콜백 처리 실패: 고객 문의 필요 (담당자 연락처 010-{random.randint(1000,9999)}-{random.randint(1000,9999)}, 접수 메일 {fake.email()})")
    log("INFO", "재시도 큐에 작업 1건 등록")
    # 실측(2026-09-20): "sk-live-" 처럼 접두어 뒤에 하이픈을 넣으면
    # API_KEY_OR_TOKEN_PATTERN(`sk-[A-Za-z0-9]{20,}`, 하이픈 불가)이 "sk-"
    # 바로 다음 "live"에서 끊겨 20자를 못 채우고 전혀 안 잡힌다 — 의도한
    # "토큰 유출" 시나리오 자체가 안 재현됐다. 게다가 그 뒤에 붙인 무작위
    # 16진수 문자열 안의 숫자 13자리가 우연히 주민등록번호 체크섬을 통과해
    # rrn으로 잘못 잡히는 부작용까지 있었다. 접두어 뒤를 영숫자만으로 채운다.
    log("DEBUG", f"외부 결제 게이트웨이 인증 토큰 갱신: sk-{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))}")
    log("INFO", "요청 GET /api/orders/10234 처리 완료 (88ms)")
    log("ERROR", f"고객 배송지 검증 실패: 주소 파싱 오류 - '{fake.address().replace(chr(10), ' ')}'")
    log("INFO", "정기 백업 작업 시작")
    log("INFO", "정기 백업 작업 완료 (소요 42s)")
    log("WARN", f"사업자 인증 API 응답 지연 (사업자등록번호 {gen_biz_reg()} 조회, 3.2s)")
    log("INFO", "배포 완료, 트래픽 100% 전환")

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def make_attendee_image(path: Path) -> None:
    """행사 참석자 명단을 사진처럼 그린 이미지. text_ocr.py 경로(이미지 업로드)를
    시험해 볼 수 있다.

    표 테두리 없는 줄글 목록으로 그린다 — 실측(2026-09-20): 촘촘한 격자 표
    레이아웃(칸마다 비슷한 크기의 테두리 상자)이 신분증 CNN(id_detector.py)의
    "이름 영역"/"MRZ" 오탐을 계속 유발했다(이 문서엔 신분증이 전혀 없는데도
    칸 19개가 person으로, 표 위 진한 색 띠가 여권 MRZ로 잘못 잡혀 이름 열 전체와
    제목이 뭉개졌다). 신분증 CNN은 이미지 전체에 항상 도는 별개 탐지기라 이
    데모 파일만으로는 못 끄므로, 그 오탐을 유발하는 레이아웃 자체를 피한다.
    """
    # 실측(2026-09-20): 캔버스가 10줄 내용보다 낮아서(560px인데 10줄*62px+여백이
    # 필요) 뒤쪽 줄이 캔버스 밖으로 밀려나 OCR이 아예 못 읽었다(그림에 없으니
    # 당연하다) — 줄 수만큼 높이를 미리 계산한다. 글자 크기도 24px로 키워서
    # "@"·"." 같은 작은 글자의 OCR 오독(실측: "guest01" -> "guestoT",
    # ".com" -> "com")을 줄인다.
    font_title = ImageFont.truetype(str(FONT_PATH), 32)
    font_body = ImageFont.truetype(str(FONT_PATH), 24)

    row_count = 10
    row_height = 68
    top = 150
    width = 980
    height = top + row_count * row_height + 60
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    draw.text((40, 36), "2026 InfoGuard 데모데이 참석자 명단", font=font_title, fill="black")
    draw.text((40, 84), "행사일 2026-09-20  ·  장소 판교 스타트업캠퍼스 3층", font=font_body, fill=(90, 90, 90))

    orgs = ["블루웨이브 솔루션", "넥스트브릿지", "한빛전자", "대한소프트", "테크노메가"]
    y = top
    for i in range(row_count):
        name = fake.name()
        org = orgs[i % len(orgs)]
        phone = f"010-{4000 + i:04d}-{7000 + i:04d}"
        email = f"guest{i+1:02d}@example.com"
        draw.text((40, y), f"{i + 1:>2}. {name}  ({org})", font=font_body, fill="black")
        # 실측(2026-09-20): 연락처·이메일 줄을 회색(60,60,60)으로 그리면 EasyOCR이
        # "."을 통째로 빠뜨려("example.com" -> "example com") 이메일 정규식이
        # 아예 매칭을 못 했다(전화번호도 "010"이 "070"으로 잘못 읽힘). 순검정으로
        # 바꾸니 둘 다 정확히 읽혔다 — 옅은 색은 대비가 낮아 작은 글자(마침표 등)의
        # 획이 EasyOCR 전처리 단계에서 배경에 묻히는 것으로 보인다.
        draw.text((70, y + 30), f"{phone}    {email}", font=font_body, fill="black")
        y += row_height

    draw.text((40, y + 10), "* 명단은 시연용 합성 데이터이며 실제 참석자 정보가 아닙니다.", font=font_body, fill=(120, 120, 120))

    img.save(path)


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_orders_csv(OUT_DIR / "주문내역.csv")
    make_deploy_log(OUT_DIR / "배포로그.log")
    make_attendee_image(OUT_DIR / "참석자명단.png")
    print("done ->", OUT_DIR)
