"""Background worker: `python -m app.worker` (run one or more alongside the
API with JOB_MODE=queue)."""

import logging
import signal
import time

from app.queue import claim_and_run_one

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")

_stop = False


def _handle(signum, _frame):
    global _stop
    logger.info("Signal %s: finishing current job and stopping", signum)
    _stop = True


def main(poll_seconds: float = 2.0) -> None:
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    logger.info("Worker started")
    while not _stop:
        try:
            if not claim_and_run_one():
                time.sleep(poll_seconds)
        except Exception:  # noqa: BLE001 -- e.g. database restarting; keep the worker alive
            logger.exception("Worker loop error")
            time.sleep(5)


if __name__ == "__main__":
    main()
