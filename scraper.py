import gzip
import hashlib
import os
import pickle
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

from newspaper import Article
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

STOCK_KEYWORDS = (
    "台股", "美股", "陸股", "港股", "日股", "股市", "股價", "股東", "股東會", "股票",
    "證券", "上市", "上櫃", "興櫃", "掛牌", "IPO", "ADR", "TDR",
    "大盤", "加權", "指數", "行情", "盤勢", "盤中", "收盤", "開盤", "成交量",
    "漲停", "跌停", "漲幅", "跌幅", "飆漲", "大漲", "重挫", "拉回", "反彈",
    "多頭", "空頭", "買盤", "賣壓", "外資", "投信", "自營商", "三大法人", "融資", "融券",
    "法人", "券商", "分析師", "本益比", "殖利率", "配息", "除息", "股息", "股利",
    "ETF", "ETN", "基金", "權證", "期貨", "選擇權", "台指期",
    "市值", "財報", "營收", "獲利", "EPS", "毛利率", "展望", "訂單", "報價",
    "AI股", "半導體", "記憶體", "晶片", "台積電", "聯發科", "鴻海", "輝達", "NVIDIA", "散熱", "封裝",
    "力積電", "聯電", "華邦電", "南亞科", "中華電", "台達電", "群創", "奇鋐", "京元電子",
    "FOPLP",
)

NON_STOCK_KEYWORDS = (
    "遺產", "遺產稅", "罰鍰", "大雷雨", "冰雹", "豪車", "登山口", "醫師公會",
    "停車場", "YouBike", "兒童節", "雲霄飛車", "偷拍", "軍費", "入境", "疫情", "馬英九基金會",
)

SOURCES = {
    "udn": {
        "name": "聯合報",
        "list_url": "https://udn.com/rank/newest/2/6645/1",
        "folder": os.path.join("News_txts", "UDN"),
        "seen_file": "seen_links_udn.pkl.gz",
        "link_selector": 'a[href*="/news/story/"]',
        "path_pattern": r"/news/story/\d+/\d+",
        "wait_min_links": 5,
    },
    "ctee": {
        "name": "工商時報",
        "list_url": "https://www.ctee.com.tw/livenews/stock",
        "folder": os.path.join("News_txts", "CTEE"),
        "seen_file": "seen_links_ctee.pkl.gz",
        "link_selector": 'a[href*="/news/"]',
        "path_pattern": r"/news/\d+-\d+",
        "wait_min_links": 5,
    },
    "money_udn": {
        "name": "經濟日報",
        "list_url": "https://money.udn.com/rank/newest/1001/5590/1",
        "folder": os.path.join("News_txts", "MoneyUDN"),
        "seen_file": "seen_links_money_udn.pkl.gz",
        "link_selector": 'a[href*="/money/story/"]',
        "path_pattern": r"/money/story/\d+/\d+",
        "wait_min_links": 5,
    },
    "ltn": {
        "name": "自由時報",
        "list_url": "https://ec.ltn.com.tw/list/securities",
        "folder": os.path.join("News_txts", "LTN"),
        "seen_file": "seen_links_ltn.pkl.gz",
        "link_selector": 'a[href*="/article/breakingnews/"]',
        "path_pattern": r"/article/breakingnews/\d+",
        "wait_min_links": 1,
        "scroll_rounds": 2,
    },
    "wallstreetcn": {
        "name": "華爾街見聞",
        "list_url": "https://wallstreetcn.com/news/global",
        "folder": os.path.join("News_txts", "WallStreetCN"),
        "seen_file": "seen_links_wallstreetcn.pkl.gz",
        "link_selector": 'a[href*="/articles/"]',
        "path_pattern": r"/articles/\d+",
        "skip_path_prefixes": ("/member/articles/",),
        "skip_title_keywords": ("清朗", "举报专区", "举报公告", "违规内容专项整治"),
        "wait_min_links": 5,
    },
}

ACTIVE_SOURCES = ["udn", "ctee", "money_udn", "ltn"]
RUN_INTERVAL_SECONDS = 90 * 60
DEFAULT_BASE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")


def _log(logger, level, message):
    if logger:
        getattr(logger, level)(message)
    else:
        print(message)


def make_chrome_options():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument(f"user-agent={USER_AGENT}")
    return options


def save_article_as_txt(full_link, title, publish_date, text, base_dir=None, source_folder=None):
    if base_dir is None:
        base_dir = DEFAULT_BASE_DIR

    if source_folder:
        news_root = os.path.join(base_dir, source_folder)
    else:
        news_root = os.path.join(base_dir, "News_txts")

    os.makedirs(news_root, exist_ok=True)

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

    safe_title = re.sub(r"[\\/*?:\"<>|\n\r]+", "_", title or "untitled").strip()
    safe_title = (safe_title[:80].rstrip(" ._") or "untitled")
    link_hash = hashlib.sha256(full_link.encode("utf-8")).hexdigest()[:8]
    file_path = os.path.join(date_dir, f"{date_str}_{safe_title}_{link_hash}.txt")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"Title: {title}\n")
        f.write(f"URL: {full_link}\n")
        f.write(f"Publish Date: {publish_date}\n\n")
        f.write(text or "")

    return file_path


