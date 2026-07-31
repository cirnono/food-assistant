from __future__ import annotations

import os
import tempfile


_test_data_dir = tempfile.mkdtemp(prefix="food-assistant-tests-")
os.environ.setdefault("DATA_DIR", _test_data_dir)
os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{_test_data_dir}/test.db"
)
os.environ.setdefault(
    "FOOD_ASSISTANT_API_TOKEN", "example-development-token-00000000"
)
