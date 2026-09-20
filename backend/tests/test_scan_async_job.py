"""비동기 검사(/scan/async, /scan/async/{job_id})가 결과를 맞게 전달하는지 확인한다.

실측(2026-09-20, DocXray_합성데이터_5MB.log): 이 파일은 25,146줄 전부에 한글이
섞여 있어(로그 메시지 자체가 한국어라 PII 유무와 무관) NER 청크 필터가 줄이지
못했고, batch_size를 키워도 CPU 연산량 자체가 병목이라 전체 처리에 약 17분이
걸린다. 프런트엔드 fetch 타임아웃(180초)·Railway 프록시 타임아웃(5분) 둘 다
그보다 짧아 동기 응답(/scan)으로는 끝을 볼 수 없다. job_id만 즉시 돌려주고
백그라운드 스레드에서 실제 검사를 돌리는 구조로 바꿨다.
"""

from __future__ import annotations

import io
import time
import unittest
from unittest.mock import patch

from fastapi import UploadFile

from backend import main
from backend.shared import schema


def _fake_scan_files(paths, **kwargs):
    """실제 scan.scan_files처럼 결과의 filename에 받은 경로를 그대로 넣는다.

    main.py는 이후 display_name(경로->원래 파일명) 매핑으로 이 경로를 사용자가
    올린 이름으로 되돌리므로, 가짜 구현도 그 계약을 지켜야 한다.
    """
    results = []
    for path in paths:
        result = schema.ScanResult(filename=path, raw_text="hello world")
        result.finalize()
        results.append(result)
    return schema.ScanBatch(results=results)


class ScanAsyncJobTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        main._scan_jobs.clear()

    async def test_submit_then_poll_returns_the_same_shape_as_sync_scan(self) -> None:
        upload = UploadFile(io.BytesIO(b"hello world"), filename="a.txt")

        with patch.object(main.scan, "scan_files", side_effect=_fake_scan_files):
            submitted = await main.scan_upload_async([upload], masking_policy_json=None, create_masked_copy=False)

        self.assertEqual(submitted["status"], "running")
        job_id = submitted["job_id"]

        # 백그라운드 스레드가 끝날 때까지 잠깐 기다린다(가짜 scan_files라 즉시 끝난다).
        deadline = time.time() + 5
        status = main.scan_job_status(job_id)
        while status["status"] == "running" and time.time() < deadline:
            time.sleep(0.05)
            status = main.scan_job_status(job_id)

        self.assertEqual(status["status"], "done")
        self.assertEqual(status["result"]["results"][0]["filename"], "a.txt")
        self.assertIn("masking_policy", status["result"])

    def test_unknown_job_id_returns_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            main.scan_job_status("no-such-job")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_scan_failure_is_reported_as_error_status(self) -> None:
        upload = UploadFile(io.BytesIO(b"hello world"), filename="a.txt")

        with patch.object(main.scan, "scan_files", side_effect=RuntimeError("boom")):
            submitted = await main.scan_upload_async([upload], masking_policy_json=None, create_masked_copy=False)

        job_id = submitted["job_id"]
        deadline = time.time() + 5
        status = main.scan_job_status(job_id)
        while status["status"] == "running" and time.time() < deadline:
            time.sleep(0.05)
            status = main.scan_job_status(job_id)

        self.assertEqual(status["status"], "error")
        self.assertTrue(status["detail"])


if __name__ == "__main__":
    unittest.main()
