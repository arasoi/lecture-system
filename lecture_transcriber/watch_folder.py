import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


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
            self.recently_seen = {}

        def on_created(self, event):
            if event.is_dir:
                return
            path = Path(event.src_path)
            if self.supported_extensions and path.suffix.lower() not in self.supported_extensions:
                return
            logger.info("File created: %s", path)
            self.recently_seen[str(path)] = time.time()

        def on_modified(self, event):
            if event.is_dir:
                return
            path = Path(event.src_path)
            if self.supported_extensions and path.suffix.lower() not in self.supported_extensions:
                return
            self.recently_seen[str(path)] = time.time()

        def check_stable_files(self):
            now = time.time()
            stable = []
            for fpath, seen_time in list(self.recently_seen.items()):
                if now - seen_time > 2:  # 2 second stability window
                    stable.append(fpath)
                    del self.recently_seen[fpath]
            return stable

    return StableFileHandler(callback, supported_extensions)


def watch_directory(source_dir: Path, callback: Callable[[Path], None], extensions=None):
    """Watch a directory for new files."""
    try:
        from watchdog.observers import Observer
    except ImportError as exc:
        raise RuntimeError(
            "watchdog is required for folder watching. Install it with `pip install -r requirements.txt`."
        ) from exc
    
    observer = Observer()
    handler = _create_stable_file_handler(callback, extensions)
    observer.schedule(handler, str(source_dir), recursive=False)
    observer.start()
    return observer


def wait_for_file_stability(path: Path, timeout: float = 5.0) -> bool:
    """Wait for a file to become stable (not being written to)."""
    import os
    start_time = time.time()
    last_size = -1
    
    while time.time() - start_time < timeout:
        try:
            current_size = os.path.getsize(path)
            if current_size == last_size:
                return True
            last_size = current_size
            time.sleep(0.5)
        except OSError:
            time.sleep(0.5)
    
    return False
