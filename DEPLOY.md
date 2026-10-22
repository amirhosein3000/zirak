# راهنمای اجرا و دیپلوی زیرک برای چالش والکس (برای هم‌تیمی‌ها)

> این فایل خلاصهٔ قدم‌به‌قدم است. جزئیات بیشتر: [docs/challenge/RUNBOOK.md](docs/challenge/RUNBOOK.md) ·
> توضیح فنی الگوریتم برای داوران: [docs/ALGORITHM.md](docs/ALGORITHM.md) · متن چالش: [docs/challenge/spec.md](docs/challenge/spec.md)

## وضعیت فعلی (صادقانه)
- ✅ **آماده و تست‌شده:** موتور معاملاتی، مدل یادگیری ماشین، عامل مدل زبانی، لایهٔ ریسک، بک‌تست، تست سایه، کلید توقف،
  بازگشت بعد از ری‌استارت، ۱۵۷ تست خودکار، ایمیج Docker، مستندات تحویلی.
- ⚠️ **هنوز با والکس واقعی امتحان نشده:** مدل روی دادهٔ ۱۵ دقیقه‌ای واقعی آموزش ندیده، کارمزد واقعی حساب معلوم نیست
  (همین سود یا زیان را تعیین می‌کند)، شکل پاسخ سفارش‌ها تأیید نشده، عامل مدل زبانی با سرویس واقعی تست نشده.
  مراحل ۱ تا ۳ پایین این‌ها را مشخص می‌کنند.
- روی دادهٔ نمونه با کارمزد فرضی: سود تحقق‌یافته حدود ‎−۰٫۶٪، بیشترین افت ۱٫۴٪. سودآوری هنوز ثابت نشده است.

## قوانین طلایی
1. **فقط از داخل ایران.** API والکس از خارج در دسترس نیست.
2. **`LIVE_TRADING=false`** تا وقتی همهٔ تیم سقف‌های ریسک (مرحلهٔ ۴) را تأیید کند.
3. **هیچ سفارش دستی** روی حساب چالش ثبت نکنید (ممنوع و باعث حذف است).
4. **در طول چالش کد را عوض نکنید.** کد تحویلی باید همان کدی باشد که معامله کرده (هر اجرا commit خودش را ثبت می‌کند).
5. کلیدها فقط در `.env`؛ هرگز commit نکنید. کلید API فقط با مجوز **معامله**، بدون برداشت.

---

## مسیر پیشنهادی: دیپلوی روی لیارا (سرورهای ایران، با حساب تیم)
لیارا در ایران است، پس ربات مستقیم به API والکس دسترسی دارد و سرور جدا لازم نیست. دو اپ ساخته می‌شود:
`zirak-api` (API + عامل معاملاتی در یک کانتینر، با دیسک دائمی برای داده‌ها) و `zirak-web` (داشبورد).

**فقط یک بار، در گیت‌هاب** (Settings ← Secrets and variables ← Actions). همین کافی است؛ بقیه خودکار است:
- **Secrets (لازم):** `LIARA_API_TOKEN` (توکن API لیارا)، `WALLEX_API_KEY` (کلید حساب چالش)،
  و `LIARA_TEAM_ID` (شناسهٔ تیم در لیارا؛ اگر خالی باشد روی حساب شخصیِ صاحب توکن دیپلوی می‌شود).
- **Secrets (اختیاری):** `LLM_API_KEY`، `WALLEX_SUB_ACCOUNT_CLIENT_ID`.
- **Variables (اختیاری):** `LIARA_PLAN` (فقط اگر اپ‌ها هنوز در لیارا ساخته نشده‌اند: شناسهٔ پلن از `liara plan list`؛
  دیپلوی خودش دو اپ Docker و دیسک `zirak-data` را می‌سازد)، `ZIRAK_CHALLENGE_START` و `ZIRAK_CHALLENGE_END`
  (زمان چالش به **UTC**، مثل `2026-11-01T06:30:00Z`؛ بدون آن، بستن خودکار پوزیشن‌ها در پایان چالش فعال نیست)،
  `LLM_BASE_URL`، `LLM_MODEL`، `WALLEX_PROP_PACKAGE_ID`، `ZIRAK_AGENT` (پیش‌فرض shadow)، `LIVE_TRADING` (پیش‌فرض false)،
  `MAX_ORDER_TMN`، `DAILY_LOSS_LIMIT_PCT`.

