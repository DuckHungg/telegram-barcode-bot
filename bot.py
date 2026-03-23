import os
import cv2
import gspread
import re
from pyzbar.pyzbar import decode, ZBarSymbol
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ==========================================
# 1. CẤU HÌNH
# ==========================================
TOKEN = "8196905397:AAEgGhNZq_ziZt4qce0YVAAOxiXZbeJPxtM"
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"
LOCAL_JSON = "serviceaccountjson-460918-3c9ddf6c02df.json"

BARCODE_TYPES = [ZBarSymbol.QRCODE, ZBarSymbol.CODE128, ZBarSymbol.CODE39, ZBarSymbol.EAN13]

def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(LOCAL_JSON, scope)
        return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
    except: return None

sheet = connect_sheet()

# ==========================================
# 2. ĐỒNG BỘ TỪ KHÓA (KHÔNG NHẬN NHẦM)
# ==========================================
def clean_vntxt(text):
    if not text: return ""
    s = text.lower().strip()
    s = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', s)
    s = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', s)
    s = re.sub(r'[ìíịỉĩ]', 'i', s)
    s = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', s)
    s = re.sub(r'[ùúụủũưừứựửữ]', 'u', s)
    s = re.sub(r'[ỳýỵỷỹ]', 'y', s)
    s = re.sub(r'[đ]', 'd', s)
    return s

def get_synced_condition(text):
    if not text: return None
    txt = clean_vntxt(text)
    words = txt.split()

    # DANH SÁCH ĐỒNG BỘ (Thêm bớt tùy ý bạn)
    # Trạng thái giao nhận
    if "cho lay" in txt: return "CHỜ LẤY"
    if "dang lay" in txt: return "ĐANG LẤY"
    if "dang giao" in txt: return "ĐANG GIAO"
    if "da giao" in txt: return "ĐÃ GIAO"
    if "cho tra" in txt: return "CHỜ TRẢ"
    if "da tra" in txt: return "ĐÃ TRẢ"
    if "huy" in txt: return "HỦY"
    
    # Loại lỗi (Ưu tiên kiểm tra cụm từ dài trước)
    if any(x in txt for x in ["rach uot", "uot rach"]): return "RÁCH ƯỚT"
    if any(x in txt for x in ["be uot", "uot be"]): return "BỂ ƯỚT"
    if any(x in txt for x in ["be", "vo", "nat", "mop"]): return "BỂ VỠ"
    if any(x in txt for x in ["rach", "bung", "thung"]) or ("ho" in words): return "BUNG RÁCH"
    if any(x in txt for x in ["mat", "thieu", "rong"]): return "MẤT RUỘT"
    
    return "KHÁC"

# ==========================================
# 3. QUÉT MÃ
# ==========================================
def scan_logic(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    results = decode(gray, symbols=BARCODE_TYPES)
    return results[0].data.decode("utf-8") if results else None

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    caption = (msg.caption or "").strip()
    
    # Lấy điều kiện duy nhất
    condition = get_synced_condition(caption)
    if not condition: return # Không có chữ thì không làm gì

    temp_file = f"temp_{msg.chat_id}"
    try:
        # Tải file
        if msg.photo:
            file = await msg.photo[-1].get_file()
            temp_file += ".jpg"
            await file.download_to_drive(temp_file)
            img = cv2.imread(temp_file)
            barcode = scan_logic(img)
        elif msg.video or msg.video_note:
            v_obj = msg.video or msg.video_note
            file = await v_obj.get_file()
            temp_file += ".mp4"
            await file.download_to_drive(temp_file)
            cap = cv2.VideoCapture(temp_file)
            barcode, f_id = None, 0
            while cap.isOpened() and f_id < 400:
                ret, frame = cap.read()
                if not ret: break
                if f_id % 6 == 0:
                    barcode = scan_logic(frame)
                    if barcode: break
                f_id += 1
            cap.release()
        else: return

        if barcode and sheet:
            # Ghi vào Sheet: [Thời gian, Mã, Nội dung/Điều kiện, Caption gốc]
            sheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                barcode, 
                condition, 
                caption
            ])
            await msg.reply_text(f"✅ **ĐÃ GHI NHẬN**\n📦 `{barcode}`\n📌 Phân loại: **{condition}**", parse_mode="Markdown")
        elif not barcode:
            await msg.reply_text("❌ Không tìm thấy mã vạch/QR.")

    except Exception as e: print(f"Lỗi: {e}")
    finally:
        if os.path.exists(temp_file): os.remove(temp_file)

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not sheet: return
    today = datetime.now().strftime("%Y-%m-%d")
    all_rows = sheet.get_all_values()
    count = sum(1 for r in all_rows[1:] if r[0].startswith(today))
    await update.message.reply_text(f"📊 Hôm nay đã quét: `{count}` đơn.")

if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("report", send_report))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE, handle_media))
    print("🚀 Bot ĐỒNG BỘ đang chạy...")
    app.run_polling(drop_pending_updates=True)
