"""사본 레지스트리가 워커 사이에서 공유되는지 본다.

uvicorn이 --workers 4로 뜨므로 사본을 만든 워커와 다운로드 요청을 받은 워커가
다를 수 있다. 프로세스 메모리 dict이던 시절에는 그때마다 404가 났다.
별도 프로세스를 띄우는 대신, 아무 상태도 공유하지 않는 인스턴스를 하나 더
만들어 같은 상황을 만든다.
"""

import os
import tempfile
import time
import unittest
import uuid

from backend import main


def _other_worker() -> main._SharedDict:
    """같은 디렉터리를 보는, 메모리를 공유하지 않는 두 번째 인스턴스."""
    return main._SharedDict("infoguard_masked", lambda raw: main._MaskedFile(**raw), main.asdict)


class SharedRegistryTest(unittest.TestCase):
    def test_other_worker_sees_the_copy(self):
        file_id = uuid.uuid4().hex
        copy_path = os.path.join(tempfile.mkdtemp(prefix="reg_test_"), "명단_masked.xlsx")
        open(copy_path, "wb").close()
        main._masked_files[file_id] = main._MaskedFile(
            path=copy_path,
            download_name="명단_masked.xlsx",
            created_at=time.time(),
            batch_id=uuid.uuid4().hex,
        )
        try:
            entry = _other_worker().get(file_id)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.path, copy_path)
            self.assertEqual(entry.download_name, "명단_masked.xlsx")
        finally:
            main._masked_files.pop(file_id, None)

    def test_path_shaped_id_is_not_a_key(self):
        # /download/{file_id}로 사용자 입력이 그대로 들어온다.
        self.assertIsNone(main._masked_files.get("../../etc/passwd"))
        self.assertNotIn("../../etc/passwd", main._masked_files)


if __name__ == "__main__":
    unittest.main()
