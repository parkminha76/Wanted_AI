"""InfoGuard API — 바깥에서 부르는 창구.

    POST /scan            파일 여러 개 업로드 -> ScanBatch JSON   (D가 호출)
    POST /scan/text       문장 하나 -> ScanResult JSON            (C의 실시간 답장 스캔)
    GET  /download/{id}   마스킹 사본 파일 하나
    GET  /download/all    배치 전체 .zip
    GET  /samples         심사위원용 샘플을 미리 검사한 결과
    GET  /health          살아있는지 확인

지켜야 하는 것
--------------
1. **업로드 원본은 처리 후 즉시 지운다.** 개인정보 보호 서비스가 개인정보를 모으면
   그 자체로 실격 사유다(backend/scanner/README.md). 임시 파일로 받아 스캔하고
   finally에서 삭제한다.

2. **마스킹 사본은 TTL이 지나면 지운다.** scan_results의 masked_path는 서버 임시
   경로이고 다운로드 후 남아 있을 이유가 없다. 응답 직후에 지우면 다운로드를 할 수
   없으므로(스캔과 다운로드는 별개 요청이다) 발급 시각을 기록해 두고 만료된 것부터
   지운다.

3. **경로를 사용자 입력으로 만들지 않는다.** /download/{id}의 id는 우리가 발급한
   UUID이고, 실제 경로는 레지스트리에서만 꺼낸다. 클라이언트가 보낸 문자열을 경로로
   이어 붙이면 ../../로 서버 파일을 읽어갈 수 있다.

4. **로그에 원문을 남기지 않는다.** 탐지된 값도, 파일 내용도 찍지 않는다(팀 규칙).

DB는 없어도 돈다. .env가 없는 환경에서도 스캔은 되어야 하므로 저장은 선택이다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from backend.scanner import scan
from backend.shared import schema

MASKED_DIR_PREFIX = "infoguard_mask_"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버가 뜰 때 이전 프로세스가 남긴 사본을 한 번 훑어 지운다.

    사본 경로는 메모리(_masked_files)에만 있어서 재시작하면 레지스트리는 비는데
    **파일은 디스크에 그대로 남는다.** 그 뒤로는 아무도 존재를 모르니 _sweep_expired의
    TTL 청소에도 걸리지 않고 영영 쌓인다(실측으로 확인했다 — 개발 중에만 527개가
    쌓여 있었다).

    남는 것이 마스킹된 사본이라 원본만큼 위험하진 않지만, 개인정보가 일부라도
    담긴 파일이 서버에 무기한 남아서는 안 된다.
    """
    _sweep_orphan_dirs()
    yield


app = FastAPI(title="InfoGuard API", version=schema.SCHEMA_VERSION, lifespan=lifespan)

# 프론트(D)가 다른 포트에서 부른다. 배포 도메인이 정해지면 그 도메인만 남긴다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 업로드 1건 상한. 이걸 안 걸면 큰 파일 하나로 디스크를 채울 수 있다.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_FILES_PER_REQUEST = 20
# 훈련 모드 답장 스캔의 입력 상한. NER이 긴 글을 청킹하므로 길이 자체는 문제가
# 아니지만, 채팅 한 줄에 소설이 들어올 이유는 없다.
MAX_TEXT_LENGTH = 100_000
# 마스킹 사본 보관 시간. 사용자가 결과를 보고 내려받기까지의 여유다.
MASKED_FILE_TTL_SECONDS = 30 * 60


# ---------------------------------------------------------------------------
# 마스킹 사본 레지스트리
# ---------------------------------------------------------------------------
#
# 스캔과 다운로드는 별개 요청이라 사본 경로를 기억해야 한다. 프로세스 메모리에
# 두므로 서버를 재시작하면 레지스트리가 비는데, **파일은 디스크에 그대로 남는다.**
# 그래서 재시작 직후 한 번 훑어 지운다(_sweep_orphan_dirs). 그 청소가 없으면
# 고아 파일이 TTL 청소에도 안 걸려 영영 쌓인다.


@dataclass
class _MaskedFile:
    path: str
    download_name: str
    created_at: float


_masked_files: dict[str, _MaskedFile] = {}
_batches: dict[str, list[str]] = {}


def _sweep_expired() -> None:
    """TTL이 지난 사본을 지운다. 별도 스케줄러 없이 요청이 올 때마다 훑는다."""
    deadline = time.time() - MASKED_FILE_TTL_SECONDS
    for file_id, entry in list(_masked_files.items()):
        if entry.created_at < deadline:
            _remove_quietly(entry.path)
            _masked_files.pop(file_id, None)
    for batch_id, file_ids in list(_batches.items()):
        if not any(fid in _masked_files for fid in file_ids):
            _batches.pop(batch_id, None)