**هر بار دیپلوی:** Actions ← **Deploy to Liara** ← Run workflow (`both`). به ترتیب:
1. همهٔ تست‌ها و بررسی‌های کیفیت.
2. اگر اپ‌های `zirak-api` / `zirak-web` یا دیسک `zirak-data` (روی `/data`) نیستند، ساخته می‌شوند (با `LIARA_PLAN`؛
   اگر آن را نگذاشته‌اید، یک بار خودتان در پنل لیارا دو اپ از نوع **Docker** در تیم بسازید؛ پیام خطا همین را می‌گوید).
3. تنظیمات و کلیدها از Secrets/Variables گیت‌هاب در متغیرهای اپ `zirak-api` لیارا نوشته می‌شوند (حالت سایه، بدون سفارش واقعی).
4. دو اپ در لیارا (ساخت در ایران) دیپلوی می‌شوند؛ commit دیپلوی‌شده در هر اجرای ربات ثبت می‌شود. بار اول، ربات خودش سابقهٔ
   قیمت را دانلود و مدل را آموزش می‌دهد (`ZIRAK_BOOTSTRAP=true`).
از سیستم خودتان هم می‌شود: `LIARA_API_TOKEN=... LIARA_TEAM_ID=... sh scripts/deploy-liara.sh both`

**بعد از دیپلوی:**
- داشبورد: `https://zirak-web.liara.run/agent` · سلامت API: `https://zirak-api.liara.run/api/health`
- دستورها داخل کانتینر (کنسول اپ در پنل لیارا یا `liara shell --app zirak-api --team-id <TEAM_ID>`):
  `zirak agent report /data/runs/challenge-shadow`، `zirak agent probe --symbol USDTTMN --yes` (مرحلهٔ ۲)، `zirak kill`
- رفتن به معاملهٔ واقعی (بعد از مراحل ۱ تا ۳ و تأیید تیم): در متغیرهای لیارا `LIVE_TRADING=true` و
  `ZIRAK_AGENT=live,shadow` بگذارید و اپ را ری‌استارت کنید (`liara app restart --app zirak-api --team-id <TEAM_ID>`).
- ربات اگر خطا بدهد خودکار دوباره بالا می‌آید و از همان‌جا ادامه می‌دهد؛ بعد از `zirak kill` خاموش می‌ماند.

> ⛔ هیچ توکن یا کلیدی را در `.env.example` یا هر فایل دیگری که در گیت است ننویسید؛ آن فایل عمومی است. جای کلیدها:
> متغیرهای پنل لیارا، Secrets گیت‌هاب، یا فایل `.env` محلی (که در گیت نیست). اگر کلیدی تا حالا جایی commit یا ارسال شده،
> همان را باطل کنید و کلید جدید بسازید.

**مسیر جایگزین (بدون لیارا):** مراحل ۰ تا ۶ زیر روی یک VPS داخل ایران با Docker.

---

## مرحلهٔ ۰ — آماده‌سازی (یک بار)
1. **سرور:** یک VPS لینوکسی داخل ایران با Docker (پیشنهادی؛ سه روز بدون قطعی = امتیاز «پایداری»).
   لپ‌تاپ هم می‌شود، ولی نباید خاموش شود یا به خواب برود.
2. **دریافت کد:**
   ```bash
   git clone https://github.com/amirhosein3000/zirak && cd zirak
   cp .env.example .env
   ```
3. **پر کردن `.env`:**
   ```
   WALLEX_API_KEY=<کلید خودِ حساب اعتباری چالش>
   WALLEX_CREDIT_ACCOUNT=true
   WALLEX_SUB_ACCOUNT_CLIENT_ID=<اگر والکس داد>
   WALLEX_PROP_PACKAGE_ID=<اگر والکس داد؛ بازارهای غیرمجاز خودکار حذف می‌شوند>
   MOCK_LLM=false
   LLM_BASE_URL=<آدرس سرویس سازگار با OpenAI>
   LLM_API_KEY=<کلید>
   LLM_MODEL=<نام مدل>
   LIVE_TRADING=false
   MAX_ORDER_TMN=1500000
   MAX_ORDER_USDT=50
   DAILY_LOSS_LIMIT_PCT=2.5
   ```
