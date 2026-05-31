import time

from log import setup_logger
from scraper import RUN_INTERVAL_SECONDS, scrape_active_sources


def main():
    logger = setup_logger()
    try:
        while True:
            scrape_active_sources(logger=logger)
            logger.info(f"本輪爬取完成，等待 {RUN_INTERVAL_SECONDS // 60} 分鐘後再次執行...")
            time.sleep(RUN_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("收到中斷 (KeyboardInterrupt)，程式結束。")


if __name__ == "__main__":
    main()