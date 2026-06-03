import time
import os
import log
from scraper import scrape_udn_latest_stock_news
from keyword_scanner import scan_keywords_and_export_excels
from financial_report_scraper import FinancialReportScraper
from news_financial_analyzer import save_analysis_excel

DEFAULT_BASE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
DEFAULT_FINANCIAL_REPORT_DIR = os.path.join(DEFAULT_BASE_DIR, "Financial_Reports")
logger = log.setup_logger(base_dir=DEFAULT_BASE_DIR)

if __name__ == "__main__":
    def run_financial_report_scraper(base_dir=None):
        if base_dir is None:
            base_dir = DEFAULT_BASE_DIR

        scraper = FinancialReportScraper(
            download_base_dir=DEFAULT_FINANCIAL_REPORT_DIR,
            max_workers=2,
            qps=0.25,
            headless=True,
            request_timeout=60,
            recent_years=3,
            start_roc_year_floor=1,
        )

        try:
            print("\n請選擇抓取範圍：")
            print("1. 全部公司")
            print("2. 指定起始與結束公司代號")
            choice = input("請輸入選項 (1/2): ").strip()
            if choice == "2":
                start_c = input("請輸入起始公司代號 (例: 1101): ").strip()
                end_c = input("請輸入最後公司代號 (例: 2330): ").strip()
                if start_c > end_c:
                    start_c, end_c = end_c, start_c
                scraper.run_parallel(start_code=start_c, end_code=end_c)
            else:
                scraper.run_parallel()
        finally:
            scraper.close()

    try:
        while True:
            print("\n=== 選擇執行模式 ===")
            print("1. 爬取最新 UDN 股票新聞並掃描關鍵字")
            print("2. 僅掃描已抓取新聞的關鍵字並輸出 Excel")
            print("3. 下載 MOPS 財務報告 PDF")
            print("4. 生成新聞與財報整合分析報表")
            print("0. 結束程式")
            choice = input("請輸入選項 (0/1/2/3/4): ").strip()

            if choice == "1":
                scrape_udn_latest_stock_news(base_dir=DEFAULT_BASE_DIR)
                output_files = scan_keywords_and_export_excels(base_dir=DEFAULT_BASE_DIR)
                if output_files:
                    logger.info(f"已產生關鍵字月度 Excel：{', '.join(output_files)}")
                else:
                    logger.info("本次未找到任何關鍵字，未生成 Excel。")
            elif choice == "2":
                output_files = scan_keywords_and_export_excels(base_dir=DEFAULT_BASE_DIR)
                if output_files:
                    logger.info(f"已產生關鍵字月度 Excel：{', '.join(output_files)}")
                else:
                    logger.info("本次未找到任何關鍵字，未生成 Excel。")
            elif choice == "3":
                run_financial_report_scraper(base_dir=DEFAULT_BASE_DIR)
            elif choice == "4":
                try:
                    output_path = save_analysis_excel(base_dir=DEFAULT_BASE_DIR)
                    logger.info(f"已產生新聞與財報整合分析報表：{output_path}")
                except Exception as exc:
                    logger.exception(f"生成整合分析報表時發生錯誤：{exc}")
            elif choice == "0":
                logger.info("程式結束。")
                break
            else:
                logger.warning("無效選項，請重新輸入。")

            if choice in {"1", "2"}:
                logger.info("本輪執行完成，等待 90 分鐘後再次執行...")
                time.sleep(90 * 60)
    except KeyboardInterrupt:
        logger.info("收到中斷 (KeyboardInterrupt)，程式結束。")