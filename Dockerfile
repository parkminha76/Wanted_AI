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

COPY . .

# 모델 캐시와 다운로드 레지스트리는 프로세스 메모리에 있으므로 worker는 하나만 쓴다.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
