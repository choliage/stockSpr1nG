#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import shutil
import logging
import sys
import random
import threading
import json
from datetime import datetime
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple, Dict, List

import requests

from selenium.webdriver.chrome.webdriver import WebDriver as Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    NoSuchWindowException,
)
from webdriver_manager.chrome import ChromeDriverManager

from mongodb_helper import MongoDBHelper


# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [Thread-%(threadName)s] - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scraper_selenium.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    except Exception:
        pass


# ---------------------------
# 全域限流（跨執行緒共享）
# ---------------------------
class RateLimiter:
    def __init__(self, qps: float = 0.25):
        self._lock = threading.Lock()
        self._min_interval = 1.0 / max(qps, 1e-6)
        self._next_time = time.monotonic()

    def acquire(self, extra_delay_range: Tuple[float, float] = (0.2, 0.9)) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_time:
                time.sleep(self._next_time - now)
            jitter = random.uniform(*extra_delay_range)
            self._next_time = time.monotonic() + self._min_interval + jitter


@dataclass
class BackoffPolicy:
    base_seconds: float = 40.0
    max_seconds: float = 10 * 60.0
    jitter_ratio: float = 0.25

    def compute(self, attempt: int) -> float:
        raw = min(self.base_seconds * (2 ** attempt), self.max_seconds)
        jitter = raw * self.jitter_ratio
        return max(1.0, raw + random.uniform(-jitter, jitter))


