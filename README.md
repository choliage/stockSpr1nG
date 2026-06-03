**一個歷史系的跟機械系的心血來潮想要科技炒股**

## 功能概覽

- 從 UDN 股市新聞頁面爬取最新股票新聞，並儲存為 TXT 檔案
- 掃描已抓取新聞中的關鍵字，按月輸出 Excel 檔案
- 下載指定公司代號的 MOPS 財報 PDF
- 匯整新聞與財報資訊，產生分析 Excel 報表

## 目錄結構

- `main.py`：主程式入口，提供互動式選單
- `scraper.py`：爬取 UDN 最新股票新聞並儲存為 `.txt`
- `keyword_scanner.py`：掃描新聞檔案並匯出每月關鍵字 Excel
- `financial_report_scraper.py`：下載 MOPS 財報 PDF
- `news_financial_analyzer.py`：產生整合分析報表
- `company_names.json`：公司名稱與代號對照表
- `company_codes.json`：公司代號清單，可用於財報下載或其它流程
- `mongodb_helper.py`：MongoDB 相關協助函數
- `log.py`：日誌設定

## 環境與安裝

建議先建立虛擬環境，然後安裝相依套件：

『`bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

必須安裝 Chrome 或相容的瀏覽器，且 `selenium` 會透過 `webdriver-manager` 取得對應驅動程式。

## 如何使用

在專案根目錄執行：

『`bash
python main.py
```

會出現互動式菜單：

1. 爬取最新 UDN 股票新聞並掃描關鍵字
2. 僅掃描已抓取新聞的關鍵字並輸出 Excel
3. 下載 MOPS 財務報告 PDF
4. 產生新聞與財報整合分析報表
0. 結束程式

### 常用流程

- 若你想完整執行新聞爬蟲與關鍵字分析，選擇 `1`。
- 若已經有新聞檔案，只想重新產生關鍵字 Excel，選擇 `2`。
- 若想單獨下載財報 PDF，選擇 `3`。
- 若要依據現有新聞與財報資料產生分析報表，選擇 `4`。

## 資料位置

程式預設使用使用者桌面(`Desktop`)作為基底路徑，並建立下列檔案夾：

- `News_txts/`：儲存爬取的新聞 TXT
- `Financial_Reports/`：儲存下載的財報 PDF
- `News_Financial_Analysis/`：儲存整合分析 Excel

如果需要，也可以修改程式中 `DEFAULT_BASE_DIR` 變數來變更基底路徑。

## company_names.json 格式說明

`company_names.json` 目前支援兩種格式：

- `code -> name`
- `name -> code`

程式會自動辨識並轉換成內部可使用的對應格式。

## 注意事項

- `newspaper3k` 需要搭配 `lxml[html-clean]`。
- 若要抓取財報，請確認 `company_codes.json` 中已包含目標公司代號。
- 若遭遇網頁結構變動或無法抓取新聞，可能需要調整 `scraper.py` 中的 CSS selector。

## 套件相依

請參考 `requirements.txt`：

- selenium
- webdriver-manager
- requests
- openpyxl
- newspaper3k
- lxml[html-clean]
- pymongo

## 其他說明

若要新增關鍵字，請在 `keyword_scanner.py` 的 `KEYWORDS` 清單中調整。

若要新增公司名稱對照，請編輯 `company_names.json`。