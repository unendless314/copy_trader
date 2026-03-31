# MVP 後續待辦：觀測性與 SQLite Schema

## 目的

本文件記錄目前 MVP 階段已確認、但可暫時接受的觀測性 / SQLite schema 限制。

這些項目不代表程式目前不能用；多數屬於：

- 觀測資料不夠精確
- schema 語意與實際用途有落差
- 後續若要做精確對帳、P&L、成交追蹤時需要補強

目前策略仍以「輪詢來源倉位 + 輪詢 Binance 實際倉位 + 發現差額即補單」為主，
SQLite 僅作為觀測與事後排查用途，不作為交易真相來源。

## 目前架構定位

- 主交易邏輯依賴每輪直接讀取 Binance 實際倉位
- SQLite 不參與交易決策
- `reconciliation_decisions` 與 `execution_results` 主要用於事後排查
- 目前設計重點是簡單、可維護、可收斂，不是逐筆成交核帳

## 已知問題與限制

### 1. `execution_results` 不是精確成交帳本

目前 `execution_results` 比較接近「送單結果紀錄」，不是「最終成交紀錄」。

現況：

- `status` 代表下單回應狀態，不一定是最終成交狀態
- `submitted_size` 代表送單 quantity，不代表最終 executed quantity
- 缺少 `executed_qty`
- 缺少 `avg_price`
- 缺少 `fee`
- 缺少 `final_status`
- 缺少 `client_order_id`

影響：

- 不適合直接拿來做精確 P&L
- 不適合直接拿來做逐筆成交對帳
- 在極少數部分成交情況下，累計 `submitted_size` 可能大於真實成交量

目前風險評估：

- 對小資金、單一高流動性標的、使用市價單的場景，通常可接受
- 若未來放大單量、擴展到低流動性標的，需優先補強

### 2. `source_snapshots` 缺少 `cycle_id`

目前 `source_snapshots` 雖會寫入，但缺少 `cycle_id`，不利於和同一輪的
`reconciliation_decisions` 或 `execution_results` 精準關聯。

現況：

- 能保留來源持倉快照
- 但不容易還原「某一輪決策當下看到的完整來源狀態」
- 若某 symbol 當輪沒有來源倉位，通常不會有 row

影響：

- 事後排查時，難以精準對齊同一輪資料
- 對單標的 MVP 價值有限，但多標的時會逐漸不夠用

### 3. `binance_positions` 缺少 `cycle_id` 與上下文

目前 `binance_positions` 只是持倉快照，缺少足夠上下文來和決策、執行結果做完整還原。

現況：

- 缺少 `cycle_id`
- 缺少 `runtime_mode`
- 缺少「這是下單前還是下單後」的語意
- 未保留同輪價格快照

影響：

- 難以重建某次決策時的完整交易上下文
- 長期來看，分析價值低於 `reconciliation_decisions`

### 4. SQLite 是 write-only 觀測庫，不是 authoritative state

這是設計選擇，不是 bug，但需要持續記住。

現況：

- 交易邏輯不會讀 SQLite
- 真實倉位以 Binance 即時讀取為準
- SQLite 寫入失敗不會阻塞交易流程

影響：

- 優點是簡單、容錯高、重啟後可恢復
- 缺點是 SQLite 無法單獨作為完整交易真相來源

### 5. Schema 演進能力弱

目前 schema 採嚴格欄位比對；若欄位不一致，程式會要求重建資料庫。

現況：

- 無 migration 機制
- 無 schema version table
- 無向後相容策略

影響：

- MVP 階段尚可接受
- 若後續頻繁迭代欄位，會增加部署與資料保留成本

### 6. 缺少索引與資料保留策略

目前表結構沒有額外 index，也沒有 archive / retention 機制。

影響：

- 早期資料量小時問題不大
- 長期運作後，手動查詢與資料保留成本會逐漸上升

## MVP 階段判斷

以下判斷目前成立：

- 主交易邏輯可用
- 倉位收斂機制可用
- 觀測精度有限，但對個人散戶、小量、單一高流動性標的通常可接受
- 現階段可優先維持簡單輪詢架構，不急於導入複雜訂單狀態機

## 後續建議方向

若未來要提升觀測精度，建議優先順序如下：

1. 在送單成功後，追加「查訂單 / 查成交」流程，而不是重寫整個主輪詢
2. 為 `execution_results` 補充最小必要欄位：
   - `executed_qty`
   - `avg_price`
   - `final_status`
   - `client_order_id`
3. 為 `source_snapshots`、`binance_positions` 補 `cycle_id`
4. 規劃 SQLite schema version / migration 策略
5. 視資料量增加 index 與 retention 政策

## 暫不急做的項目

以下項目目前可延後，不屬於 MVP 必須立即處理：

- WebSocket user data stream
- 完整訂單狀態機
- 逐筆 fill 對帳系統
- 複雜限價追價邏輯
- 完整 P&L / fee accounting

## 文件狀態

- 建立日期：2026-03-31
- 用途：MVP 階段後續迭代備忘
- 性質：產品 / 架構待辦，不代表當前必須立即修復
