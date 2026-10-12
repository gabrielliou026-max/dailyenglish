# DailyEnglish

每天由 Claude 依照目前程度自動出英文選擇題，目標為 **多益金色證書（860+）** 與 **FLPT 240**。手機作答，所有紀錄存在資料庫，用來分析強弱項並調整隔天的題目。

架設步驟請看 **[SETUP.md](SETUP.md)**。

## 架構

```
GitHub Actions（每天 04:07 台灣時間）
  ├─ 讀取各技能能力值與錯題複習排程
  ├─ Claude 出題 → 另一次呼叫獨立作答驗題 → 答案不一致或有歧義的題目淘汰
  ├─ 聽力稿用 Kokoro TTS 轉成 mp3（模型在 Actions 上執行，不用另外付費）
  └─ 寫入 Supabase（音檔也存在資料庫）

手機 PWA（Vercel） ←→ Supabase（PostgreSQL + Auth + RLS）
```

| 目錄 | 內容 |
|---|---|
| `supabase/migrations/` | 資料表、RLS、作答 RPC（能力值更新與錯題排程都在 DB 端計算） |
| `generator/` | Python 出題程式（planner 選題 → Claude 出題 → 驗題 → 寫入） |
| `web/` | React + Vite 手機網頁 |
| `.github/workflows/` | 每日出題排程、CI 測試 |

## 每日題組（v2，約 30 分鐘）

| 區塊 | 題數 | 內容 |
|---|---|---|
| 聽力 | 9 | 應答 3（多益 Part 2，三選一，只聽不看）、對話 3（Part 3）、獨白 3（Part 4） |
| 用法 | 10 | 文法、字彙，句子填空 |
| 閱讀主文章 | 4–5 | 每天隨機：單篇、雙篇、三篇（多益 Part 7）、表格與圖表 |
| 短文填空 | 4 | 多益 Part 6／FLPT 用法短文填空，最後一空考篇章結構（句子插入） |
| 錯題複習 | 最多 3 | |

- 聽力作答前每段最多播 2 次，整段題目做完才顯示文字稿；聲音有美式、英式男女聲。
- 文章與聽力情境的主題每天在 16 個領域間輪換（科技、健康、旅遊、財經、人資…）。
- 閱讀約 60% 多益風格（商務職場）、40% FLPT 風格（新聞、政府、學術）；聽力一律多益風格。
- 資料庫還沒套用 `0002` 時，出題程式會自動退回 v1（用法 10＋單篇閱讀 4），不會中斷。

## 適性出題邏輯

- **技能分類**：13 項文法、8 類字彙、10 種閱讀題型、4 種聽力題型（見 `skills` 資料表）
- **能力值**：每個技能一個 Elo 式分數，以多益分數為尺度，初始 805。預期答對率含四選一猜題下限：`P = 0.25 + 0.75 / (1 + 10^((難度 − 能力) / 150))`
- **選技能**：離目標（900）越遠、資料越少、越久沒練的技能，被抽中的機率越高
- **選難度**：60% 接近目前程度、25% 高 80 分（挑戰）、15% 低 80 分。累積作答未滿 30 題前為校正期，難度刻意分散
- **錯題複習**：答錯的題目依 1 → 3 → 7 → 14 → 30 天重新出現，30 天那次答對即畢業。複習題不影響能力值

## 費用估計

v2 每天的 Claude 呼叫從 4 次增加到約 10–12 次（聽力 3 組、閱讀 2 組，各自出題＋驗題），token 用量大約是 v1 的 2–3 倍。
下表是依 v1 的估計值按比例推算，**尚未實際量測**，請以 App「學習分析 → 出題紀錄」的實際用量為準。

| 模型 | 每天約 | 每月約 |
|---|---|---|
| `claude-opus-5-5`（預設） | US$0.6–1.0 | US$18–30 |
| `claude-sonnet-5-5` | US$0.3–0.5 | US$9–15 |

如果 Anthropic Console 設的每月上限是 US$15，用 Opus 可能會在月底前用完，可以把上限調高，或在 GitHub Variables 把 `CLAUDE_MODEL` 改成 `claude-sonnet-5-5`。
Kokoro 語音在 GitHub Actions 上執行，不另外收費。音檔存在 Supabase 資料庫，每天約 1 MB，超過 60 天且不在錯題複習中的音檔會自動刪除。

## 本機開發

```bash
# 出題程式測試（需要 PostgreSQL）
createdb de_test
psql de_test -f supabase/tests/local_auth_stub.sql -f supabase/migrations/0001_init.sql \
  -f supabase/migrations/0002_listening_reading_formats.sql
cd generator && pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql:///de_test python -m pytest

# 前端
cd web && cp .env.example .env.local   # 填入 Supabase URL 與 anon key
npm install && npm run dev
```

## 開發進度

- [x] v1：出題、驗題、手機作答、能力值、錯題複習、基本分析頁
- [x] v2：聽力（Kokoro TTS 產生音檔）、閱讀新題型（雙篇／三篇、表格、短文填空、篇章結構）、每日約 30 分鐘
- [ ] v3：分析圖表、每日推播提醒、模考模式
