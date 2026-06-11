from concurrent.futures import ThreadPoolExecutor
from typing import Any

EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict[str, Any]] = {}
