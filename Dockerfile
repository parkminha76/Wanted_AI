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
# 버전을 고정한다: 실측(2026-09-17)으로 확인 — 같은 코드인데도 로컬(Windows,
# tesseract v5.5.3)과 배포(버전 고정 없이 apt로 설치, 그 시점 최신 bookworm
# 패키지)가 같은 이미지를 다르게 읽었다. text_ocr.py의 표 줄 인식 보정 자체가
# Tesseract 레이아웃 분석의 버전별 차이에서 비롯된 문제라, 버전이 고정 안 돼
# 있으면 다음 배포에서 apt 미러가 올려주는 새 버전으로 또 조용히 바뀔 수 있다.
#
# TODO(버전 고정 미완성): 정확한 패키지 버전 문자열을 이 환경(샌드박스, Docker
# 없음)에서 확인할 방법이 없어 임시로 `apt-cache madison tesseract-ocr`
# 결과를 이 자리에 채워 넣어야 한다. 잘못된 버전 문자열을 넣으면 그 자리에서
# 빌드가 실패하므로(조용히 넘어가지 않음), 검증 없이 추측값을 넣지 않았다.
# 당장은 설치된 버전을 빌드 로그에 남겨서 최소한 "무엇이 배포됐는지"는
# 보이게 해 뒀다 — 다음에 이 줄을 `tesseract-ocr=<버전>`으로 바꿔 채운다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tesseract-ocr tesseract-ocr-kor \
    && tesseract --version \
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
