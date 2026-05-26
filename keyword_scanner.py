import os
import re
from datetime import datetime
from openpyxl import Workbook

DEFAULT_BASE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
KEYWORDS = [
    "營收創新高", "法說會", "轉盈", "毛利率", "產能利用率", "殖利率", "獨家訂單", "獨家供應",
    "砍單", "減產", "認證", "缺貨", "漲價潮", "拉貨動能", "外資買超", "外資反手", "投信作帳",
    "投信鎖碼", "國家隊", "官股進場", "融資爆發", "融資斷頭", "併購", "收購", "實施庫藏股",
    "增資", "減資", "AI伺服器", "液冷", "先進封裝", "CoWoS", "FOPLP", "矽光子", "CPO",
    "低軌衛星", "綠能", "儲能", "面板報價", "記憶體報價"
]

KEYWORD_PATTERN = re.compile(
    r"(" + r"|".join(sorted([re.escape(k) for k in KEYWORDS], key=len, reverse=True)) + r")",
    flags=re.IGNORECASE,
)


def get_news_root(base_dir=None):
    if base_dir is None:
        base_dir = DEFAULT_BASE_DIR
    return os.path.join(base_dir, "News_txts")


def _parse_title_and_company(text, file_path):
    company_name = ""
    title = ""
    for line in text.splitlines():
        if line.startswith("Title:"):
            title = line.split("Title:", 1)[1].strip()
            break
    if not title:
        basename = os.path.basename(file_path)
        title = os.path.splitext(basename)[0]
        if len(title) > 11 and re.match(r"^\d{4}_\d{2}_\d{2}_", title):
            title = title[11:]
    if title:
        company_name = _extract_company_name(title)
    return title, company_name


def _extract_company_name(title):
    if not title:
        return ""
    for sep in ["：", ":", "-", "–", "_", "|"]:
        if sep in title:
            candidate = title.split(sep, 1)[0].strip()
            if candidate:
                return candidate
    return title.strip()


def _normalize_date_from_path(file_path):
    parent_dir = os.path.basename(os.path.dirname(file_path))
    if re.match(r"^\d{4}_\d{2}_\d{2}$", parent_dir):
        return parent_dir
    filename = os.path.splitext(os.path.basename(file_path))[0]
    if len(filename) >= 10 and re.match(r"^\d{4}_\d{2}_\d{2}$", filename[:10]):
        return filename[:10]
    try:
        return datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y_%m_%d")
    except Exception:
        return datetime.now().strftime("%Y_%m_%d")


def scan_txt_file_for_keywords(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return []

    matches = set(m.group(0) for m in KEYWORD_PATTERN.finditer(text))
    if not matches:
        return []

    title, company_name = _parse_title_and_company(text, file_path)
    date_str = _normalize_date_from_path(file_path)
    rows = []
    for keyword in sorted(matches, key=lambda x: KEYWORDS.index(x) if x in KEYWORDS else 999):
        rows.append({
            "date": date_str,
            "file_name": os.path.basename(file_path),
            "keyword": keyword,
            "company_name": company_name,
        })
    return rows


def _collect_txt_files(base_dir=None):
    news_root = get_news_root(base_dir)
    if not os.path.isdir(news_root):
        return []
    txt_files = []
    for root, dirs, files in os.walk(news_root):
        if os.path.basename(root).lower() == "logs":
            continue
        for filename in files:
            if filename.lower().endswith(".txt"):
                txt_files.append(os.path.join(root, filename))
    return txt_files


def _group_rows_by_month(rows):
    groups = {}
    for row in rows:
        month_key = row["date"][:7]
        groups.setdefault(month_key, []).append(row)
    return groups


def _write_excel_for_month(month, rows, output_dir):
    if not rows:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = "關鍵字"
    ws.append(["日期", "新聞txt檔案名稱", "關鍵字", "公司名稱"])
    for row in sorted(rows, key=lambda x: (x["date"], x["file_name"], x["keyword"])):
        ws.append([row["date"], row["file_name"], row["keyword"], row["company_name"]])

    output_path = os.path.join(output_dir, f"keyword_matches_{month}.xlsx")
    wb.save(output_path)
    return output_path


def scan_keywords_and_export_excels(base_dir=None):
    news_root = get_news_root(base_dir)
    os.makedirs(news_root, exist_ok=True)

    txt_files = _collect_txt_files(base_dir)
    all_rows = []
    for file_path in txt_files:
        all_rows.extend(scan_txt_file_for_keywords(file_path))

    grouped = _group_rows_by_month(all_rows)
    output_paths = []
    for month, rows in grouped.items():
        output = _write_excel_for_month(month, rows, news_root)
        if output:
            output_paths.append(output)
    return output_paths
