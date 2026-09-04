# AI 產業鏈股票地圖 v2

這是一個可直接部署到 GitHub Pages 的靜態網站。

## 功能
- 產業分類與股票卡片
- 股票代號
- 每日投信買賣超（張）
- 近 5 日 / 20 日投信買賣超
- 投信連買 / 連賣天數
- 依今日 / 5 日 / 20 日買超排序
- GitHub Actions 每個台股交易日 18:30（台灣時間）自動更新

## 部署
1. 在 GitHub 建立一個新的 repository。
2. 把此資料夾內所有檔案與隱藏的 `.github` 資料夾一起上傳。
3. Repository → Settings → Pages。
4. Build and deployment 選 `Deploy from a branch`。
5. Branch 選 `main`、資料夾選 `/ (root)`，按 Save。
6. Repository → Actions → `Update institutional data` → `Run workflow`，先手動跑一次。
7. 幾分鐘後重新整理 GitHub Pages 網址。

## 重要：5日 / 20日
此版本使用官方每日資料並自行累積歷史，所以剛部署時：
- 第一天只有「今日」
- 累積 5 個交易日後，5 日數字才是完整 5 日
- 累積 20 個交易日後，20 日數字才是完整 20 日

這是刻意採用的設計，避免依賴非官方歷史資料 API。

## 資料來源
- TWSE 三大法人買賣超日報（T86）
- TPEx OpenAPI：tpex_3insti_daily_trading

## 注意
官方資料以「股」提供，網站顯示時除以 1,000 轉成「張」。
若股票不是台灣上市/上櫃標的，或沒有有效代號，卡片仍會保留產業資訊，但不顯示投信數字。


## v3 修正：直接雙擊也能開
v3 不再用 `fetch()` 讀取投信資料，而是透過 `<script src="./data/institutional.js">` 載入。
因此：
- GitHub Pages 可以正常使用
- 直接雙擊 `index.html` 也可以讀取已存在的投信資料

但請注意：第一次下載時 `institutional.js` 還沒有真實投信數字。
你必須至少執行一次：
- GitHub → Actions → Update institutional data → Run workflow
或
- 本機執行 `python scripts/update_institutional.py`

更新完成後，`data/institutional.js` 才會包含真實數據。

## 如果 GitHub Actions 沒有數字
請到 GitHub repository：
1. Actions
2. 點 `Update institutional data`
3. Run workflow
4. 等待綠色勾勾
5. 打開 `data/institutional.js`，確認裡面 `"stocks"` 不再是空物件
6. 再重新整理 GitHub Pages 網頁
