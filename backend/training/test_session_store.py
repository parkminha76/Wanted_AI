import multiprocessing
import unittest
from uuid import uuid4

from backend.training.session_store import TrainingJsonStore


def _read_store_in_another_process(namespace: str, key: int, queue) -> None:
    queue.put(TrainingJsonStore(namespace).get(key))


class TrainingJsonStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.namespace = f"infoguard_training_test_{uuid4().hex}"
        self.store = TrainingJsonStore(self.namespace)

    def tearDown(self) -> None:
        self.store.clear()

    def test_second_store_instance_sees_session(self) -> None:
        self.store[17] = {
            "status": "in_progress",
            "history": [{"role": "user", "content": "test"}],
        }

        other_worker_store = TrainingJsonStore(self.namespace)

        self.assertEqual(other_worker_store.get(17), self.store.get(17))

    def test_separate_process_sees_session(self) -> None:
        self.store[23] = {"level": 2, "turn_no": 1}
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        process = context.Process(
            target=_read_store_in_another_process,
            args=(self.namespace, 23, queue),
        )

        process.start()
        process.join(timeout=10)

        self.assertEqual(process.exitcode, 0)
        self.assertEqual(queue.get(timeout=1), {"level": 2, "turn_no": 1})

    def test_pop_removes_shared_value(self) -> None:
        self.store[31] = {"score": 100}

        self.assertEqual(self.store.pop(31), {"score": 100})
        self.assertIsNone(TrainingJsonStore(self.namespace).get(31))


if __name__ == "__main__":
    unittest.main()
