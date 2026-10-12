# 架設步驟

整套只要做一次，大約 30–60 分鐘。需要三個帳號：Anthropic、Supabase、Vercel（GitHub 已經有了）。

> 各服務的選單名稱可能會改版，以下以 2026 年 10 月的介面為準。若找不到某個選單，以該服務官方文件為準。

---

## 1. Supabase（資料庫與登入）

1. 到 <https://supabase.com> 用 GitHub 登入 → **New project**
   - Region 選 **Northeast Asia (Tokyo)** 或 **Southeast Asia (Singapore)**
   - **Database Password 記下來**，第 4 步會用到
2. 左側 **SQL Editor** → New query → 把 `supabase/migrations/0001_init.sql` 整份貼上 → **Run**
   - 接著再開一個 New query，把 `supabase/migrations/0002_listening_reading_formats.sql` 整份貼上 → **Run**（聽力與閱讀新題型）
3. 建立你的登入帳號：
   - **Authentication → Users → Add user → Create new user**，填 email、密碼，勾選 **Auto Confirm User**
   - **Authentication → Sign In / Providers**，關閉 **Allow new users to sign up**（只有你能用）
4. 取得連線資訊：
   - **Project Settings → API**：複製 **Project URL** 與 **anon / publishable key**（給前端用，第 4 節）
   - 頁面上方 **Connect** → 選 **Session pooler** → 複製連線字串，把 `[YOUR-PASSWORD]` 換成第 1 步的密碼（給 GitHub Actions 用，第 3 節）

> ⚠️ 一定要用 **Session pooler**，不要用 Direct connection。Direct connection 只有 IPv6，GitHub Actions 連不到。
> 連線字串長這樣：`postgresql://postgres.abcdxyz:密碼@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres`

## 2. Anthropic API（出題用）

1. 到 <https://console.anthropic.com> 註冊
2. **Billing** → 儲值（最低金額以頁面顯示為準）
3. **Limits** → 設定每月花費上限，例如 US$15，避免意外
4. **API Keys → Create Key** → 複製（只會顯示一次）

## 3. GitHub（每日排程）

到這個 repo 的 **Settings → Secrets and variables → Actions**：

**Secrets** 分頁 → New repository secret，新增兩個：

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | 第 2 節的 API key |
| `DATABASE_URL` | 第 1 節的 Session pooler 連線字串 |

**Variables** 分頁（選填）：

| Name | 說明 |
|---|---|
| `CLAUDE_MODEL` | 預設 `claude-opus-5-5`。想省一半費用可改 `claude-sonnet-5-5` |
| `CLAUDE_EFFORT` | 預設 `medium`。`low` 較省、`high` 題目品質可能較好但較貴 |

設定完後，到 **Actions → Daily question generation → Run workflow**，手動產生第一份題組（約 2–5 分鐘）。之後每天台灣時間清晨 4 點左右自動執行。

> 排程只會在 repo 的 **default branch** 上執行。如果之後新增 `main` 分支，記得到 Settings → General 把 default branch 改成 `main`，Vercel 也會以 default branch 作為正式版。

## 4. Vercel（手機網頁）

1. 到 <https://vercel.com> 用 GitHub 登入 → **Add New → Project** → 匯入 `dailyenglish`
2. **Root Directory** 選 `web`（Framework 會自動偵測為 Vite）
3. **Environment Variables** 新增：

| Name | Value |
|---|---|
| `VITE_SUPABASE_URL` | 第 1 節的 Project URL |
| `VITE_SUPABASE_ANON_KEY` | 第 1 節的 anon / publishable key |

4. **Deploy**，完成後會拿到一個網址，例如 `https://dailyenglish-xxx.vercel.app`

> anon key 本來就是給前端用的，資料由 RLS 保護，只有登入的你看得到自己的資料。
> `ANTHROPIC_API_KEY` 和 `DATABASE_URL` **絕對不要**放到 Vercel。

## 5. 手機

- **iPhone**：用 Safari 開網址 → 分享 → **加入主畫面** → 從主畫面圖示開啟後登入
- **Android**：用 Chrome 開網址 → 選單 → **安裝應用程式**

> iPhone 主畫面 App 和 Safari 的登入狀態是分開的，要在主畫面 App 裡登入一次。

---

## 從 v1 升級到 v2（聽力、閱讀新題型）

已經照上面架設過 v1 的話，只要做一步：

1. Supabase → **SQL Editor** → New query → 把 `supabase/migrations/0002_listening_reading_formats.sql` 整份貼上 → **Run**

這份 SQL 可以重複執行。不需要新增任何 Secret：Kokoro 語音模型由 GitHub Actions 自動下載並快取，音檔存在原本的資料庫。

執行完之後，下一次出題（清晨自動，或到 Actions 手動 Run workflow）就會有聽力。還沒執行這份 SQL 之前，出題程式會自動維持 v1 題型，不會失敗。

---

## 疑難排解

| 狀況 | 檢查 |
|---|---|
| 首頁顯示「今日題組尚未產生」 | GitHub → Actions，看最近一次執行是否失敗、錯誤訊息 |
| Actions 顯示連線逾時 | `DATABASE_URL` 是否為 Session pooler、密碼是否正確 |
| Actions 顯示 401 / authentication_error | `ANTHROPIC_API_KEY` 是否正確、是否有儲值 |
| 想重新產生今天的題目 | Run workflow 時勾選 force（已作答的題組不會被覆蓋） |
| 某題答案有問題 | 作答後按「回報題目有問題」，該題不計入能力值，也不會進錯題複習 |
| 今天沒有聽力題 | 是否已執行 `0002`；Actions 紀錄裡若有 `Kokoro model files not found`，表示模型下載失敗，重新 Run workflow 即可 |
| 按播放沒有聲音 | iPhone 先關掉靜音鍵；確認是從主畫面 App 或 Safari 開啟、已登入 |

**Supabase 免費方案** 閒置約一週會暫停專案，但每天的排程都會寫入資料，正常使用不會碰到。
若 repo 是 **public**，GitHub 會在 60 天沒有任何 commit 後自動停用排程，需要到 Actions 頁面重新啟用。
