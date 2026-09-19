"""배치 .zip이 "이 배치의 사본만" 묶는지 본다.

파일마다 마스킹 방식을 다르게 고를 수 있어서, 화면은 검사 때 만든 전체 마스킹 사본과
나중에 만든 부분 마스킹 사본을 섞어서 요청한다. 부분 마스킹 사본은 배치 목록(_batches)에
없지만 같은 배치의 것이므로 받아야 하고, 다른 배치의 사본은 끼워 넣을 수 없어야 한다.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.shared import schema


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

    def test_zip_rejects_partial_result_when_one_selected_copy_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "available.pdf"
            path.write_bytes(b"available")
            main._masked_files["available"] = main._MaskedFile(
                path=str(path),
                download_name="available.pdf",
                created_at=time.time(),
                batch_id="b1",
            )
            main._batches["b1"] = ["available", "missing"]

            with self.assertRaises(HTTPException) as raised:
                main.download_all("b1", "available,missing")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("일부가 없거나", raised.exception.detail)

    def test_zip_rejects_copy_from_another_batch_instead_of_omitting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.pdf"
            other = Path(directory) / "other.pdf"
            first.write_bytes(b"first")
            other.write_bytes(b"other")
            for file_id, path, batch_id in (
                ("first", first, "b1"),
                ("other", other, "b2"),
            ):
                main._masked_files[file_id] = main._MaskedFile(
                    path=str(path),
                    download_name=path.name,
                    created_at=time.time(),
                    batch_id=batch_id,
                )
            main._batches["b1"] = ["first"]

            with self.assertRaises(HTTPException) as raised:
                main.download_all("b1", "first,other")

        self.assertEqual(raised.exception.status_code, 404)


class SampleSubsetBatchTagTest(unittest.TestCase):
    """실측 버그(2026-09-19): "샘플로 체험하기"에서 파일을 몇 개 골라 검사한 뒤
    "전체 파일 ZIP 받기"를 누르면 항상 404였다("선택 파일 다운받기"로 하나씩
    받는 건 멀쩡했다 — 증상이 갈렸던 이유는 아래 참고).

    `_sample_subset`이 고른 파일들을 새 batch_id로 `_batches`(배치 -> 파일 목록)에는
    등록하면서, 정작 각 파일의 `_masked_files[fid].batch_id`(파일 -> 배치 역방향
    조회, `_batch_of`가 쓰는 값이자 `/download/all`이 소속을 확인하는 값)는 예전
    batch_id를 그대로 가리키고 있었다. `/download/{id}`는 이 역방향 조회를 안 보고
    파일 존재만 확인해서 멀쩡했지만, `/download/all`은 매번 "선택한 사본 중 일부가
    없거나 보관 기간이 지났습니다"로 404였다.
    """

    def setUp(self) -> None:
        self._files = dict(main._masked_files)
        self._batches = dict(main._batches)
        self._sample_batch = main._sample_batch
        main._masked_files.clear()
        main._batches.clear()

    def tearDown(self) -> None:
        main._masked_files.clear()
        main._masked_files.update(self._files)
        main._batches.clear()
        main._batches.update(self._batches)
        main._sample_batch = self._sample_batch

    def test_subset_files_are_downloadable_as_a_zip_under_the_new_batch_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path_a = Path(directory) / "a.pdf"
            path_b = Path(directory) / "b.pdf"
            path_a.write_bytes(b"a")
            path_b.write_bytes(b"b")

            main._masked_files["a"] = main._MaskedFile(
                path=str(path_a), download_name="a.pdf", created_at=time.time(),
                batch_id="parent-batch",
            )
            main._masked_files["b"] = main._MaskedFile(
                path=str(path_b), download_name="b.pdf", created_at=time.time(),
                batch_id="parent-batch",
            )
            main._batches["parent-batch"] = ["a", "b"]
            main._sample_batch = schema.ScanBatch(
                results=[
                    schema.ScanResult(filename="a.pdf", file_id="a"),
                    schema.ScanResult(filename="b.pdf", file_id="b"),
                ],
                batch_id="parent-batch",
            )

            subset = main._sample_subset("a.pdf,b.pdf")
            subset_batch_id = subset["batch_id"]

            self.assertNotEqual(subset_batch_id, "parent-batch")
            self.assertEqual(main._batch_of("a"), subset_batch_id)
            self.assertEqual(main._batch_of("b"), subset_batch_id)

            # 예전 버그라면 여기서 HTTPException(404)이 났다.
            response = main.download_all(subset_batch_id, "a,b")
            self.assertTrue(os.path.exists(response.path))


if __name__ == "__main__":
    unittest.main()
