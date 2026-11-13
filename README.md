# Thai Fund NAV Board

A website that shows the daily NAV of every Thai mutual fund, refreshed automatically every morning at 06:07 (Bangkok time) from the SEC Open Data API.

**Cost: ฿0.** Everything runs on GitHub's free tier:

| Job | Free service used |
|---|---|
| Run the update every morning | GitHub Actions (scheduled workflow) |
| Store the data ("database") | JSON files inside this GitHub repository (`data/`) |
| Host the website | GitHub Pages |
| Keep the API key secret | GitHub Secrets |

You do **not** need to rent a server or a database.

---

## ขั้นตอนติดตั้ง (ทำครั้งเดียว ~15 นาที)

### 1) เข้าสู่ระบบ GitHub
ใช้บัญชี GitHub ที่มีอยู่แล้ว เข้าที่ https://github.com

### 2) สร้าง repository ใหม่
1. กดปุ่ม **+** มุมขวาบน → **New repository**
2. Repository name: `thai-fund-nav`
3. เลือก **Public** (GitHub Pages ฟรีต้องเป็น Public — ข้อมูล NAV เป็นข้อมูลสาธารณะอยู่แล้ว ส่วน API key จะเก็บแยกเป็นความลับ ไม่มีใครเห็น)
4. กด **Create repository**

### 3) อัปโหลดไฟล์
1. แตกไฟล์ zip ที่ได้รับไว้ในเครื่อง
2. ในหน้า repository กดลิงก์ **uploading an existing file**
3. ลาก **ทุกอย่างที่อยู่ข้างในโฟลเดอร์ `thai-fund-nav`** (โฟลเดอร์ `.github`, ไฟล์ `update.py`, `index.html`, `README.md`) ไปวางในหน้าเว็บ
   - บน Mac โฟลเดอร์ `.github` ถูกซ่อน กด `Cmd + Shift + .` ใน Finder เพื่อให้มองเห็น
4. กด **Commit changes**
5. ตรวจว่ามีไฟล์ `.github/workflows/daily-update.yml` อยู่ใน repo (ถ้าไม่มี ให้กด **Add file → Create new file** พิมพ์ชื่อ `.github/workflows/daily-update.yml` แล้ว copy เนื้อหาจากไฟล์ในเครื่องมาวาง)

### 4) ใส่ API key แบบลับ
1. ใน repo ไปที่ **Settings → Secrets and variables → Actions**
2. กด **New repository secret**
3. Name: `SEC_API_KEY`
4. Secret: ใส่ API key ของคุณ
5. กด **Add secret**

### 5) เปิดเว็บไซต์
1. **Settings → Pages**
2. ตรง **Source** เลือก **GitHub Actions**

### 6) รันครั้งแรก
1. ไปแท็บ **Actions** (ถ้ามีปุ่มเขียว "I understand my workflows, go ahead and enable them" ให้กด)
2. เลือก **Daily NAV update** ทางซ้าย → **Run workflow** → กด **Run workflow**
3. ครั้งแรกระบบจะดึงประวัติย้อนหลัง 13 เดือนให้อัตโนมัติ รอประมาณ 30–40 นาที จนขึ้นเครื่องหมายถูกสีเขียว
   - ถ้าต้องการประวัติ 10 ปี (แนะนำ): ตอนกด Run workflow ให้ใส่ช่อง **From date** = `2016-01-01` (ใช้เวลาประมาณ 2–3 ชั่วโมง ทำครั้งเดียว)
4. เว็บของคุณจะอยู่ที่ `https://<ชื่อผู้ใช้ GitHub>.github.io/thai-fund-nav/`

หลังจากนี้ระบบจะอัปเดตเองทุกเช้า 06:07 น. ไม่ต้องทำอะไรอีก

---

## ใช้งานประจำวัน
- **ค้นหา**: พิมพ์รหัสกองทุน ชื่อไทย/อังกฤษ หรือชื่อ บลจ.
- **กรอง**: บลจ., ประเภทกองทุน, SSF / RMF / ThaiESG
- **เรียงลำดับ**: กดหัวคอลัมน์
- **★ Watchlist**: กดดาวหน้ากองทุนที่ถือ แล้วกดชิป ★ Watchlist (จำไว้ในเบราว์เซอร์นั้น)
- **กราฟ**: กดที่แถวเพื่อดู NAV ย้อนหลัง 1M / 3M / 6M / 1Y