def _sweep_orphan_dirs() -> int:
    """이전 프로세스가 남긴 사본 폴더를 지운다. 지운 개수를 돌려준다.

    TTL이 지난 것만 건드린다. 같은 머신에서 다른 인스턴스가 돌고 있을 수 있는데,
    그쪽이 방금 만든 사본을 지우면 사용자가 다운로드 버튼을 눌렀을 때 404가 난다.
    """
    removed = 0
    deadline = time.time() - MASKED_FILE_TTL_SECONDS
    root = tempfile.gettempdir()
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(MASKED_DIR_PREFIX):
            continue
        target = os.path.join(root, name)
        try:
            if os.path.getmtime(target) >= deadline:
                continue
            shutil.rmtree(target, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed


def _remove_quietly(path: str) -> None:
    """지우다 실패해도 요청을 깨뜨리지 않는다. 임시 파일 정리는 부가 작업이다."""
    try:
        os.remove(path)
    except OSError:
        pass
    parent = os.path.dirname(path)
    if parent.startswith(tempfile.gettempdir()):
        try:
            os.rmdir(parent)
        except OSError:
            pass


def _register_masked(result: schema.ScanResult) -> None:
    """ScanResult.masked_path를 다운로드 가능한 file_id로 바꿔 등록한다."""
    if not result.masked_path or not os.path.exists(result.masked_path):
        return
    file_id = uuid.uuid4().hex
    _masked_files[file_id] = _MaskedFile(
        path=result.masked_path,
        download_name=os.path.basename(result.masked_path),
        created_at=time.time(),
    )
    result.file_id = file_id


# ---------------------------------------------------------------------------
# 업로드 처리
# ---------------------------------------------------------------------------


def _safe_basename(name: str | None) -> str:
    """업로드된 파일명에서 경로 성분을 떼어낸다.

    클라이언트는 "../../etc/passwd"나 "C:\\Windows\\x"도 보낼 수 있다. 파일명을
    그대로 경로에 이어 붙이면 엉뚱한 곳에 쓰게 된다.
    """
    base = os.path.basename((name or "upload").replace("\\", "/"))
    return base or "upload"


async def _spool_upload(upload: UploadFile, dest_dir: str) -> str:
    """업로드를 임시 파일로 받는다. 상한을 넘으면 받다 말고 끊는다."""
    path = os.path.join(dest_dir, _safe_basename(upload.filename))
    written = 0
    with open(path, "wb") as out:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                out.close()
                _remove_quietly(path)
                raise HTTPException(
                    status_code=413,
                    detail=f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB)",
                )
            out.write(chunk)
    return path


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


class ScanTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)


@app.get("/health")
def health() -> dict:
    """배포 후 살아있는지 확인. 링크가 10/5까지 살아 있어야 해서 모니터링이 이걸 찍는다."""
    return {"status": "ok", "schema_version": schema.SCHEMA_VERSION}


@app.post("/scan")
async def scan_upload(files: list[UploadFile]) -> dict:
    """파일 여러 개를 검사해 위험도 순으로 돌려준다.

    업로드 원본은 이 함수를 벗어나기 전에 지운다. 마스킹 사본만 file_id로 남는다.
    """
    if not files:
        raise HTTPException(status_code=400, detail="파일이 없습니다")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=413, detail=f"한 번에 {MAX_FILES_PER_REQUEST}개까지 올릴 수 있습니다"
        )

    _sweep_expired()
    upload_dir = tempfile.mkdtemp(prefix="infoguard_upload_")
    try:
        paths = [await _spool_upload(f, upload_dir) for f in files]
        batch = scan.scan_files(paths)
    finally:
        # 제품 원칙: 업로드 원본은 저장하지 않는다. 스캔이 실패해도 지운다.
        shutil.rmtree(upload_dir, ignore_errors=True)

    # scan_file은 자기가 받은 경로를 filename에 넣는데, 여기서 넘긴 것은 업로드
    # 임시 경로다(…/Temp/infoguard_upload_xxxx/연락처.pdf). 그대로 내보내면
    # **서버 디렉터리 구조가 응답에 실려 나가고**, 화면에는 파일명 대신 그 경로가
    # 뜬다. 사용자가 올린 이름으로 돌려놓는다 — 경로 성분은 _safe_basename이
    # 이미 떼어냈다(클라이언트가 "../../etc/passwd"를 보낼 수 있다).
    #
    # 순서로 맞추지 않고 경로를 키로 쓴다. 결과 목록의 순서가 입력 순서와
    # 달라져도(정렬·건너뜀) 엉뚱한 파일에 이름이 붙지 않는다.
    display_name = {path: _safe_basename(f.filename) for path, f in zip(paths, files)}
    for result in batch.results:
        result.filename = display_name.get(result.filename, os.path.basename(result.filename))

    batch.batch_id = uuid.uuid4().hex
    for result in batch.results:
        _register_masked(result)
    _batches[batch.batch_id] = [r.file_id for r in batch.results if r.file_id]

    return batch.to_dict()


