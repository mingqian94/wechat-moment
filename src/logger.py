import sys
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
KEEP_DAYS = 30


def _log_path() -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    return LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"


def _cleanup():
    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    for f in LOG_DIR.glob("*.log"):
        try:
            date = datetime.strptime(f.stem, "%Y%m%d")
            if date < cutoff:
                f.unlink()
        except ValueError:
            pass


def init():
    _cleanup()


def write(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}\n"
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"[logger] 写入失败: {e}", file=sys.stderr)