- **Fees & ranking**: สลับไปแท็บนี้เพื่อดูค่าธรรมเนียม (TER, management fee, front/back-end), ผลตอบแทน 3 ปี เทียบค่าเฉลี่ยกลุ่ม, ความผันผวน, ระดับความเสี่ยง 1–8 และคะแนน 0–100 ปรับน้ำหนักได้ด้วยแถบเลื่อน (ข้อมูลจาก fund factsheet รายเดือน อัปเดตทุกสัปดาห์)

- **เงินปันผล**: ปฏิทินกองทุนที่จะปิดสมุดทะเบียน/จ่ายปันผลเร็ว ๆ นี้, คอลัมน์ Yield 12 เดือน, ตัวกรอง "Pays dividends", และสวิตช์ "Returns include dividends" (บวกเงินปันผลกลับเข้าไปในผลตอบแทน — เปิดไว้เป็นค่าเริ่มต้น) หน้ากองทุนแสดงประวัติการจ่ายปันผลรายปีและรายครั้ง

## ถ้ามีปัญหา
| อาการ | วิธีแก้ |
|---|---|
| Actions ขึ้น ❌ "ERROR 401" | API key ผิด → แก้ใน Settings → Secrets |
| Actions ขึ้น ❌ ตอน deploy | ตรวจว่า Settings → Pages → Source = **GitHub Actions** |
| เว็บไม่อัปเดต | ดูแท็บ Actions ว่ารันไหม; ถ้า repo ไม่มีความเคลื่อนไหว 60 วัน GitHub จะหยุดตารางเวลา ให้กด Enable workflow ใหม่ |
| อยากดึงประวัติย้อนหลังเพิ่ม | Actions → Run workflow → ใส่ **From date** เช่น `2016-01-01` (10 ปี) |
| อยากได้ประวัติทั้งหมดตั้งแต่ปี 2540 (1997) | รันทีละช่วงเพื่อไม่ให้เกินเวลา 6 ชม. ของ GitHub: (1) From `1997-01-01` To `2005-12-31` (2) From `2006-01-01` To `2015-12-31` (3) From `2016-01-01` — ข้อมูลรวม ~700 MB ใกล้เพดาน GitHub แนะนำทำตอนย้ายไป Supabase |

## How it works (technical)
- `update.py fetch` calls `GET https://api.sec.or.th/v2/fund/daily-info/nav?start_nav_date=…&end_nav_date=…` (header `Ocp-Apim-Subscription-Key`), pages with `next_cursor` (100 rows/page), and writes one file per NAV date to `data/daily/`. It also refreshes the active fund list from `/v2/fund/general-info/profiles?fund_status=Registered|IPO`.
- Fees, factsheet returns, peer averages, volatility and risk level come from `/v2/fund/factsheet/fees`, `/factsheet/performance` and `/factsheet/risk-spectrum`, refreshed weekly into `data/factsheet.json` (about 7,500 calls; the script backs off automatically on SEC rate limits and resumes on the next run if interrupted).
- Dividends: `/v2/fund/daily-info/dividend-history` (every payout since 1994, ~45 calls) and `/v2/fund/factsheet/dividend-policy` (pays or not, per class), refreshed daily into `data/dividends.json`. Total returns add each payout back on the first NAV date on or after its book-close date, which is when the NAV drops in about 3 of 4 cases checked. The SEC record has gaps (almost nothing for 2021–2023, some payers missing).
- Each run re-downloads the last 7 days so late or corrected NAVs are picked up.
- `update.py build` turns `data/` into the website in `site/` (latest table with 1D/1W/1M/3M/6M/YTD/1Y returns + one history file per fund) and the workflow deploys it to GitHub Pages.
- Daily files are small (~200 KB) and never rewritten once settled, so the repo grows by roughly 50 MB a year.
