"""Put src/ on the import path so tests import `fetch_data.*` and `analysis.*` like notebooks do."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
