"""DOCX/XLSX는 둘 다 zip이다. 업로드 크기 상한(MAX_UPLOAD_BYTES)은 압축된 크기만
막아서, 압축률이 아주 높은 파일이면 20MB 업로드로 수 GB짜리 압축 해제 결과를
만들 수 있다("zip bomb"). python-docx/openpyxl에게 넘기기 전에 central
directory(목차)만 읽어 미리 걸러내는지 확인한다 — 실제로 압축을 풀지 않으므로
이 테스트도 큰 파일을 실제로 만들지 않고 빠르게 끝난다.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile

from backend.scanner.parser import parse


def _write_zip(path: str, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


class ZipBombGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="test_zip_bomb_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp_dir, ignore_errors=True))

    def test_oversized_declared_uncompressed_size_is_rejected_without_extracting(self) -> None:
        """압축은 아주 잘 되지만(같은 바이트 반복) 실제로 풀면 상한을 넘는 진짜 zip
        bomb 형태 — 디스크에 올라가는 압축 파일 자체는 몇 KB뿐이다."""
        path = os.path.join(self.tmp_dir, "bomb.docx")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", b"0" * (parse._ZIP_BOMB_MAX_UNCOMPRESSED_BYTES + 1024))

        with self.assertRaises(parse.ParseError):
            parse._reject_zip_bomb(path, "DOCX")

    def test_too_many_entries_is_rejected(self) -> None:
        path = os.path.join(self.tmp_dir, "many_entries.xlsx")
        entries = {f"part_{i}.xml": b"x" for i in range(parse._ZIP_BOMB_MAX_ENTRY_COUNT + 1)}
        _write_zip(path, entries)

        with self.assertRaises(parse.ParseError):
            parse._reject_zip_bomb(path, "XLSX")

    def test_normal_sized_zip_passes(self) -> None:
        path = os.path.join(self.tmp_dir, "normal.docx")
        _write_zip(path, {"word/document.xml": b"hello world" * 1000})

        parse._reject_zip_bomb(path, "DOCX")  # 예외가 안 나면 통과

    def test_load_docx_rejects_before_handing_to_python_docx(self) -> None:
        """실제 load() 경로에서도 걸러지는지 — python-docx가 못 여는 가짜 구조라도
        zip bomb 검사가 먼저 걸려야 한다(더 구체적인 이유로 막혀야 함)."""
        path = os.path.join(self.tmp_dir, "bomb2.docx")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", b"0" * (parse._ZIP_BOMB_MAX_UNCOMPRESSED_BYTES + 1024))

        with self.assertRaises(parse.ParseError) as ctx:
            parse.load(path)
        self.assertIn("압축 해제", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
