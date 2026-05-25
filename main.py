import time
import os
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
import hashlib
import gzip
import pickle
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from newspaper import Article


def save_article_as_txt(full_link, title, publish_date, text, base_dir=None):
    """Save article text into News_txts/YYYY_MM_DD/YYYY_MM_DD_title.txt

    Args:
        full_link (str): article url
        title (str): article title
        publish_date (datetime|str|None): publish date
        text (str): article body
        base_dir (str|None): base path to create News_txts (defaults to script dir)
    Returns:
        str: path to saved file
    """
    if base_dir is None:
        # default to user's Desktop to avoid committing article files into the repo
        base_dir = os.path.join(os.path.expanduser("~"), "Desktop")

    news_root = os.path.join(base_dir, "News_txts")
    os.makedirs(news_root, exist_ok=True)

    # normalize publish_date to datetime
    date_obj = None
    if publish_date is None:
        date_obj = datetime.now()
    elif isinstance(publish_date, datetime):
        date_obj = publish_date
    else:
        # try to parse string-ish publish_date, fallback to now
        try:
            # try common ISO formats
            date_obj = datetime.fromisoformat(str(publish_date))
        except Exception:
            date_obj = datetime.now()

    date_str = date_obj.strftime("%Y_%m_%d")
    date_dir = os.path.join(news_root, date_str)
    os.makedirs(date_dir, exist_ok=True)

    # sanitize title for filename
    safe_title = title or "untitled"
    safe_title = re.sub(r"[\\/*?:\"<>|\n\r]+", "_", safe_title).strip()
    if not safe_title:
        safe_title = "untitled"

    filename = f"{date_str}_{safe_title}.txt"
    file_path = os.path.join(date_dir, filename)

    # write header + content
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
        # best-effort
        try:
            os.remove(file_path)
            os.replace(tmp, file_path)
        except Exception:
            pass


def scrape_udn_latest_stock_news():
    # 1. 設定 Selenium WebDriver
    chrome_options = Options()
    # 如果不想看到瀏覽器視窗彈出，可以取消下方這行的註解
    chrome_options.add_argument('--headless') 
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # 股市最新文章列表網址
    target_url = "https://udn.com/news/cate/2/6645" 
    print(f"正在前往網頁: {target_url}")
    driver.get(target_url)
    
    # 等待網頁與動態內容載入
    time.sleep(3) 

    # 2. 定位目標區域內的新聞連結
    containers = driver.find_elements(By.CSS_SELECTOR, "div.context-box__content.story-list__holder")
    if not containers:
        print("找不到任何 context-box__content story-list__holder 容器。")
        driver.quit()
        return

    news_links = []
    for idx, container in enumerate(containers, start=1):
        # 直接抓取 container 裡的所有 a[href]，不再依賴 h2/h3 等中間容器
        sub_links = container.find_elements(By.CSS_SELECTOR, "a[href]")
        print(f"第 {idx} 個 container 找到 {len(sub_links)} 個 a[href] 連結")
        news_links.extend(sub_links)

    print(f"總共在所有 target container 找到 {len(news_links)} 個 a[href] 連結。開始進行篩選與爬取...\n")
    
    # 3. 逐一處理所有找到的新聞連結
    # load persistent seen set (hashes) to avoid duplicates across runs
    # store seen-links file on user's Desktop to avoid repo contamination
    desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    seen_file = os.path.join(desktop_dir, 'seen_links.pkl.gz')
    seen_links = load_seen_hashes(seen_file)
    article_count = 0
    new_added = 0
    for link_element in news_links:
        try:
            # 取得完整的網址並正規化
            href = link_element.get_attribute("href")
            if not href:
                continue
            full_link = urljoin(target_url, href)

            # 過濾掉可能抓錯的無效連結或非目標文章
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
            print(f"\n===== 文章 {article_count} =====")
            print(f"標題: {title_text}")
            print(f"網址: {full_link}")
            
            # 4. 將網址交給 Newspaper3k 解析內文
            print("正在使用 Newspaper3k 抓取內文...")
            article = Article(full_link, language='zh')
            article.download()
            article.parse()
            
            # 儲存解析到的文章為 txt 檔，並依發布日期分類
            try:
                saved_path = save_article_as_txt(full_link, article.title or title_text, article.publish_date, article.text)
                print(f"已儲存為: {saved_path}")
            except Exception as e:
                print(f"儲存檔案失敗: {e}")
            
            print("-" * 50)
            print(f"📰 解析標題: {article.title}")
            print(f"🕒 發布時間: {article.publish_date}")
            print(f"📝 新聞內文 (前 200 字):\n{article.text[:200]}...\n")
            print("-" * 50)
                
        except Exception as e:
            # 避免單一元素解析失敗導致整個程式崩潰
            print(f"解析該連結時發生錯誤: {e}")
            continue

    # 5. 關閉瀏覽器
    driver.quit()

    # persist seen set only once per run to minimize disk writes
    try:
        if new_added > 0:
            save_seen_hashes(seen_file, seen_links)
            print(f"本輪新增 {new_added} 個連結，已儲存去重資料。")
    except Exception as e:
        print(f"儲存去重資料時發生錯誤: {e}")

    print("爬蟲任務結束。")

if __name__ == "__main__":
    try:
        while True:
            scrape_udn_latest_stock_news()
            print("本輪爬取完成，等待 90 分鐘後再次執行...")
            time.sleep(90 * 60)
    except KeyboardInterrupt:
        print("收到中斷 (KeyboardInterrupt)，程式結束。")