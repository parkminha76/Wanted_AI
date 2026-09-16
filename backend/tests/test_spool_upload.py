from __future__ import annotations

import io
import shutil
import tempfile
import unittest

from fastapi import UploadFile

from backend.main import _spool_upload


class SpoolUploadCollisionTest(unittest.IsolatedAsyncioTestCase):
    """같은 이름의 파일 두 개를 한 배치로 올려도 서로 덮어쓰지 않는지 확인한다.

    실측(2026-09-16): 고치기 전에는 두 번째 파일이 첫 번째 파일의 스풀 경로를
    그대로 덮어써서, 첫 파일은 검사되지도 않은 채 사라지고 결과에는 두 번째
    파일 내용이 두 번 나왔다.
    """

    def setUp(self) -> None:
        self.dest_dir = tempfile.mkdtemp(prefix="test_spool_")
        self.addCleanup(shutil.rmtree, self.dest_dir, True)

    async def test_same_filename_uploads_do_not_overwrite_each_other(self) -> None:
        first = UploadFile(io.BytesIO(b"AAAA first"), filename="invoice.txt")
        second = UploadFile(io.BytesIO(b"BBBB second"), filename="invoice.txt")

        path_a = await _spool_upload(first, self.dest_dir)
        path_b = await _spool_upload(second, self.dest_dir)

        self.assertNotEqual(path_a, path_b)
        with open(path_a, "rb") as f:
            self.assertEqual(f.read(), b"AAAA first")
        with open(path_b, "rb") as f:
            self.assertEqual(f.read(), b"BBBB second")


if __name__ == "__main__":
    unittest.main()
