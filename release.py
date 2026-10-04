"""Installation identity and exclusive maintenance; no GUI dependencies."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess

REPOSITORY = "https://github.com/SydFloyd/abide.git"
CODE_FILES = ("app.py", "app.css", "focus.py", "install.py", "launcher.sh",
              "bindings.py", "config.py", "release.py", "updater.py")


def file_hashes(source):
    result = {}
    for name in CODE_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("The release is incomplete: " + name)
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def manifest(source):
    files = file_hashes(source)
    try:
        def git(*arguments):
            return subprocess.check_output(["git", "-C", str(source), *arguments],
                                           text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        if Path(git("rev-parse", "--show-toplevel")).resolve() != source.resolve():
            raise OSError("Not an Abide checkout")
        revision = git("rev-parse", "HEAD")
        tracked = set(git("ls-files", "--", *CODE_FILES).splitlines())
        dirty = bool(git("status", "--porcelain", "--untracked-files=all", "--", *CODE_FILES))
        return {"format": 1, "repository": REPOSITORY, "revision": revision,
                "local_changes": dirty or tracked != set(CODE_FILES), "files": files}
    except (OSError, subprocess.SubprocessError):
        try:
            saved = json.loads((source / "release.json").read_text())
            if saved.get("format") == 1 and saved.get("files") == files:
                return saved
        except (OSError, ValueError, AttributeError):
            pass
        return {"format": 1, "repository": REPOSITORY, "revision": None,
                "local_changes": True, "files": files}


def install_identity(root):
    return hashlib.sha256((root / "release.json").read_bytes()).hexdigest()


def verify_installation(root, expected):
    if install_identity(root) != expected:
        raise RuntimeError("Abide changed while the update was being prepared. Check again before installing.")
    try:
        saved = json.loads((root / "release.json").read_text())
        files = saved["files"]
        if not isinstance(files, dict) or not files:
            raise ValueError("Missing installed files")
        for name, checksum in files.items():
            path = root / name
            if Path(name).name != name or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError("Installed code changed")
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("Abide has local code changes. The update will preserve them.") from None


@contextmanager
def maintenance_lock(state, name="maintenance.lock"):
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (state / name).open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another Abide installation or update is running. Try again when it finishes.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
