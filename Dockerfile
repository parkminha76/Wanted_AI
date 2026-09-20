FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false \
    PATH="/app/.venv/bin:$PATH"

# opencv-python이 headless Linux에서도 import될 수 있게 필요한 런타임 라이브러리만 설치한다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

WORKDIR /app

# 의존성 레이어를 먼저 만들어 소스만 바뀐 재배포에서 설치 캐시를 재사용한다.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# 스캐너 NER 모델은 실행 중 처음 내려받지 않는다. Railway의 첫 /scan 요청에서
# Hugging Face 다운로드까지 겹치면 프록시 응답 제한을 넘길 수 있으므로 이미지
# 빌드 단계에서 캐시에 고정하고, 런타임에는 그 캐시만 사용한다.
ENV HF_HOME=/opt/huggingface
RUN .venv/bin/python -c "from transformers import AutoModelForTokenClassification, AutoTokenizer; name='Leo97/KoELECTRA-small-v3-modu-ner'; AutoTokenizer.from_pretrained(name); AutoModelForTokenClassification.from_pretrained(name)"
ENV HF_HUB_OFFLINE=1

# 이미지 OCR(text_ocr.py, 2026-09-18에 Tesseract에서 EasyOCR로 교체)도 같은
# 이유로 같이 고정한다 — 검출기(CRAFT)·인식기 가중치를 첫 이미지 검사 요청
# 때 내려받게 두면 그 요청이 느려지거나 실패할 수 있다. EasyOCR 기본
# 저장 위치(~/.EasyOCR)에 미리 받아 두면 런타임에는 그 캐시를 그대로 쓴다.
RUN .venv/bin/python -c "import easyocr; easyocr.Reader(['ko', 'en'], gpu=False)"

COPY . .

# 모델 캐시와 다운로드 레지스트리는 프로세스 메모리에 있어서, worker를 늘리면
# worker 개수만큼 모델(NER·EasyOCR·YOLO·분류기)을 각자 따로 메모리에 올린다.
# Railway Hobby(CPU 1개, 메모리 빠듯함) 때는 이게 부담스러워 1개로 고정했었다.
# Pro로 올린 뒤(2026-09-20, CPU 24개·RAM 24GB)에는 상황이 다르다 — worker가
# 하나뿐이면 CPU가 몇 개든 uvicorn 프로세스 자체가 코어 하나만 쓰므로, 요금제만
# 올려서는 체감 속도가 그대로다(실측: 사용자가 직접 확인). WORKERS 환경변수로
# 조절 가능하게 하고 기본값을 4로 올린다 — 모델들을 합쳐도 워커 하나당
# 1~2GB 안팎이라 24GB에서 여유 있게 돈다.
ENV WORKERS=4
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS}"]
