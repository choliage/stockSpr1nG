import time
import os
import log
from scraper import scrape_udn_latest_stock_news
from keyword_scanner import scan_keywords_and_export_excels

DEFAULT_BASE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
logger = log.setup_logger(base_dir=DEFAULT_BASE_DIR)

if __name__ == "__main__":
    try:
        while True:
            scrape_udn_latest_stock_news(base_dir=DEFAULT_BASE_DIR)
            output_files = scan_keywords_and_export_excels(base_dir=DEFAULT_BASE_DIR)
            if output_files:
                logger.info(f"已產生關鍵字月度 Excel：{', '.join(output_files)}")
            else:
                logger.info("本次未找到任何關鍵字，未生成 Excel。")
            logger.info("本輪爬取完成，等待 90 分鐘後再次執行...")
            time.sleep(90 * 60)
    except KeyboardInterrupt:
        logger.info("收到中斷 (KeyboardInterrupt)，程式結束。")