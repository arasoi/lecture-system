import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# How long a recording must sit untouched before it is considered finished. This has to
# outlast the interval between OneDrive sync bursts, which was measured at 10-14 minutes.
DEFAULT_QUIET_PERIOD_SECONDS = 1200.0


def seconds_since_last_write(path: Path) -> float:
    """
    How long ago the recording was last written to.

    Clamped at zero: the modification time comes from whichever machine wrote the file,
    so clock skew can place it slightly in the future. Treating that as "just written"
    defers the recording until the local clock catches up rather than processing it early.
    """
    return max(time.time() - path.stat().st_mtime, 0.0)


def recording_is_quiet(path: Path, quiet_seconds: float = DEFAULT_QUIET_PERIOD_SECONDS) -> bool:
    """
    True when nothing has written to `path` for `quiet_seconds`.

    OneDrive uploads an in-progress recording in bursts roughly ten minutes apart, and
    between bursts the file sits at a constant size. `wait_for_file_stability` cannot tell
    that lull apart from a finished recording, so the quiet period has to outlast the sync
    cadence. A quiet period of zero disables the check.
    """
    if quiet_seconds <= 0:
        return True
    return seconds_since_last_write(path) >= quiet_seconds


class FileProcessorQueue:
    def __init__(self, process_callback, maxsize: int = 128):
        self.queue = queue.Queue(maxsize=maxsize)
        self.process_callback = process_callback
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def enqueue(self, path: Path):
        while True:
            try:
                self.queue.put(path, timeout=5)
                return
            except queue.Full:
                logger.warning("Processing queue is full; waiting to enqueue %s", path)

    def _worker(self):
        while True:
            path = self.queue.get()
            try:
                self.process_callback(path)
            except Exception:
                logger.exception("Error processing %s", path)
            finally:
                self.queue.task_done()


def _create_stable_file_handler(callback: Callable[[Path], None], supported_extensions=None):
    try:
        from watchdog.events import FileSystemEventHandler
    except ImportError as exc:
        raise RuntimeError(
            "watchdog is required for folder watching. Install it with `pip install -r requirements.txt`."
        ) from exc

    class StableFileHandler(FileSystemEventHandler):
        def __init__(self, callback: Callable[[Path], None], supported_extensions=None):
            super().__init__()
            self.callback = callback
            self.supported_extensions = supported_extensions

        def on_created(self, event):
            self._enqueue_event(event)

        def on_modified(self, event):
            self._enqueue_event(event)

        def _enqueue_event(self, event):
            if event.is_directory:
                return

            path = Path(event.src_path)
            if self.supported_extensions and path.suffix.lower() not in self.supported_extensions:
                return

            logger.debug("Queued file event for %s", path)
            self.callback(path)

    return StableFileHandler(callback, supported_extensions=supported_extensions)


def watch_directory(source_dir: Path, process_callback: Callable[[Path], None], supported_extensions=None):
    try:
        from watchdog.observers import Observer
    except ImportError as exc:
        raise RuntimeError(
            "watchdog is required for folder watching. Install it with `pip install -r requirements.txt`."
        ) from exc

    event_handler = _create_stable_file_handler(process_callback, supported_extensions=supported_extensions)
    observer = Observer()
    observer.schedule(event_handler, str(source_dir), recursive=False)
    observer.start()
    return observer


def wait_for_file_stability(path: Path, stable_seconds: float = 10.0, check_interval: float = 2.0, timeout: float = 300.0) -> bool:
    if not path.exists():
        return False

    start = time.time()
    last_size = path.stat().st_size
    stable_since = time.time()

    while True:
        time.sleep(check_interval)
        if not path.exists():
            return False

        current_size = path.stat().st_size
        if current_size != last_size:
            last_size = current_size
            stable_since = time.time()
            logger.debug("File %s size changed; waiting", path)
        elif time.time() - stable_since >= stable_seconds:
            return True

        if time.time() - start > timeout:
            logger.warning("Timed out waiting for %s to become stable", path)
            return False
