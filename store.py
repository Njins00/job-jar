import os
import json
import fcntl
import tempfile
from pathlib import Path
from contextlib import contextmanager

# tiny json store shared by the bot and the dashboard.
# one lock so they never write over each other, and atomic
# writes so a crash mid-save can't leave half a jobs.json behind.


def _jobs_path() -> Path:
    return Path(os.getenv("DATA_FILE", "jobs.json"))


def _state_path() -> Path:
    return _jobs_path().with_name("state.json")


@contextmanager
def _locked():
    lock = _jobs_path().with_name("jobs.lock")
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _write(path: Path, data: dict):
    # temp file in the same folder, then swap it in
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_jobs() -> dict:
    with _locked():
        return _read(_jobs_path())


def update_jobs(fn):
    # read, change, write under one lock - fn edits the dict in place
    with _locked():
        jobs = _read(_jobs_path())
        result = fn(jobs)
        _write(_jobs_path(), jobs)
        return result


def load_state() -> dict:
    with _locked():
        return _read(_state_path())


def save_state(**kwargs):
    with _locked():
        state = _read(_state_path())
        state.update(kwargs)
        _write(_state_path(), state)
