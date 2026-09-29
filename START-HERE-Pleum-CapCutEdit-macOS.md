# คู่มือเริ่มต้น Pleum CapCutEdit for macOS

คู่มือนี้สำหรับผู้ที่ได้รับไฟล์ `Pleum-CapcutEdit-macOS.zip` และต้องการใช้ Codex หรือ Claude ช่วยอ่าน วิเคราะห์ และตัดต่อโปรเจกต์ CapCut Desktop บน Mac

> เริ่มด้วยโปรเจกต์ทดสอบหรือสำเนาของงานจริงเสมอ อย่าใช้โปรเจกต์ต้นฉบับเพียงชุดเดียวในการทดลองครั้งแรก

## Quick Start: 3 ขั้นตอน

### Step 1 — เตรียม Mac

ต้องมี:

- macOS บน Apple Silicon หรือ Intel
- CapCut Desktop 9 หรือใหม่กว่า
- Python 3.10 หรือใหม่กว่า
- FFmpeg และ ffprobe
- Codex Desktop, Codex CLI หรือ Claude Code ที่เข้าถึงไฟล์ในเครื่องได้
- ElevenLabs API key ของผู้ใช้เอง เฉพาะเมื่อต้องถอดเสียงใหม่

ตรวจเวอร์ชันใน Terminal:

```bash
python3 --version
ffmpeg -version
ffprobe -version
```

ถ้ายังไม่มี Python หรือ FFmpeg และใช้ Homebrew:

```bash
brew install python ffmpeg
```

Cloud chat ที่เข้าถึงไฟล์ใน Mac ไม่ได้จะไม่สามารถแก้โปรเจกต์ CapCut ในเครื่องได้ ต้องใช้เครื่องมือที่รันบน Mac เครื่องเดียวกับ CapCut

### Step 2 — แตก ZIP และติดตั้ง Runtime

1. แตกไฟล์ `Pleum-CapcutEdit-macOS.zip`
2. เปิด Terminal
3. เข้าโฟลเดอร์ที่แตกออกมา โดยเปลี่ยน path ให้ตรงกับเครื่องของตัวเอง:

```bash
cd "/absolute/path/to/pleum-capcutedit-macos"
```

4. ตรวจความพร้อมแบบไม่แก้เครื่องหรือโปรเจกต์:

```bash
sh install.sh --check-only
```

5. ติดตั้ง Python packages ลง `.venv` ภายในโฟลเดอร์นี้:

```bash
sh install.sh
```

คำสั่งนี้ต้องใช้อินเทอร์เน็ตเพื่อติดตั้ง packages แต่จะไม่แก้โปรเจกต์ CapCut

### Step 3 — ติดตั้ง Skill และทดลองกับโปรเจกต์สำรอง

คำว่า `--project-path` ด้านล่างหมายถึงโฟลเดอร์งานของ Codex/Claude ไม่ใช่โฟลเดอร์โปรเจกต์ CapCut

ติดตั้งให้ Codex ระดับ repository:

```bash
./.venv/bin/python scripts/install_skill.py \
  --tool codex \
  --project-path "/absolute/path/to/your/codex-workspace" \
  --dry-run
```

ตรวจ destination ที่แสดง แล้วรันซ้ำโดยเอา `--dry-run` ออก

สำหรับ Claude Code ระดับโปรเจกต์:

```bash
./.venv/bin/python scripts/install_skill.py \
  --tool claude-project \
  --project-path "/absolute/path/to/your/claude-project" \
  --dry-run
```

จากนั้น:

1. เปิด CapCut และสร้างหรือ Duplicate โปรเจกต์ทดสอบ
2. ตั้งชื่อที่จำง่าย เช่น `Skill Test`
3. ปิด CapCut ให้สนิท
4. ขอให้ Agent ใช้ `$pleum-capcutedit-macos` ตรวจโปรเจกต์ก่อน เช่น:

