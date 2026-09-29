from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = REPO_ROOT / "tasks"
BUILD_DIR = REPO_ROOT / "build"
TASK_BASE_LOCK = REPO_ROOT / "images" / "task-base.lock"
MATRIX_FILE = REPO_ROOT / "matrix.toml"
