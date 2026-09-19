import atexit
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"

for p in (SRC, TESTS):
    # TESTS is on the path so the bucketed files (unit/, golden/, property/,
    # integration/) can all `from conftest import ...`. pytest only inserts each
    # test file's own directory, not the tests root.
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CONFIG_DIR = ROOT / "config"
DATASET_DIR = ROOT / "dataset"
INBOX_DIR = DATASET_DIR / "inbox"
SAMPLE_SUBMISSION = DATASET_DIR / "sample_submission.json"

# Shared extraction cache for the whole test session. Without it every run_corpus()
# call re-renders and re-OCRs the three scanned PDFs, which took the suite from ~27s
# to over 10 minutes.
#
# It lives in a disposable temp dir, never in output/ (which holds exactly the four
# artifacts the system produces) and never in BACKUP/. A pytest `tmp_path_factory`
# would be the idiomatic home, but that is only reachable from a fixture, and this is
# consumed as a module-level constant inside test bodies — turning it into a fixture
# would mean editing those bodies, which this reorganisation must not do.
TEST_CACHE = Path(tempfile.mkdtemp(prefix="shipdoc-testcache-")) / "cache"
atexit.register(shutil.rmtree, TEST_CACHE.parent, True)
