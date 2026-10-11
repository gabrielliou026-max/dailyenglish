# DailyEnglish

每天由 Claude 依照目前程度自動出英文選擇題，目標為 **多益金色證書（860+）** 與 **FLPT 240**。手機作答，所有紀錄存在資料庫，用來分析強弱項並調整隔天的題目。

架設步驟請看 **[SETUP.md](SETUP.md)**。

## 架構

```
GitHub Actions（每天 04:07 台灣時間）
  ├─ 讀取各技能能力值與錯題複習排程
  ├─ Claude 出題 → 另一次呼叫獨立作答驗題 → 答案不一致或有歧義的題目淘汰
  └─ 寫入 Supabase

手機 PWA（Vercel） ←→ Supabase（PostgreSQL + Auth + RLS）
```

| 目錄 | 內容 |
|---|---|
| `supabase/migrations/` | 資料表、RLS、作答 RPC（能力值更新與錯題排程都在 DB 端計算） |
| `generator/` | Python 出題程式（planner 選題 → Claude 出題 → 驗題 → 寫入） |
| `web/` | React + Vite 手機網頁 |
| `.github/workflows/` | 每日出題排程、CI 測試 |

## 每日題組（v1，約 15 分鐘）

| 區塊 | 題數 |
|---|---|
| 用法（文法、字彙，句子填空） | 10 |
| 閱讀（1 篇短文） | 4 |
| 錯題複習 | 最多 3 |

題目約 60% 多益風格（商務職場）、40% FLPT 風格（新聞、政府、學術）。

## 適性出題邏輯

- **技能分類**：13 項文法、8 類字彙、6 種閱讀題型（見 `skills` 資料表）
- **能力值**：每個技能一個 Elo 式分數，以多益分數為尺度，初始 805。預期答對率含四選一猜題下限：`P = 0.25 + 0.75 / (1 + 10^((難度 − 能力) / 150))`
- **選技能**：離目標（900）越遠、資料越少、越久沒練的技能，被抽中的機率越高
- **選難度**：60% 接近目前程度、25% 高 80 分（挑戰）、15% 低 80 分。累積作答未滿 30 題前為校正期，難度刻意分散
- **錯題複習**：答錯的題目依 1 → 3 → 7 → 14 → 30 天重新出現，30 天那次答對即畢業。複習題不影響能力值

## 費用估計

每天大約 8k input、12–18k output tokens（含模型思考），實際用量會記錄在 App 的「學習分析 → 出題紀錄」。

| 模型 | 每天約 | 每月約 |
|---|---|---|
| `claude-opus-5-5`（預設） | US$0.25–0.40 | US$8–12 |
| `claude-sonnet-5-5` | US$0.13–0.20 | US$4–6 |

以上是估計值，以實際紀錄為準。Supabase、Vercel、GitHub Actions 使用免費方案。

## 本機開發

```bash
# 出題程式測試（需要 PostgreSQL）
createdb de_test
psql de_test -f supabase/tests/local_auth_stub.sql -f supabase/migrations/0001_init.sql
cd generator && pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql:///de_test python -m pytest

# 前端
cd web && cp .env.example .env.local   # 填入 Supabase URL 與 anon key
npm install && npm run dev
```

## 開發進度

- [x] v1：出題、驗題、手機作答、能力值、錯題複習、基本分析頁
- [ ] v2：聽力（Kokoro TTS 產生音檔）
- [ ] v3：分析圖表、每日推播提醒、模考模式
