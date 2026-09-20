from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterator
from typing import Any


class TrainingJsonStore:
    """Process-shared JSON store for training state."""

    def __init__(self, namespace: str) -> None:
        self._directory = os.path.join(tempfile.gettempdir(), namespace)

    def _path(self, key: int) -> str:
        if not isinstance(key, int) or isinstance(key, bool) or key < 1:
            raise KeyError(key)
        return os.path.join(self._directory, f"{key}.json")

    def get(self, key: int, default: Any = None) -> Any:
        try:
            with open(self._path(key), encoding="utf-8") as file:
                return json.load(file)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return default

    def __setitem__(self, key: int, value: Any) -> None:
        path = self._path(key)
        os.makedirs(self._directory, exist_ok=True)
        temporary_path = f"{path}.tmp{os.getpid()}"
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False)
        for attempt in range(5):
            try:
                os.replace(temporary_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)

    def pop(self, key: int, default: Any = None) -> Any:
        value = self.get(key, default)
        try:
            os.remove(self._path(key))
        except (OSError, KeyError):
            pass
        return value

    def items(self) -> Iterator[tuple[int, Any]]:
        try:
            names = os.listdir(self._directory)
        except OSError:
            return
        for name in names:
            stem, extension = os.path.splitext(name)
            if extension != ".json" or not stem.isdigit():
                continue
            key = int(stem)
            value = self.get(key)
            if value is not None:
                yield key, value

    def clear(self) -> None:
        for key, _ in list(self.items()):
            self.pop(key, None)