def seen_hash(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def load_seen_hashes(file_path):
    if os.path.exists(file_path):
        try:
            with gzip.open(file_path, "rb") as f:
                return pickle.load(f)
        except Exception:
            return set()
    return set()


def save_seen_hashes(file_path, seen_set):
    tmp = file_path + ".tmp"
    with gzip.open(tmp, "wb") as f:
        pickle.dump(seen_set, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, file_path)


def normalize_article_url(url):
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def should_keep_link(source, url, title):
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    title = title or ""

    for prefix in source.get("skip_path_prefixes", ()): 
        if path.startswith(prefix):
            return False

    for keyword in source.get("skip_title_keywords", ()): 
        if keyword in title:
            return False

    if re.fullmatch(source["path_pattern"], path) is None:
        return False

    if source.get("stock_filter", True):
        if any(keyword in title for keyword in NON_STOCK_KEYWORDS):
            return False
        return any(keyword in title for keyword in STOCK_KEYWORDS)

    return True


def wait_for_links(driver, source):
    selector = source["link_selector"]
    min_links = source.get("wait_min_links", 1)
    WebDriverWait(driver, 20).until(
        lambda browser: len(browser.find_elements(By.CSS_SELECTOR, selector)) >= min_links
    )


def collect_article_links(driver, source):
    driver.get(source["list_url"])
    wait_for_links(driver, source)

    for _ in range(source.get("scroll_rounds", 0)):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

    items = []
    seen_urls = set()
    for link_element in driver.find_elements(By.CSS_SELECTOR, source["link_selector"]):
        href = link_element.get_attribute("href")
        if not href:
            continue

        full_link = normalize_article_url(urljoin(source["list_url"], href))
        title_text = (link_element.get_attribute("title") or link_element.text or "").strip()
        if full_link in seen_urls or not should_keep_link(source, full_link, title_text):
            continue

        seen_urls.add(full_link)
        items.append((full_link, title_text))

    return items


def parse_article(url):
    article = Article(
        url,
        language="zh",
        browser_user_agent=USER_AGENT,
        request_timeout=15,
    )
    article.download()
    article.parse()
    if not (article.text or "").strip():
        raise ValueError("Newspaper3k 未解析到文章內文")
    return article


def clean_article_text(text):
    noise_lines = {
        "已將目前網頁的網址複製到您的剪貼簿！",
    }
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped in noise_lines:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def scrape_source(source_key, limit=None, base_dir=None, logger=None):
    if logger is None:
        logger = None

    source = SOURCES[source_key]
    desktop_dir = base_dir or DEFAULT_BASE_DIR
    seen_file = os.path.join(desktop_dir, source["seen_file"])
    seen_links = load_seen_hashes(seen_file)

    candidate_count = 0
    duplicate_count = 0
    new_added = 0
    failed_count = 0

    _log(logger, "info", f"\n========== {source['name']} ==========")
    _log(logger, "info", f"正在前往新聞列表: {source['list_url']}")

    driver = webdriver.Chrome(options=make_chrome_options())
    try:
        try:
            news_items = collect_article_links(driver, source)
        except TimeoutException:
            _log(logger, "error", f"等待 {source['name']} 文章列表逾時，請確認網站結構或網路狀態。")
            return
    finally:
        driver.quit()

    _log(logger, "info", f"找到 {len(news_items)} 個有效文章連結，開始篩選與爬取...\n")

    for full_link, title_text in news_items:
        if limit is not None and new_added >= limit:
            break

        candidate_count += 1
        link_hash = seen_hash(full_link)
        if link_hash in seen_links:
            duplicate_count += 1
            continue

        try:
            _log(logger, "info", f"===== {source['name']}文章 {new_added + 1} =====")
            _log(logger, "info", f"標題: {title_text}")
            _log(logger, "info", f"網址: {full_link}")
            _log(logger, "info", "正在使用 Newspaper3k 抓取內文...")

            article = parse_article(full_link)
            article_text = clean_article_text(article.text)
            saved_path = save_article_as_txt(
                full_link,
                article.title or title_text,
                article.publish_date,
                article_text,
                base_dir=desktop_dir,
                source_folder=source["folder"],
            )

            seen_links.add(link_hash)
            new_added += 1
            _log(logger, "info", f"已儲存為: {saved_path}")
            _log(logger, "info", f"解析標題: {article.title}")
            _log(logger, "info", f"發布時間: {article.publish_date}")
            _log(logger, "info", f"新聞內文前 200 字:\n{article_text[:200]}...\n")
        except Exception as e:
            failed_count += 1
            _log(logger, "error", f"解析該連結時發生錯誤: {e}")
        _log(logger, "info", "-" * 50)

    if new_added > 0:
        try:
            save_seen_hashes(seen_file, seen_links)
            _log(logger, "info", f"本輪新增 {new_added} 個 {source['name']} 連結，已儲存去重資料。")
        except Exception as e:
            _log(logger, "error", f"儲存 {source['name']} 去重資料時發生錯誤: {e}")

    _log(logger, "info", f"\n{source['name']}本輪統計：")
    _log(logger, "info", f"- 文章候選連結：{candidate_count}")
    _log(logger, "info", f"- 已爬過而跳過：{duplicate_count}")
    _log(logger, "info", f"- 新增儲存文章：{new_added}")
    _log(logger, "info", f"- 解析或儲存失敗：{failed_count}")
    _log(logger, "info", f"- 文章儲存位置：{os.path.join(desktop_dir, source['folder'])}")


def scrape_active_sources(limit_per_source=None, base_dir=None, logger=None):
    for source_key in ACTIVE_SOURCES:
        if source_key not in SOURCES:
            _log(logger, "warning", f"略過未知來源: {source_key}")
            continue
        scrape_source(source_key, limit=limit_per_source, base_dir=base_dir, logger=logger)