class FinancialReportScraper:
    """
    Selenium：只負責進 step=1 -> 點進細節頁 -> 取得最終 PDF URL + cookies
    requests：真正下載 PDF（可檢查 Content-Type / header / size）
    """

    # 你提供的 selector：<font color="red">查無所需資料</font>
    NO_DATA_SELECTOR = "body > center > h4 > font"

    def __init__(
        self,
        download_base_dir: str = "data/reports",
        max_workers: int = 1,
        qps: float = 0.25,
        headless: bool = True,
        request_timeout: int = 60,
        recent_years: int = 3,  # ✅ 只抓最近三年
        start_roc_year_floor: int = 1,
        bootstrap_old_years: bool = True,  # ✅ 開啟舊年初始化模式
        bootstrap_start_gregorian_year: Optional[int] = 2014,
        bootstrap_end_gregorian_year: Optional[int] = 2023,
        company_codes: Optional[List[str]] = None,
        mongo_uri: Optional[str] = None,
        mongo_db: Optional[str] = None,
        company_codes_path: Optional[str] = None,
    ):
        self.download_base_dir = os.path.abspath(download_base_dir)
        os.makedirs(self.download_base_dir, exist_ok=True)

        self.max_workers = max_workers
        self.db_helper = MongoDBHelper(
            mongo_uri=mongo_uri,
            mongo_db=mongo_db,
            company_codes_path=company_codes_path,
        )
        self.collection = self.db_helper.db["financial_reports"]
        if company_codes is not None:
            self.valid_company_codes = sorted({str(code).strip() for code in company_codes if code})
        else:
            self.valid_company_codes = sorted(list(self.db_helper.get_all_company_codes()))

        self.driver_path = str(ChromeDriverManager().install())
        self.rate_limiter = RateLimiter(qps=qps)
        self.backoff = BackoffPolicy()

        self.headless = headless
        self.request_timeout = request_timeout
        self.recent_years = max(1, int(recent_years))
        self.start_roc_year_floor = max(1, int(start_roc_year_floor))

        self.bootstrap_old_years = bootstrap_old_years
        self.bootstrap_start_gregorian_year = bootstrap_start_gregorian_year
        self.bootstrap_end_gregorian_year = bootstrap_end_gregorian_year
        self.session = requests.Session()

        # ✅ 新增：中斷續傳紀錄檔
        self.checkpoint_file = os.path.join(os.path.dirname(self.download_base_dir), "scraper_checkpoint.txt")

    # ✅ 新增：一次性撈取本地檔案清單 (O(1) 查詢用)
    def _get_local_files_set(self, company_code: str) -> set:
        d = self._company_dir(company_code)
        try:
            return set(os.listdir(d))
        except Exception:
            return set()

    def _in_bootstrap_old_year_range(self, gregorian_year: int, is_recent_year: bool) -> bool:
        """
        只有在：
        1) 開啟 bootstrap_old_years
        2) 該年不屬於最近四年
        3) 落在指定初始化舊年份區間
        時，才回傳 True
        """
        if not self.bootstrap_old_years:
             return False

        if is_recent_year:
            return False

        if self.bootstrap_start_gregorian_year is None or self.bootstrap_end_gregorian_year is None:
            return False

        return self.bootstrap_start_gregorian_year <= gregorian_year <= self.bootstrap_end_gregorian_year

    # ---------------------------
    # UA / Driver
    # ---------------------------
    def _get_random_ua(self) -> str:
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
        ]
        return random.choice(uas)

    def _make_driver(self, ua: str) -> Chrome:
        options = Options()
        options.page_load_strategy = "eager"
        options.add_argument(f"--user-agent={ua}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--window-size=1920,1080")

        if self.headless:
            options.add_argument("--headless=new")

        service = Service(executable_path=self.driver_path)
        driver = Chrome(service=service, options=options)

        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'},
        )
        driver.set_page_load_timeout(35)
        return driver

    # ---------------------------
    # 年度策略：最近3年 + 舊年依 DB 缺口
    # ---------------------------
    def _recent_year_range(self) -> Tuple[int, int]:
        """
        回傳 (start_gregorian_year, end_gregorian_year) for recent window.
        例如今年 2026、recent_years=3 => 2024~2026
        """
        now = datetime.now()
        end_y = now.year
        start_y = end_y - (self.recent_years - 1)
        return start_y, end_y

    def _should_query_season_by_month(self, roc_year: int, season: int) -> bool:
        """
        依月份推算該季是否應該已公告（只針對「今年」）。
        你可視需要微調 deadline（我刻意放寬幾天避免誤判）。
        """
        now = datetime.now()
        current_roc = now.year - 1911
        if roc_year != current_roc:
            return True  # 非今年不做月份 gate

        gregorian_year = roc_year + 1911
        deadlines = {
            1: datetime(gregorian_year, 5, 20),      # Q1
            2: datetime(gregorian_year, 8, 20),      # Q2
            3: datetime(gregorian_year, 11, 20),     # Q3
            4: datetime(gregorian_year + 1, 3, 31),  # Q4（次年）
        }
        dl = deadlines.get(season)
        return True if dl is None else (now >= dl)

    # ---------------------------
    # 無資料 / 查詢過量判斷
    # ---------------------------
    def _is_rate_limited(self, page_source: str) -> bool:
        return ("查詢過量" in page_source) or ("下載過量" in page_source)

    def _has_no_data_message(self, driver: Chrome) -> bool:
        try:
            text = driver.execute_script(
                """
                const el = document.querySelector(arguments[0]);
                return el ? (el.textContent || '').trim() : '';
                """,
                self.NO_DATA_SELECTOR,
            )
            return text == "查無所需資料"
        except Exception:
            return False

    # ---------------------------
    # 本地檔案 / DB 查詢
    # ---------------------------
    def _company_dir(self, company_code: str) -> str:
        d = os.path.join(self.download_base_dir, str(company_code))
        os.makedirs(d, exist_ok=True)
        return d

    def _expected_filename(self, gregorian_year: int, season: int, company_code: str, report_type: str) -> str:
        season_str = f"0{season}"
        return f"{gregorian_year}{season_str}_{company_code}_{report_type}.pdf"

    def _file_exists(self, company_code: str, gregorian_year: int, season: int, report_type: str) -> bool:
        path = os.path.join(self._company_dir(company_code), self._expected_filename(gregorian_year, season, company_code, report_type))
        return os.path.exists(path)

    def _db_has_record(self, company_code: str, gregorian_year: int, season: int) -> bool:
        """
        DB 是否已存在該公司/年/季 任一類型的紀錄（合併/個體皆算）。
        用於「舊年度：依 DB 判斷缺口」策略。
        """
        q = {"公司代號": str(company_code), "年度": int(gregorian_year), "季別": int(season)}
        return self.collection.count_documents(q, limit=1) > 0

    def _db_records_for_season(self, company_code: str, gregorian_year: int, season: int) -> List[dict]:
        q = {"公司代號": str(company_code), "年度": int(gregorian_year), "季別": int(season)}
        return list(self.collection.find(q, {"類型": 1, "本地路徑": 1}))

    def _should_attempt_old_year(self, company_code: str, gregorian_year: int, season: int) -> bool:
        """
        舊年度（不在最近四年）：只依 DB 判斷缺口
        - DB 沒紀錄：不查、不打站
        - DB 有紀錄但檔案不存在：補抓（視為缺口）
        - DB 有紀錄且檔案存在：跳過
        """
        if not self._db_has_record(company_code, gregorian_year, season):
            return False

        recs = self._db_records_for_season(company_code, gregorian_year, season)
        # 若 DB 有紀錄，但對應本地路徑檔案不存在，才補抓
        for r in recs:
            rtype = (r.get("類型") or "").strip()
            if rtype in ("合併財報", "個體財報"):
                expected = os.path.join(self._company_dir(company_code), self._expected_filename(gregorian_year, season, company_code, rtype))
                if not os.path.exists(expected):
                    return True
        return False

    # ---------------------------
    # 找報告連結（AI1/AI2）
    # ---------------------------
    def _find_report_link(
        self,
        driver: Chrome,
        prefer_ai: str,
        season: int,
        season_str: str,
    ) -> Optional[Tuple[WebElement, str]]:
        report_type = "合併財報" if prefer_ai == "AI1" else "個體財報"
        try:
            candidates = driver.find_elements(By.XPATH, f"//a[contains(@href,'{prefer_ai}')]")
        except Exception:
            candidates = []

        for a in candidates:
            href = a.get_attribute("href") or ""
            text = (a.text or "").strip()
            if (season_str in href) or (f"第{season}季" in text) or (f"{season}季" in text):
                return a, report_type

        for a in candidates:
            text = (a.text or "").strip()
            if (f"第{season}季" in text) or (f"{season}季" in text):
                return a, report_type

        return None

    # ---------------------------
    # Selenium cookies -> requests
    # ---------------------------
    def _driver_cookies_to_dict(self, driver: Chrome) -> Dict[str, str]:
        cookies = {}
        for c in driver.get_cookies():
            n = c.get("name")
            v = c.get("value")
            if n and v:
                cookies[n] = v
        return cookies

    def _download_pdf_via_requests(
        self,
        pdf_url: str,
        cookies: Dict[str, str],
        user_agent: str,
        out_path: str,
        referer: Optional[str] = None,
    ) -> None:
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer

        self.session.cookies.clear()
        self.session.cookies.update(cookies)
        r = self.session.get(pdf_url, headers=headers, timeout=self.request_timeout, stream=True, allow_redirects=True)
        r.raise_for_status()

        ctype = (r.headers.get("Content-Type") or "").lower()
        if ("pdf" not in ctype) and ("octet-stream" not in ctype):
            raise ValueError(f"Non-PDF content-type: {ctype[:80]}")

        tmp_path = out_path + ".part"
        total = 0
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                total += len(chunk)

        if total < 1024:
            raise ValueError(f"Downloaded file too small: {total} bytes")

        with open(tmp_path, "rb") as f:
            head = f.read(5)
        if head != b"%PDF-":
            raise ValueError("Downloaded content is not a PDF (missing %PDF-)")

        os.replace(tmp_path, out_path)

    # ---------------------------
    # DB 寫入（符合 unique index：公司代號+年度+季別+類型）
    # ---------------------------
    def _update_db(self, code: str, gregorian_year: int, season: int, r_type: str, path: str) -> None:
        record = {
            "公司代號": str(code),
            "年度": int(gregorian_year),       # ✅ 重要：對齊你的 unique index
            "西元年度": int(gregorian_year),   # 可選：保留相容欄位
            "季別": int(season),
            "類型": str(r_type),
            "本地路徑": os.path.abspath(path),
            "更新時間": datetime.now(),
            "已解析": False,
        }
        self.collection.update_one(
            {"公司代號": record["公司代號"], "年度": record["年度"], "季別": record["季別"], "類型": record["類型"]},
            {"$set": record},
            upsert=True,
        )

    # ---------------------------
    # 主流程：單公司
    # ---------------------------
    def process_company(self, company_code: str) -> str: # ✅ 優化：回傳代號供 checkpoint 紀錄
        ua = self._get_random_ua()
        driver: Optional[Chrome] = None

        try:
            # ✅ 優化：預先取得本地已存在的檔案清單 (Filename-First)
            local_files = self._get_local_files_set(company_code)

            recent_start_g, recent_end_g = self._recent_year_range()
            current_roc_year = datetime.now().year - 1911
            roc_start = max(self.start_roc_year_floor, current_roc_year - 30)  
            roc_end = current_roc_year  

            for roc_year in range(roc_start, roc_end + 1):
                gregorian_year = roc_year + 1911
                is_recent_year = (recent_start_g <= gregorian_year <= recent_end_g)

                for season in range(1, 5):
                    season_str = f"0{season}"

                    # ✅ 優化：檔名優先檢查，存在即直接跳過該季，完全不啟動瀏覽器
                    fn_ai1 = self._expected_filename(gregorian_year, season, company_code, "合併財報")
                    fn_ai2 = self._expected_filename(gregorian_year, season, company_code, "個體財報")
                    if fn_ai1 in local_files or fn_ai2 in local_files:
                        continue

                    if not self._should_query_season_by_month(roc_year, season):
                        logger.info(f"   ⏭ [{company_code}-{gregorian_year} Q{season}] 尚未到合理公告時間，跳過")
                        continue

                    if not is_recent_year:
                        if self._in_bootstrap_old_year_range(gregorian_year, is_recent_year):
                             logger.info(
                                  f"   🚀 [{company_code}-{gregorian_year} Q{season}] 舊年份初始化模式啟用，允許首次抓取"
                           )
                        else:
                            if not self._should_attempt_old_year(company_code, gregorian_year, season):
                                continue
                            else:
                                logger.info(
                                    f"   🔧 [{company_code}-{gregorian_year} Q{season}] 舊年度依 DB 判定缺口，開始補抓"
                             )

                    # ✅ 優化：延遲啟動瀏覽器 (Lazy Initialization)
                    if driver is None:
                        logger.info(f"🚀 偵測到檔案缺漏，啟動瀏覽器處理公司: {company_code}")
                        driver = self._make_driver(ua=ua)

                    url = (
                        "https://doc.twse.com.tw/server-java/t57sb01"
                        f"?step=1&co_id={company_code}&year={roc_year}&seamon={season}&mtype=A"
                    )

                    max_retries = 4
                    for attempt in range(max_retries):
                        main_window: Optional[str] = None
                        new_window: Optional[str] = None

                        try:
                            self.rate_limiter.acquire(extra_delay_range=(0.2, 1.0))

                            driver.get(url)
                            WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

                            if self._is_rate_limited(driver.page_source):
                                sleep_s = self.backoff.compute(attempt)
                                logger.warning(f"⛔ [{company_code}] 查詢過量，退避 {sleep_s:.1f}s (attempt {attempt+1}/{max_retries})")
                                time.sleep(sleep_s)
                                continue

                            if self._has_no_data_message(driver):
                                logger.info(f"   ⏭ [{company_code}-{gregorian_year} Q{season}] 查無所需資料，跳過")
                                break

                            WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "a")))

                            found = self._find_report_link(driver, "AI1", season, season_str) \
                                or self._find_report_link(driver, "AI2", season, season_str)

                            if not found:
                                logger.info(f"   ⏭ [{company_code}-{gregorian_year} Q{season}] 查無 AI1/AI2 連結，視為無檔案，跳過")
                                break

                            target_link, report_type = found

                            out_dir = self._company_dir(company_code)
                            out_name = self._expected_filename(gregorian_year, season, company_code, report_type)
                            out_path = os.path.join(out_dir, out_name)
                            if os.path.exists(out_path):
                                break

                            main_window = driver.current_window_handle
                            before_handles = set(driver.window_handles)

                            target_link.click()

                            WebDriverWait(driver, 12).until(lambda d: len(d.window_handles) > len(before_handles))
                            after_handles = set(driver.window_handles)
                            diff = list(after_handles - before_handles)
                            if not diff:
                                if self._has_no_data_message(driver):
                                    logger.info(f"   ⏭ [{company_code}-{gregorian_year} Q{season}] 點擊後顯示無資料，跳過")
                                    break
                                raise TimeoutException("未偵測到新視窗")

                            new_window = diff[0]
                            if new_window not in driver.window_handles:
                                raise NoSuchWindowException("新視窗 handle 不存在")

                            driver.switch_to.window(new_window)

                            a_btn = WebDriverWait(driver, 12).until(
                                EC.presence_of_element_located((By.TAG_NAME, "a"))
                            )
                            pdf_url = (a_btn.get_attribute("href") or "").strip()

                            if not pdf_url.lower().startswith("http"):
                                pdf_url = driver.current_url

                            if not pdf_url.lower().startswith("http"):
                                raise ValueError(f"Invalid pdf_url: {pdf_url[:120]}")

                            cookies = self._driver_cookies_to_dict(driver)
                            referer = driver.current_url

                            self._download_pdf_via_requests(
                                pdf_url=pdf_url,
                                cookies=cookies,
                                user_agent=ua,      
                                out_path=out_path,
                                referer=referer,
                            )

                            logger.info(f"   💾 [{company_code}-{gregorian_year} Q{season}] 下載成功(requests) -> {out_name}")
                            self._update_db(company_code, gregorian_year, season, report_type, out_path)

                            break  

                        except (TimeoutException, WebDriverException, NoSuchWindowException, requests.RequestException, ValueError) as e:
                            try:
                                if self._has_no_data_message(driver):
                                    logger.info(f"   ⏭ [{company_code}-{gregorian_year} Q{season}] 無資料（例外路徑），跳過：{e}")
                                    break
                            except Exception:
                                pass

                            msg = str(e).lower()
                            transient = any(k in msg for k in [
                                "too many queries", "查詢過量",
                                "timeout", "下載過量", "time out", 
                                "disconnected", "connection reset",
                                "invalid session",
                            ]) or (driver is not None and self._is_rate_limited(getattr(driver, "page_source", "")))

                            if transient and attempt < max_retries - 1:
                                sleep_s = self.backoff.compute(attempt)
                                logger.warning(
                                    f"   ✗ [{company_code}-{gregorian_year} Q{season}] attempt {attempt+1}/{max_retries} transient 失敗：{e}；退避 {sleep_s:.1f}s"
                                )
                                time.sleep(sleep_s)
                                continue

                            logger.info(f"   ⏭ [{company_code}-{gregorian_year} Q{season}] 放棄該季：{e}")
                            break

                        finally:
                            if driver:
                                try:
                                    handles = driver.window_handles
                                    if new_window is not None and new_window in handles:
                                        driver.switch_to.window(new_window)
                                        driver.close()
                                    handles = driver.window_handles
                                    if main_window is not None and main_window in handles:
                                        driver.switch_to.window(main_window)
                                except Exception:
                                    pass
            return company_code # ✅ 回傳給 run_parallel 寫入 checkpoint

        except Exception as e:
            logger.error(f"🔥 公司 {company_code} 執行緒異常: {e}")
            return company_code
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    # ---------------------------
    # 多公司
    # ---------------------------
    def run_parallel(self, start_code: Optional[str] = None, end_code: Optional[str] = None, resume: bool = True) -> None:
        targets = self.valid_company_codes
        
        # ✅ 優化：中斷續傳過濾
        if resume and not start_code and os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r") as f:
                    last_done = f.read().strip()
                if last_done in targets:
                    targets = [c for c in targets if c > last_done]
                    if targets:
                        logger.info(f"⏭ 偵測到上次進度，從 Checkpoint 接續執行，起始公司: {targets[0]}")
            except Exception as e:
                logger.error(f"讀取 checkpoint 失敗: {e}")

        if start_code and end_code:
            targets = [c for c in targets if start_code <= c <= end_code]

        if not targets:
            logger.warning("⚠ 找不到符合條件的公司清單！")
            return

        recent_start_g, recent_end_g = self._recent_year_range()
        logger.info("=" * 60)
        logger.info(f"⚡ requests 下載版 | Workers: {self.max_workers} | Headless: {self.headless}")
        logger.info(f"🏢 預計處理公司數: {len(targets)} 家")
        if start_code:
            logger.info(f"🎯 範圍: {start_code} ~ {end_code}")
        logger.info(f"🧭 最近年度窗口（西元）：{recent_start_g} ~ {recent_end_g}（只抓最近四年）")
        logger.info("🧩 舊年度策略：僅依 DB 判定缺口（DB 無紀錄即不掃）")
        logger.info("📅 今年季報：依月份 gate 未到公告期直接跳過")
        logger.info("=" * 60)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self.process_company, code) for code in targets]
            for f in as_completed(futures):
                try:
                    # ✅ 優化：即時寫入 checkpoint
                    res_code = f.result()
                    if res_code:
                        with open(self.checkpoint_file, "w") as cp:
                            cp.write(str(res_code))
                except Exception as e:
                    logger.error(f"執行緒錯誤: {e}")

    def close(self) -> None:
        try:
            if self.session:
                self.session.close()
        except Exception:
            pass

        if self.db_helper:
            self.db_helper.close()


