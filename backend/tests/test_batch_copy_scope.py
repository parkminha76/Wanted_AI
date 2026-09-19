"""배치 .zip이 "이 배치의 사본만" 묶는지 본다.

파일마다 마스킹 방식을 다르게 고를 수 있어서, 화면은 검사 때 만든 전체 마스킹 사본과
나중에 만든 부분 마스킹 사본을 섞어서 요청한다. 부분 마스킹 사본은 배치 목록(_batches)에
없지만 같은 배치의 것이므로 받아야 하고, 다른 배치의 사본은 끼워 넣을 수 없어야 한다.
"""

import time
import unittest

from backend import main


def register(file_id: str, batch_id: str | None) -> None:
    main._masked_files[file_id] = main._MaskedFile(
        path=f"/tmp/{file_id}",
        download_name=f"{file_id}.pdf",
        created_at=time.time(),
        batch_id=batch_id,
    )


class BatchTagTest(unittest.TestCase):
    def setUp(self) -> None:
        self._files = dict(main._masked_files)
        self._batches = dict(main._batches)
        main._masked_files.clear()
        main._batches.clear()

    def tearDown(self) -> None:
        main._masked_files.clear()
        main._masked_files.update(self._files)
        main._batches.clear()
        main._batches.update(self._batches)

    def test_scan_copy_carries_its_batch(self) -> None:
        register("a", "b1")
        self.assertEqual(main._batch_of("a"), "b1")

    def test_partial_copy_inherits_the_batch_it_replaces(self) -> None:
        register("a", "b1")
        # /mask가 하는 일과 같다: 대체 대상의 배치를 물려준다.
        register("a_partial", main._batch_of("a"))
        self.assertEqual(main._batch_of("a_partial"), "b1")

    def test_copy_from_another_batch_is_not_ours(self) -> None:
        register("a", "b1")
        register("z", "b2")
        self.assertNotEqual(main._batch_of("z"), "b1")

    def test_unknown_id_has_no_batch(self) -> None:
        self.assertIsNone(main._batch_of("nope"))
        self.assertIsNone(main._batch_of(None))


if __name__ == "__main__":
    unittest.main()
