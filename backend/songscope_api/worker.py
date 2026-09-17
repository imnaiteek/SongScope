"""Standalone worker: `python -m songscope_api.worker` (set SONGSCOPE_EMBEDDED_WORKER=false on the API)."""

import logging
import signal
import threading

from .db import init_db
from .dispatcher import Dispatcher


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    dispatcher = Dispatcher()
    done = threading.Event()

    def shutdown(*_):
        done.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    dispatcher.start()
    logging.getLogger("songscope.worker").info("worker %s ready", dispatcher.worker_name)
    done.wait()
    dispatcher.stop()


if __name__ == "__main__":
    main()
