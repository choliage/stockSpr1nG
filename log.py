import logging
import os
from datetime import datetime


def get_news_root(base_dir=None):
    if base_dir is None:
        base_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(base_dir, "News_txts")


def get_log_dir(base_dir=None):
    return os.path.join(get_news_root(base_dir), "logs")


def get_log_file_path(base_dir=None, date=None):
    if date is None:
        date = datetime.now()
    date_str = date.strftime("%Y_%m_%d")
    return os.path.join(get_log_dir(base_dir), f"{date_str}.log")


def setup_logger(name="stock_scraper", base_dir=None, level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # Clear existing handlers so repeated setup calls don't duplicate output
    if logger.handlers:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    log_file_path = get_log_file_path(base_dir)
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