@app.post("/scan/text")
def scan_one_text(request: ScanTextRequest) -> dict:
    """문장 하나를 검사한다. 훈련 모드(C)가 답장을 보내기 전에 부른다.

    파일이 아니므로 사본도 file_id도 없다. masked_text는 응답에 그대로 들어간다.
    """
    return scan.scan_text(request.text).to_dict()


@app.get("/download/all")
def download_all(batch_id: str) -> FileResponse:
    """배치의 사본 전체를 .zip으로 내려준다.

    zip은 요청할 때 만들고 응답을 보낸 뒤 지운다(BackgroundTask). 미리 만들어 두면
    내려받지 않은 zip이 디스크에 남는다.
    """
    _sweep_expired()
    file_ids = _batches.get(batch_id)
    if not file_ids:
        raise HTTPException(status_code=404, detail="배치가 없거나 보관 기간이 지났습니다")

    entries = [_masked_files[fid] for fid in file_ids if fid in _masked_files]
    if not entries:
        raise HTTPException(status_code=404, detail="내려받을 사본이 없습니다")

    zip_dir = tempfile.mkdtemp(prefix="infoguard_zip_")
    zip_path = os.path.join(zip_dir, "infoguard_masked.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        used: set[str] = set()
        for entry in entries:
            if not os.path.exists(entry.path):
                continue
            # 같은 이름이 둘 이상이면 zip 안에서 덮어써진다. 뒤에 번호를 붙인다.
            name = entry.download_name
            stem, ext = os.path.splitext(name)
            counter = 1
            while name in used:
                name = f"{stem}_{counter}{ext}"
                counter += 1
            used.add(name)
            archive.write(entry.path, arcname=name)

    return FileResponse(
        zip_path,
        filename="infoguard_masked.zip",
        media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, zip_dir, ignore_errors=True),
    )


# /download/all 아래에 둔다. FastAPI는 선언 순서대로 경로를 맞추므로, 이걸 위에
# 두면 /download/all 요청이 file_id="all"로 잡혀서 항상 404가 난다(실제로 겪었다).
@app.get("/download/{file_id}")
def download_one(file_id: str) -> FileResponse:
    """마스킹 사본 하나를 내려준다. file_id는 /scan 응답의 그 값이다."""
    _sweep_expired()
    entry = _masked_files.get(file_id)
    if entry is None or not os.path.exists(entry.path):
        raise HTTPException(status_code=404, detail="사본이 없거나 보관 기간이 지났습니다")
    return FileResponse(
        entry.path, filename=entry.download_name, media_type="application/octet-stream"
    )


# ---------------------------------------------------------------------------
# 심사위원용 샘플
# ---------------------------------------------------------------------------
#
# 첫 화면에서 심사위원이 누르는 버튼이다("샘플로 체험하기"). 예선 배점의 투표 20%가
# 여기서 갈리므로 **절대 느리면 안 된다.** 파일을 매번 다시 스캔하면 NER 모델 로딩과
# CNN 추론까지 걸려서 첫 클릭이 수십 초가 된다. 그래서 한 번 계산해 캐시에 둔다.

SAMPLE_DIR = os.path.join("sample_data", "demo")
_sample_cache: dict | None = None


def _sample_paths() -> list[str]:
    """데모 파일 목록. parse가 읽을 수 있는 확장자만 고른다 —
    sample_data 아래에는 분류기 학습용 JSON도 있어서 그대로 넘기면 ParseError가 난다."""
    if not os.path.isdir(SAMPLE_DIR):
        return []
    readable = set(scan._FILE_TYPE_BY_EXTENSION)
    return sorted(
        os.path.join(SAMPLE_DIR, name)
        for name in os.listdir(SAMPLE_DIR)
        if os.path.splitext(name)[1].lower() in readable
    )


@app.get("/samples")
def samples() -> dict:
    """샘플을 미리 검사한 결과. 두 번째 호출부터는 캐시에서 즉시 나간다."""
    global _sample_cache
    if _sample_cache is not None:
        return _sample_cache

    paths = _sample_paths()
    if not paths:
        # 데모 파일은 A(sample_data/ 담당)가 넣는다. 아직 없으면 빈 목록을
        # 돌려주되, 화면이 "샘플 없음"과 "서버 오류"를 구분할 수 있게 알려준다.
        return {
            "schema_version": schema.SCHEMA_VERSION,
            "results": [],
            "total_files": 0,
            "total_findings": 0,
            "note": f"데모 샘플이 아직 없습니다 ({SAMPLE_DIR})",
        }

    batch = scan.scan_files(paths)
    # /scan과 같은 이유로 경로가 아니라 파일명만 내보낸다.
    for result in batch.results:
        result.filename = os.path.basename(result.filename)
    batch.batch_id = uuid.uuid4().hex
    for result in batch.results:
        _register_masked(result)
    _batches[batch.batch_id] = [r.file_id for r in batch.results if r.file_id]

    _sample_cache = batch.to_dict()
    return _sample_cache