4. **زمان چالش** را در `.env` بنویسید: `ZIRAK_CHALLENGE_START=...Z` و `ZIRAK_CHALLENGE_END=...Z`
   (یا در `backend/config/challenge.json` → `"clock"`) به وقت **UTC** (= ساعت تهران منهای ۳:۳۰). ربات ۴ ساعت قبل از پایان ورود جدید نمی‌زند و ۳۰ دقیقه قبل از پایان همه‌چیز تومان است.
5. **نصب (فقط اگر بدون Docker کار می‌کنید):**
   ```bash
   cd backend
   python3.12 -m venv .venv
   source .venv/bin/activate          # ویندوز: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```
   > در حالت Docker، دستورهای `zirak ...` را این‌طور اجرا کنید: `docker compose run --rm agent-shadow zirak ...`
   > (یا بعد از بالا آمدن سرویس: `docker compose exec agent-live zirak ...`). مسیر داده‌ها داخل Docker `/data` است.

## مرحلهٔ ۱ — داده و مدل (حدود ۱۵ دقیقه)
از داخل پوشهٔ `backend` (خروجی‌ها در پوشهٔ `data` در ریشهٔ پروژه ذخیره می‌شوند؛ در Docker: `/data`):
```bash
zirak backfill --days-1m 45 --days-1h 180     # دانلود سابقهٔ قیمت از والکس
zirak data-stats                              # بررسی: برای هر بازار دادهٔ 1m باید باشد
zirak agent train                             # آموزش مدل -> ../data/models/challenge/model_card.json
zirak agent backtest --days 14                # بک‌تست با همان موتور -> ../data/runs/backtest-.../report.md
zirak agent verify ../data/runs/<نام اجرا>    # باید "ok": true بدهد
```
👉 فایل‌های `report.md` و `model_card.json` را در گروه بفرستید و بررسی کنید. اگر مدل معاملاتی با سود مورد انتظار منفی
می‌گیرد، `model.min_ev_pct` را در config بالا ببرید و دوباره آموزش دهید (هرگز سقف‌های ریسک را شل نکنید).

## مرحلهٔ ۲ — تست واقعی کوچک (با حضور تیم)
1. موقتاً در `.env`: `LIVE_TRADING=true`
2. ```bash
   zirak agent probe --symbol USDTTMN --yes
   ```
   یک سفارش خیلی کوچک ۵٪ پایین‌تر از قیمت خرید ثبت، بررسی و لغو می‌کند؛ موجودی، کارمزد و حد لیکوییدی حساب را هم چاپ می‌کند.
3. **خروجی را ذخیره و در گروه بفرستید** (برای تأیید فیلدهای UNVERIFIED در `docs/wallex-api/`).
4. دوباره `LIVE_TRADING=false`.

## مرحلهٔ ۳ — تست سایه (چند ساعت، ترجیحاً یک شب)
داده‌های زندهٔ والکس، سفارش‌های کاغذی روی دفتر سفارش واقعی:
```bash
GIT_COMMIT=$(git rev-parse HEAD) docker compose --profile shadow up -d --build
# بدون Docker:  zirak agent shadow
```
صفحهٔ وب برای پایش (و ضبط ویدئو):
```bash
NEXT_PUBLIC_API_URL=http://<IP-سرور>:8000 CORS_ORIGINS=http://<IP-سرور>:3000 docker compose up -d --build
```
بعد مرورگر: `http://<IP-سرور>:3000/agent`
گزارش: `docker compose exec agent-shadow zirak agent report /data/runs/challenge-shadow`

