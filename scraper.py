import os
import re
import hashlib
import gzip
import pickle
import time
import logging
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from newspaper import Article

logger = logging.getLogger("stock_scraper")
DEFAULT_BASE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")


def save_article_as_txt(full_link, title, publish_date, text, base_dir=None):
    if base_dir is None:
        base_dir = DEFAULT_BASE_DIR

    news_root = os.path.join(base_dir, "News_txts")
    os.makedirs(news_root, exist_ok=True)

    date_obj = None
    if publish_date is None:
        date_obj = datetime.now()
    elif isinstance(publish_date, datetime):
        date_obj = publish_date
    else:
        try:
            date_obj = datetime.fromisoformat(str(publish_date))
        except Exception:
            date_obj = datetime.now()

    date_str = date_obj.strftime("%Y_%m_%d")
    date_dir = os.path.join(news_root, date_str)
    os.makedirs(date_dir, exist_ok=True)

    safe_title = title or "untitled"
    safe_title = re.sub(r"[\\/*?:\"<>|\n\r]+", "_", safe_title).strip()
    if not safe_title:
        safe_title = "untitled"

    filename = f"{date_str}_{safe_title}.txt"
    file_path = os.path.join(date_dir, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"Title: {title}\n")
        f.write(f"URL: {full_link}\n")
        f.write(f"Publish Date: {publish_date}\n\n")
        f.write(text or "")

    return file_path


def _seen_hash(filepath, url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


def load_seen_hashes(file_path):
    if os.path.exists(file_path):
        try:
            with gzip.open(file_path, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return set()
    return set()


def save_seen_hashes(file_path, seen_set):
    tmp = file_path + '.tmp'
    with gzip.open(tmp, 'wb') as f:
        pickle.dump(seen_set, f, protocol=pickle.HIGHEST_PROTOCOL)
    try:
        os.replace(tmp, file_path)
    except Exception:
        try:
            os.remove(file_path)
            os.replace(tmp, file_path)
        except Exception:
            pass


def scrape_udn_latest_stock_news(base_dir=None):
    if base_dir is None:
        base_dir = DEFAULT_BASE_DIR

    chrome_options = Options()
    chrome_options.add_argument('--headless')

    driver = webdriver.Chrome(options=chrome_options)

    target_url = "https://udn.com/news/cate/2/6645"
    logger.info(f"正在前往網頁: {target_url}")
    driver.get(target_url)

    time.sleep(3)

    containers = driver.find_elements(By.CSS_SELECTOR, "div.context-box__content.story-list__holder")
    if not containers:
        logger.warning("找不到任何 context-box__content story-list__holder 容器。")
        driver.quit()
        return

    news_links = []
    for idx, container in enumerate(containers, start=1):
        sub_links = container.find_elements(By.CSS_SELECTOR, "a[href]")
        logger.info(f"第 {idx} 個 container 找到 {len(sub_links)} 個 a[href] 連結")
        news_links.extend(sub_links)

    logger.info(f"總共在所有 target container 找到 {len(news_links)} 個 a[href] 連結。開始進行篩選與爬取...\n")

    seen_file = os.path.join(base_dir, 'seen_links.pkl.gz')
    seen_links = load_seen_hashes(seen_file)
    article_count = 0
    new_added = 0

    for link_element in news_links:
        try:
            href = link_element.get_attribute("href")
            if not href:
                continue
            full_link = urljoin(target_url, href)

            if "news/story" not in full_link:
                continue

            parsed = urlparse(full_link)
            normalized_link = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', '', ''))
            link_hash = _seen_hash(seen_file, normalized_link)
            if link_hash in seen_links:
                continue
            seen_links.add(link_hash)
            new_added += 1

            title_text = link_element.get_attribute("title") or link_element.text
            article_count += 1
            logger.info(f"\n===== 文章 {article_count} =====")
            logger.info(f"標題: {title_text}")
            logger.info(f"網址: {full_link}")

            logger.info("正在使用 Newspaper3k 抓取內文...")
            article = Article(full_link, language='zh')
            article.download()
            article.parse()

            try:
                saved_path = save_article_as_txt(full_link, article.title or title_text, article.publish_date, article.text, base_dir=base_dir)
                logger.info(f"已儲存為: {saved_path}")
            except Exception as e:
                logger.error(f"儲存檔案失敗: {e}")

            logger.info("-" * 50)
            logger.info(f"📰 解析標題: {article.title}")
            logger.info(f"🕒 發布時間: {article.publish_date}")
            logger.info(f"📝 新聞內文 (前 200 字):\n{article.text[:200]}...\n")
            logger.info("-" * 50)

        except Exception as e:
            logger.exception(f"解析該連結時發生錯誤: {e}")
            continue

    driver.quit()

    try:
        if new_added > 0:
            save_seen_hashes(seen_file, seen_links)
            logger.info(f"本輪新增 {new_added} 個連結，已儲存去重資料。")
    except Exception as e:
        logger.exception(f"儲存去重資料時發生錯誤: {e}")

    logger.info("爬蟲任務結束。")
