import queue
import unittest
from pathlib import Path

from lecture_transcriber.watch_folder import FileProcessorQueue


class FileProcessorQueueTest(unittest.TestCase):
    def test_creates_queue_with_specified_maxsize(self):
        def callback(path):
            pass

        q = FileProcessorQueue(callback, maxsize=50)
        self.assertEqual(q.queue.maxsize, 50)

    def test_callback_receives_enqueued_path(self):
        import time

        received = []

        def callback(path):
            received.append(path)

        q = FileProcessorQueue(callback)
        test_path = Path("test.mp3")
        q.enqueue(test_path)
        time.sleep(0.1)  # Let worker thread process

        self.assertIn(test_path, received)


if __name__ == "__main__":
    unittest.main()