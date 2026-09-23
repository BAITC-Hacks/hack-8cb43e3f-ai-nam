import os
import sys
import tempfile
from pathlib import Path

# Изолированное окружение для тестов: отдельная папка данных, без демо-наполнения и без ИИ-модели
_tmp = tempfile.mkdtemp(prefix="orgai_test_")
os.environ["DATA_DIR"] = _tmp
os.environ["SEED_DEMO"] = "false"
os.environ["LLM_PROVIDER"] = "none"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "admin12345"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