```text
ใช้ $pleum-capcutedit-macos ตรวจโปรเจกต์ CapCut ชื่อ Skill Test
ทำแบบ read-only และรายงาน schema, timeline และสิ่งที่ทำได้ก่อน
```

5. ให้ทำ `dry-run` ก่อนทุกครั้ง แล้วตรวจรายงานก่อนอนุญาตให้เขียนจริง

## ตั้งค่า ElevenLabs สำหรับถอดเสียง

ไม่ต้องใช้ API key สำหรับการค้นหาโปรเจกต์ ตรวจ schema ตรวจ mirror หรือใช้ transcript cache ที่ยังตรงกับไทม์ไลน์

เมื่อต้องถอดเสียงใหม่:

```bash
cp .env.example .env
open -e .env
```

ใส่คีย์ของผู้ใช้เองในรูปแบบ:

```env
ELEVENLABS_API_KEY=put_your_api_key_here
```

บันทึกไฟล์แล้วปิด TextEdit ห้ามส่ง `.env`, API key หรือ transcript ให้ผู้อื่น และไม่ควรวาง API key ลงในแชต

## ตรวจระบบก่อนใช้งาน

```bash
./.venv/bin/edit-capcut doctor
```

ปิด CapCut แล้วตรวจโปรเจกต์และ active mirrors บน Mac:

```bash
./.venv/bin/edit-capcut macos-validate
```

ตรวจโปรเจกต์ตามชื่อที่เห็นใน CapCut:

```bash
./.venv/bin/edit-capcut inspect --project "Exact Project Name"
```

หากพบหลาย CapCut storage roots ให้รัน:

```bash
./.venv/bin/edit-capcut setup
```

แล้วเลือก root ที่มีโปรเจกต์เป้าหมายจริง

## ตัวอย่างงานที่ทำได้

ทุกตัวอย่างเริ่มด้วย `--dry-run`

### สร้างซับกลางสีขาว

```bash
./.venv/bin/edit-capcut captions \
  --project "Exact Project Name" \
  --preset system-default \
  --dry-run
```

กำหนดจำนวนคำต่อซับได้ เช่น 3 คำ:

```bash
./.venv/bin/edit-capcut captions \
  --project "Exact Project Name" \
  --preset system-default \
  --max-words 3 \
  --dry-run
```

### ตรวจและตัดช่วงเงียบ

```bash
./.venv/bin/edit-capcut silence-cut \
  --project "Exact Project Name" \
  --preset shorts-clean \
  --dry-run
```

### ตรวจเทคพูดซ้ำ

```bash
./.venv/bin/edit-capcut duplicate-takes \
  --project "Exact Project Name" \
  --dry-run
```

### ทำคาราโอเกะสีเหลือง

```bash
./.venv/bin/edit-capcut karaoke \
  --project "Exact Project Name" \
  --preset karaoke-yellow \
  --dry-run
```

### ใช้ Pattern 1

Pattern 1 ต้องมีโปรเจกต์อ้างอิงและ asset ที่ผู้ใช้เป็นเจ้าของ ระบบไม่ได้แจก SFX, effect, font หรือ media มาด้วย

```bash
./.venv/bin/edit-capcut pattern1-apply \
  --project "Target" \
  --reference-project "Local Pattern Reference" \
  --plan "presets/pattern1/my-plan.json" \
  --dry-run
```

## ก่อนเขียนจริงต้องผ่านอะไรบ้าง

เอา `--dry-run` ออกได้เมื่อครบทุกข้อ:

1. เลือกชื่อโปรเจกต์ถูกต้องแบบ exact match
2. ใช้โปรเจกต์ทดสอบหรือมี backup ทั้งโปรเจกต์แล้ว
3. CapCut ปิดสนิท
4. Transcript และ plan ตรงกับ timeline hash ล่าสุด
5. Active `draft_info.json` ทั้งสอง mirror เหมือนกัน
6. Dry-run รายงาน `valid` และไม่มี error
7. Schema fingerprint และฟีเจอร์นั้นมีหลักฐาน `direct_write_validated`

