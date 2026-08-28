"""Central logging config — replaces scattered print() calls."""
import logging
import sys


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    
    # Silence noisy third-party loggers
    logging.getLogger("JobSpy").setLevel(logging.ERROR)
    logging.getLogger("JobSpy:Google").setLevel(logging.ERROR)
    logging.getLogger("JobSpy:LinkedIn").setLevel(logging.ERROR)

    return logger
