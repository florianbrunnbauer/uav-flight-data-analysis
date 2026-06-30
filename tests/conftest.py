import sys
import types
from pathlib import Path

# Make imports such as `from analysis import ...` work when pytest is called
# from the repository root or when the tests folder is passed explicitly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Optional safety for very isolated test environments: analysis.py imports
# ulg_reader.py, and ulg_reader.py imports pyulog. The tests use fake log
# objects and do not instantiate ULog, so a tiny stub keeps pure unit tests
# importable even when pyulog is not installed. In the normal project environment,
# pyulog from requirements.txt will be imported normally.
try:
    import pyulog  # noqa: F401
except ModuleNotFoundError:
    pyulog_stub = types.ModuleType("pyulog")

    class _DummyULog:  # pragma: no cover - only used when pyulog is missing
        def __init__(self, *args, **kwargs):
            raise RuntimeError("pyulog is not installed in this test environment")

    pyulog_stub.ULog = _DummyULog
    sys.modules["pyulog"] = pyulog_stub
