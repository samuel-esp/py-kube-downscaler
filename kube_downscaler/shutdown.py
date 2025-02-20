import contextlib
import logging
import signal
import sys
import threading


class GracefulShutdown:
    shutdown_now = False
    safe_to_exit = False

    def __init__(self):
        if threading.current_thread() == threading.main_thread():
            signal.signal(signal.SIGINT, self.exit_gracefully)
            signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        logging.info("Shutting down gracefully")
        self.shutdown_now = True
        if self.safe_to_exit:
            sys.exit(0)

    @contextlib.contextmanager
    def safe_exit(self):
        self.safe_to_exit = True
        yield
        self.safe_to_exit = False