if __name__ == "__main__":
    print("\n=================================================")
    print("  MOPS 財務報告書 (PDF) - Selenium 取連結 + requests 下載版")
    print("  ✅ 只抓最近四年，其餘依 DB 缺口")
    print("  ✅ 今年季報依月份 gate")
    print("=================================================")
    print("請選擇爬取模式:")
    print("1. 全部爬取 (所有上市上櫃公司)")
    print("2. 指定範圍 (輸入起始和最後公司代號)")

    choice = input("\n請輸入選項 (1/2): ").strip()

    scraper = FinancialReportScraper(
        max_workers=1,
        qps=0.25,
        headless=True,
        request_timeout=60,
        recent_years=3,           # ✅ 最近四年
        start_roc_year_floor=1,   # 也可改讓外圈迴圈更短
    )

    try:
        if choice == "1":
            scraper.run_parallel()
        elif choice == "2":
            start_c = input("請輸入起始公司代號 (例: 1101): ").strip()
            end_c = input("請輸入最後公司代號 (例: 2330): ").strip()
            if start_c > end_c:
                start_c, end_c = end_c, start_c
            scraper.run_parallel(start_code=start_c, end_code=end_c)
        else:
            print("無效的選項，程式結束。")
    except KeyboardInterrupt:
        print("\n使用者強制中斷")
    finally:
        scraper.close()