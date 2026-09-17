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
# tesseract-ocr(+kor)는 이미지 검사(text_ocr.py)가 인보이스·스크린샷 같은 일반
# 문서 사진에서 글자를 읽는 데 쓴다. 이게 없으면 컨테이너 안에서는 이미지 속
# 전화번호·계좌번호 등을 하나도 못 찾으면서도 예외 없이 findings=[]로 조용히
# 넘어간다(text_ocr.detect가 실패를 삼키는 방어 코드 때문이다) — 로컬에서는
# 됐는데 배포하면 안 되는 문제라 여기서 반드시 같이 설치해야 한다.
#
# 실측(2026-09-17)으로 확인: 같은 코드인데도 로컬(Windows, tesseract v5.5.3)과
# 배포(apt로 설치한 v5.5.0)가 같은 이미지를 다르게 읽어 "성명" 값을 못 찾고
# 대신 OCR 잡음을 프롬프트 인젝션으로 오탐했다. 엔진 버전 차이(5.5.0 vs
# 5.5.3)는 패치 버전 하나 차이라 이 정도 차이의 원인으로 보기엔 작다 — uv.lock이
# opencv/numpy/pillow도 로컬과 배포에서 동일한 버전으로 고정하므로 그쪽도 아니다.
# 남는 유력한 원인은 한글 인식에 실제로 쓰이는 학습 데이터(kor.traineddata)다.
# 엔진 버전이 같아도 배포판(apt)과 설치 프로그램(Windows)이 번들하는 학습
# 데이터 자체가 다를 수 있고, 이게 인식 정확도를 좌우한다.
#
# 그래서 엔진 버전을 좇는 대신 학습 데이터를 직접 고정한다: 정확도 우선
# 모델(tessdata_best, 느리지만 이 프로덕트는 정확도가 우선이다 — PII를
# 놓치는 게 느린 것보다 훨씬 나쁘다)을 특정 커밋에 고정해서 받아, apt가 깔아준
# 파일을 덮어쓴다. 브랜치(main)가 아니라 커밋 해시로 고정하는 이유는 브랜치
# 최신본을 받으면 다음 빌드에서 또 조용히 달라질 수 있어서다. 실제로 이
# 커밋에서 두 파일이 정상적으로 받아지는지(200, 정상 크기) 확인했다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl tesseract-ocr tesseract-ocr-kor \
    && tesseract --version \
    && TESSDATA_DIR="$(dirname "$(find /usr/share -name eng.traineddata | head -n1)")" \
    && test -n "$TESSDATA_DIR" \
    && TESSDATA_COMMIT=e12c65a915945e4c28e237a9b52bc4a8f39a0cec \
    && curl -fsSL -o "$TESSDATA_DIR/eng.traineddata" \
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/$TESSDATA_COMMIT/eng.traineddata" \
    && curl -fsSL -o "$TESSDATA_DIR/kor.traineddata" \
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/$TESSDATA_COMMIT/kor.traineddata" \
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

COPY . .

# 모델 캐시와 다운로드 레지스트리는 프로세스 메모리에 있으므로 worker는 하나만 쓴다.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
