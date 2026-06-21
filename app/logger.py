import logging
import sys
from datetime import datetime


def setup_logger(name: str = "fitting_room") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()


class ServiceLogger:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self._logger = logger

    def info(self, action: str, detail: str = None, **kwargs):
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        msg = f"[{self.service_name}] {action}"
        if detail:
            msg += f" | {detail}"
        if extra:
            msg += f" | {extra}"
        self._logger.info(msg)

    def warning(self, action: str, detail: str = None, **kwargs):
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        msg = f"[{self.service_name}] {action}"
        if detail:
            msg += f" | {detail}"
        if extra:
            msg += f" | {extra}"
        self._logger.warning(msg)

    def error(self, action: str, detail: str = None, exc_info: bool = False, **kwargs):
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        msg = f"[{self.service_name}] {action}"
        if detail:
            msg += f" | {detail}"
        if extra:
            msg += f" | {extra}"
        self._logger.error(msg, exc_info=exc_info)
