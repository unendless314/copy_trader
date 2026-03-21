"""
tests/conftest.py

Make the src/ package importable without requiring `pip install -e .` first.
Adds the src/ directory to sys.path so that `pytest tests/` works in a clean
checkout after only `pip install -r requirements.txt` or equivalent.
"""

import sys
from pathlib import Path

# Insert src/ at the front of sys.path if not already present
_src = str(Path(__file__).parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
