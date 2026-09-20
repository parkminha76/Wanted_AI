"""실측(2026-09-20, Railway 배포): 컨테이너 재시작 직후 검사 요청 6개가 거의
동시에 들어오자, CPU 1개짜리 인스턴스에서 서로 자원을 뺏어가며 원래 1초 안팎
이면 끝날 검사가 최대 370초까지 늘어졌다. scan_file을 세마포로 줄 세워
한 번에 하나씩만 처리하게 했다 — 이 테스트는 실제 파싱·탐지 로직 없이,
동시 호출이 실제로 겹치지 않고 한 번에 하나씩만 실행되는지만 확인한다.
"""

import threading
import time
import unittest
from unittest.mock import patch

from backend.scanner import scan


class ScanFileSerializationTest(unittest.TestCase):
    def test_concurrent_calls_never_overlap(self) -> None:
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_impl(path, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return f"result:{path}"

        with patch.object(scan, "_scan_file_locked", side_effect=fake_impl):
            threads = [
                threading.Thread(target=scan.scan_file, args=(f"file{i}.txt",))
                for i in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(
            max_active, 1,
            f"동시에 최대 {max_active}건이 실행됐다 — 세마포가 줄을 안 세우고 있다",
        )

    def test_results_are_still_correct_per_call(self) -> None:
        with patch.object(scan, "_scan_file_locked", side_effect=lambda path, **kw: path):
            self.assertEqual(scan.scan_file("a.txt"), "a.txt")
            self.assertEqual(scan.scan_file("b.txt"), "b.txt")


if __name__ == "__main__":
    unittest.main()
