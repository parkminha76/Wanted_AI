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
# 대신 OCR 잡음을 프롬프트 인젝션으로 오탐했다. 처음엔 학습 데이터(kor.traineddata)
# 차이인 줄 알고 tessdata_fast로 로컬과 완전히 똑같이 맞췄는데(`/health`의
# `kor_traineddata` 파일 크기로 실제 적용까지 확인) 그래도 여전히 똑같이
# 깨졌다 — 남은 변수를 다 없앤 뒤에도 재현되니, 진짜 원인은 Tesseract
# **엔진 버전 자체**(5.5.0 vs 5.5.3)였다. opencv/numpy/pillow는 uv.lock이
# 로컬·배포에 동일한 버전을 고정하므로 원인에서 제외된다.
#
# Debian 저장소엔 5.5.3이 없어(설치 가능한 건 5.5.0뿐) apt로는 맞출 수 없다.
# 그래서 엔진을 소스에서 그 버전 그대로 빌드한다. 학습 데이터는 여전히
# tessdata_fast로 직접 받는다 — 소스 빌드는 traineddata를 같이 설치해주지
# 않고, 이미 위 실측으로 이 이미지에는 tessdata_fast가 로컬 Windows 설치본과
# 정확히 같은 결과를 낸다는 게 확인됐다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl git build-essential cmake pkg-config libleptonica-dev \
    && git clone --depth 1 --branch 5.5.3 https://github.com/tesseract-ocr/tesseract.git /tmp/tesseract-src \
    && cmake -S /tmp/tesseract-src -B /tmp/tesseract-src/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_TRAINING_TOOLS=OFF \
        -DBUILD_TESTS=OFF \
        -DDISABLE_ARCHIVE=ON \
        -DDISABLE_CURL=ON \
    && cmake --build /tmp/tesseract-src/build -j"$(nproc)" \
    && cmake --install /tmp/tesseract-src/build \
    && ldconfig \
    && rm -rf /tmp/tesseract-src \
    && tesseract --version \
    && mkdir -p /usr/local/share/tessdata \
    && TESSDATA_COMMIT=87416418657359cb625c412a48b6e1d6d41c29bd \
    && curl -fsSL -o /usr/local/share/tessdata/eng.traineddata \
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$TESSDATA_COMMIT/eng.traineddata" \
    && curl -fsSL -o /usr/local/share/tessdata/kor.traineddata \
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$TESSDATA_COMMIT/kor.traineddata" \
    && rm -rf /var/lib/apt/lists/*

# 빌드 도구(git/build-essential/cmake 등)를 지금 지우지 않는다. libleptonica-dev를
# purge하면 apt가 같이 딸려온 leptonica 런타임 공유 라이브러리까지 "더 이상
# 필요 없다"고 판단해 같이 지울 위험이 있고, 그러면 방금 빌드한 tesseract
# 바이너리가 런타임에 그 라이브러리를 못 찾아 실행 자체가 깨진다. 이미지
# 용량은 늘어나지만(빌드 도구가 최종 이미지에 남음), 배포가 완전히 깨지는
# 것보다 훨씬 낫다 — 용량 최적화는 이 빌드가 실제로 안정적으로 돌아가는 걸
# 확인한 뒤에, 멀티스테이지 빌드로 다시 손볼 일이다.
ENV TESSDATA_PREFIX=/usr/local/share/tessdata

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
