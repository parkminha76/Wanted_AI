"""실측 재현(2026-09-20, Railway 배포): `_get_pipeline`의 지연 초기화가 락
없이 `if _pipeline is None`만 봤다. 콜드 스타트 직후 여러 요청(XLSX는 셀마다
detect()를 부른다)이 거의 동시에 들어오면 전부 캐시가 비어 있는 걸 보고 각자
모델을 처음부터 새로 불러왔다 — 배포 로그에 "Loading weights: 0%"가 같은 몇
초 사이 수십 번 반복해서 시작되는 것으로 확인됐다. 작은 인스턴스에서 이게
동시에 겹치면 CPU를 서로 뺏어가며 몇 초면 끝날 로딩이 몇 분으로 늘어난다.

이 테스트는 실제 모델을 불러오지 않고, 지연 초기화 함수 자체가 동시 호출에서
"딱 한 번만" 무거운 생성자를 부르는지만 확인한다(`transformers.pipeline`을
가짜로 바꿔치기).
"""

import threading
import time
import unittest
from unittest.mock import patch

from backend.scanner.detectors import ner


class GetPipelineThreadSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        # 모듈 전역 캐시를 테스트마다 깨끗하게 되돌린다.
        self._original_pipeline = ner._pipeline
        ner._pipeline = None

    def tearDown(self) -> None:
        ner._pipeline = self._original_pipeline

    def test_concurrent_calls_construct_the_pipeline_exactly_once(self) -> None:
        call_count = 0
        call_count_lock = threading.Lock()

        def _slow_fake_pipeline(*args, **kwargs):
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            # 실제 모델 로딩처럼 시간이 걸리는 것을 흉내 낸다 — 이 지연 동안
            # 다른 스레드들이 몰려야 락 없이는 재현되지 않던 경쟁이 재현된다.
            time.sleep(0.2)
            return object()

        with patch("transformers.pipeline", side_effect=_slow_fake_pipeline):
            threads = [threading.Thread(target=ner._get_pipeline) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(
            call_count, 1,
            f"파이프라인 생성자가 {call_count}번 불렸다 — 동시 요청에서 락이 안 걸리고 있다",
        )

    def test_all_threads_receive_the_same_cached_object(self) -> None:
        with patch("transformers.pipeline", side_effect=lambda *a, **k: object()):
            results: list[object] = []
            results_lock = threading.Lock()

            def _call_and_record():
                pipe = ner._get_pipeline()
                with results_lock:
                    results.append(pipe)

            threads = [threading.Thread(target=_call_and_record) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(len(results), 20)
        self.assertEqual(len(set(id(r) for r in results)), 1)


if __name__ == "__main__":
    unittest.main()