## مرحلهٔ ۴ — شروع معاملهٔ واقعی
1. **همهٔ تیم سقف‌ها را تأیید کند:** ریسک هر معامله ۰٫۶٪ سرمایه · سقف هر بازار ۳۰٪ · سقف کل ۷۰٪ · سقف هر سفارش
   `MAX_ORDER_TMN` · زیان روزانه ۲٫۵٪ (توقف ورود تا فردا) · افت ۵٪ از اوج = توقف ورود · افت ۸٪ = فروش همه و توقف ·
   فاصله تا حد لیکوییدی طرح اعتباری · تبدیل کامل به تومان قبل از پایان.
2. در `.env`: `LIVE_TRADING=true`
3. ```bash
   GIT_COMMIT=$(git rev-parse HEAD) docker compose --profile live up -d --build
   docker compose --profile recorder up -d          # ضبط داده در طول چالش
   # بدون Docker:  zirak agent live --i-understand-this-is-real-money
   ```
   تست سایه را هم کنارش روشن نگه دارید (مدرک خوب برای داوران).
4. اگر سرور ری‌استارت شد: همان دستور را دوباره بزنید؛ ربات از وضعیت ذخیره‌شده ادامه می‌دهد و با حساب تطبیق می‌دهد.

## مرحلهٔ ۵ — پایش در طول چالش
| چه چیزی | دستور |
|---|---|
| لاگ زنده | `docker compose logs -f agent-live` |
| گزارش (بازده، افت، معاملات، حجم، تأخیر، خطا) | `docker compose exec agent-live zirak agent report /data/runs/challenge-live` |
| داشبورد | `http://<IP-سرور>:3000/agent` |
| آخرین تصمیم‌ها | `docker compose exec agent-live tail -n 5 /data/runs/challenge-live/decisions.jsonl` |

## اضطراری
| وضعیت | دستور |
|---|---|
| توقف فوری، لغو همهٔ سفارش‌ها | `docker compose exec agent-live zirak kill` |
| فروش همه‌چیز به تومان (بعد از kill) | `docker compose exec agent-live zirak agent flatten --yes` |
| ادامه بعد از kill | `zirak reset-kill` و دوباره دستور مرحلهٔ ۴ |
| باگ در کد | اول kill، بعد اصلاح، تست‌ها، commit و push، **بعد** اجرای دوباره |

## مرحلهٔ ۶ — بعد از پایان چالش (تحویلی‌ها)
```bash
docker compose exec agent-live zirak agent report /data/runs/challenge-live
docker compose exec agent-live zirak agent verify /data/runs/challenge-live
docker compose exec agent-live zirak agent export /data/runs/challenge-live    # decisions.csv = لاگ تصمیم
docker compose exec agent-shadow zirak agent report /data/runs/challenge-shadow
```
1. پوشهٔ اجراها را از Docker بیرون بیاورید: `docker compose cp agent-live:/data/runs ./results`
2. `report.md`، `report.json`، `decisions.csv`، `decisions.jsonl`، `postures.jsonl`، `trades.jsonl`، `orders.jsonl`،
   `equity.csv`، `manifest.json` و `models/` را در `docs/challenge/results/` commit کنید (کلید یا رمزی در آن‌ها نیست).
3. بخش نتایج `docs/ALGORITHM.md` را با اعداد واقعی به‌روز کنید.
4. ویدئوی ۵ دقیقه‌ای را طبق [docs/challenge/demo-video.md](docs/challenge/demo-video.md) ضبط کنید (با صدا).
5. push و تگ: `git tag challenge-final && git push origin challenge-final`

## چک‌لیست سریع
- [ ] Secrets گیت‌هاب (`LIARA_API_TOKEN`، `WALLEX_API_KEY`، `LIARA_TEAM_ID`) + `ZIRAK_CHALLENGE_START/END` (یا: سرور داخل ایران + Docker)
- [ ] `.env` کامل (کلید حساب اعتباری، LLM، سقف‌ها، `LIVE_TRADING=false`)
- [ ] زمان شروع/پایان در `challenge.json` به UTC
- [ ] backfill → train → backtest → verify (ok)
- [ ] probe روی حساب واقعی، خروجی ذخیره شد
- [ ] تست سایه چند ساعت بدون خطا
- [ ] تأیید سقف‌های ریسک توسط تیم → `LIVE_TRADING=true` → live + recorder
- [ ] بعد از پایان: report، verify، export، commit نتایج، ویدئو، تگ
