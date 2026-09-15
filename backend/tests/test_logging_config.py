from __future__ import annotations

import json
import logging
import unittest
from io import StringIO

from backend.shared.logging_config import (
    _JsonFormatter,
    log_event,
    reset_request_id,
    set_request_id,
)


class PrivacyLoggingTest(unittest.TestCase):
    def test_only_allowlisted_metadata_is_emitted(self) -> None:
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_JsonFormatter())

        logger = logging.getLogger("infoguard.test.privacy")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        sentinel = "MUST_NOT_APPEAR_48291"
        token = set_request_id("request-123")
        try:
            log_event(
                logger,
                logging.INFO,
                "scan.checked",
                file_count=2,
                total_findings=3,
                raw_text=sentinel,
                filename=sentinel,
                batch_id=sentinel,
                session_id=sentinel,
            )
        finally:
            reset_request_id(token)

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "scan.checked")
        self.assertEqual(payload["request_id"], "request-123")
        self.assertEqual(payload["file_count"], 2)
        self.assertEqual(payload["total_findings"], 3)
        self.assertNotIn(sentinel, stream.getvalue())
        self.assertNotIn("raw_text", payload)
        self.assertNotIn("filename", payload)
        self.assertNotIn("batch_id", payload)
        self.assertNotIn("session_id", payload)


if __name__ == "__main__":
    unittest.main()

