import time
import os

import log
from scraper import scrape_udn_latest_stock_news

DEFAULT_BASE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
logger = log.setup_logger(base_dir=DEFAULT_BASE_DIR)

if __name__ == "__main__":
    try:
        while True:
            scrape_udn_latest_stock_news(base_dir=DEFAULT_BASE_DIR)
            logger.info("本輪爬取完成，等待 90 分鐘後再次執行...")
            time.sleep(90 * 60)
    except KeyboardInterrupt:
        logger.info("收到中斷 (KeyboardInterrupt)，程式結束。")