หากระบบแจ้ง `Direct write blocked` ให้หยุดที่ dry-run ห้ามตั้ง environment variable หรือแก้ compatibility gate เพื่อข้ามการป้องกัน ต้องทดสอบด้วย disposable fixture ตามขั้นตอน schema validation ก่อน

เวอร์ชันนี้มีหลักฐาน macOS reopen/read-back สำหรับ neutral captions และ normal-speed silence cuts บน schema ที่ระบุใน `config/capcut_compatibility.json` ฟีเจอร์หรือ schema อื่นอาจถูกบล็อกแม้ dry-run ผ่าน ซึ่งเป็นพฤติกรรมที่ตั้งใจไว้

## หลังเขียนจริง

1. ตรวจว่า mirror ทั้งสองตรงกัน
2. เปิด CapCut
3. เปิดโปรเจกต์เป้าหมายและเล่นผ่านทุกจุดตัด
4. ตรวจคำซับ ภาษาไทย เสียงต้น–ท้ายคำ และความต่อเนื่องของภาพ
5. ปิด CapCut แล้วอ่านตรวจโปรเจกต์ซ้ำ
6. เก็บ backup ไว้จนกว่าจะยืนยันและ Export วิดีโอสำเร็จ

## Troubleshooting

### ไม่พบโปรเจกต์

- เปิด CapCut อย่างน้อยหนึ่งครั้งและสร้างโปรเจกต์ทดสอบ
- ปิด CapCut แล้วรัน `edit-capcut setup`
- ใช้ชื่อโปรเจกต์ตามที่แสดงใน CapCut แบบตรงทุกตัวอักษร

### Permission denied

เปิด System Settings → Privacy & Security → Files and Folders แล้วอนุญาตให้แอปที่ใช้รัน Agent เข้าถึง `Movies` หรือ `Library` เฉพาะที่จำเป็น หากองค์กรจัดการเครื่องอยู่ ให้ติดต่อผู้ดูแลก่อน

### ไม่มี ElevenLabs API key

ระบบยังค้นหา ตรวจ schema, validate และใช้ cache เดิมได้ แต่ไม่สามารถถอดเสียงใหม่ได้

### Direct write ถูกบล็อก

แปลว่า schema หรือฟีเจอร์ยังไม่มีหลักฐานเพียงพอบน Mac เครื่องนั้น ให้ใช้ dry-run ต่อไป อย่าข้าม safety gate และอย่าใช้โปรเจกต์จริงเป็น fixture

### โปรเจกต์ไปอยู่ Recycle Bin ของ CapCut

หยุดเขียนทันที ใช้คำสั่ง Restore ภายใน CapCut ก่อน อย่าย้ายโฟลเดอร์หรือแก้ `root_meta_info.json` เองหากไม่มี backup และขั้นตอน recovery ที่ตรวจสอบแล้ว

## ถอน Runtime

ลบเฉพาะ `.venv` ของแพ็กเกจโดยไม่แตะโปรเจกต์ CapCut:

```bash
sh uninstall.sh --remove-environment
```

สคริปต์นี้ไม่ลบโปรเจกต์ CapCut และไม่ลบสำเนาสกิลที่ติดตั้งใน workspace ของ Codex/Claude ให้ตรวจ destination แล้วลบสำเนาสกิลด้วยตนเองเมื่อแน่ใจว่าไม่ใช้งานต่อ

## ตรวจความถูกต้องของไฟล์แจกจ่าย

หากได้รับไฟล์ checksum มาพร้อม ZIP ให้รันจากโฟลเดอร์ที่มีไฟล์ทั้งหมด:

```bash
shasum -a 256 -c Pleum-CapcutEdit-macOS-checksums.txt
```

ทุกบรรทัดควรลงท้ายด้วย `OK`
