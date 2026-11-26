import sys
import pathlib
# Ensure the repository root (parent of 'benchmark') is in sys.path for imports
repo_root = pathlib.Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
