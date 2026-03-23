import os
import cv2
import json
import gspread
import re
from pyzbar.pyzbar import decode, ZBarSymbol
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ==========================================
# 1. CẤU HÌNH HỆ THỐNG
# ==========================================
TOKEN = "8196905397:AAEgGhNZq_ziZt4qce0YVAAOxiXZbeJPxtM"
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"
LOCAL_JSON = "serviceaccountjson-460918-3c9ddf6c02df.json"

# Cấu hình quét: QR Code và các loại Mã vạch đơn hàng phổ biến
BARCODE_TYPES = [
    ZBarSymbol.QRCODE, 
    ZBarSymbol.CODE128, 
    ZBarSymbol.CODE39, 
    ZBarSymbol.EAN13
]

def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(LOCAL_JSON, scope)
        return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
    except Exception as e:
        print(f"❌ Lỗi kết nối Sheet: {e}")
        return None

sheet = connect_sheet()

# ==========================================
# 2. XỬ LÝ NGÔN NGỮ & PHÂN LOẠI
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

def classify_issue(text):
    if not text: return ""
    txt = clean_vntxt(text)
    is_wet = any(x in txt for x in ["uot","nuoc","am","tham"])
    is_torn = any(x in txt for x in ["rach","bung","thung","ho"])
    is_broken = any(x in txt for x in ["be","vo","nat","gay","mop"])
    
    if is_torn and is_wet: return "RÁCH ƯỚT"
    if is_broken and is_wet: return "BỂ ƯỚT"
    if is_broken: return "BỂ VỠ"
    if is_torn: return "BUNG RÁCH"
    if any(x in txt for x in ["mat","thieu","rong"]): return "MẤT RUỘT"
    return ""

def classify_status(text):
    if not text: return ""
    txt = clean_vntxt(text)
    mapping = {
        "cho lay":"CHỜ LẤY", "dang lay":"ĐANG LẤY", "dang giao":"ĐANG GIAO", 
        "da giao":"ĐÃ GIAO", "cho tra":"CHỜ TRẢ", "da tra":"ĐÃ TRẢ", 
        "huy":"HỦY", "that lac":"THẤT LẠC"
    }
    for k, v in mapping.items():
        if k in txt: return v
    return ""

# ==========================================
# 3. QUÉT MÃ (ẢNH & VIDEO) - FIX WARNING
# ==========================================
def scan_logic(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # symbols=BARCODE_TYPES giúp chặn lỗi PDF417 Assertion Failed
    results = decode(gray, symbols=BARCODE_TYPES)
    if results:
        return results[0].data.decode("utf-8")
    # Thử tăng độ tương phản nếu không tìm thấy
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    results = decode(thresh, symbols=BARCODE_TYPES)
    return results[0].data.decode("utf-8") if results else None

def scan_video(path):
    cap = cv2.VideoCapture(path)
    f_id = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or f_id > 500: break
        if f_id % 5 == 0:
            barcode = scan_logic(frame)
            if barcode:
                cap.release()
                return barcode
        f_id += 1
    cap.release()
    return None

# ==========================================
# 4. TÍNH NĂNG BÁO CÁO TỔNG HỢP (/report)
# ==========================================
async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not sheet: return
    today = datetime.now().strftime("%Y-%m-%d")
    all_rows = sheet.get_all_values()
    
    issues_count = {}
    status_count = {}
    total_today = 0

    for row in all_rows[1:]: # Bỏ qua tiêu đề
        if row[0].startswith(today):
            total_today += 1
            # Thống kê lỗi (Cột C)
            iss = row[2] if len(row) > 2 and row[2] else "KHÔNG LỖI"
            issues_count[iss] = issues_count.get(iss, 0) + 1
            # Thống kê trạng thái (Cột D)
            sta = row[3] if len(row) > 3 and row[3] else "KHÔNG TRẠNG THÁI"
            status_count[sta] = status_count.get(sta, 0) + 1

    report_msg = f"📊 **BÁO CÁO TỔNG HỢP ({today})**\n"
    report_msg += f"━━━━━━━━━━━━━━━━━━\n"
    report_msg += f"📦 **Tổng đơn đã xử lý:** `{total_today}`\n\n"
    
    report_msg += "⚠️ **PHÂN LOẠI LỖI:**\n"
    for k, v in issues_count.items():
        report_msg += f" • {k}: `{v}`\n"
    
    report_msg += "\n📍 **TRẠNG THÁI:**\n"
    for k, v in status_count.items():
        report_msg += f" • {k}: `{v}`\n"

    await update.message.reply_text(report_msg, parse_mode="Markdown")

# ==========================================
# 5. XỬ LÝ TIN NHẮN CHÍNH
# ==========================================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # Lấy text từ caption hoặc text tin nhắn
    caption = (msg.caption or "").strip()
    issue = classify_issue(caption)
    status = classify_status(caption)

    # Chỉ xử lý khi có từ khóa Lỗi hoặc Trạng thái
    if not issue and not status:
        return

    temp_file = f"temp_{msg.chat_id}"
    try:
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
            barcode = scan_video(temp_file)
        else: return

        if barcode and sheet:
            # Ghi vào Sheet: [Thời gian, Mã, Lỗi, Trạng thái, Caption gốc, Người gửi]
            sheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                barcode, issue, status, caption, msg.from_user.full_name
            ])
            await msg.reply_text(f"✅ **GHI THÀNH CÔNG**\n📦 `{barcode}`\n⚠️ {issue or '-'}\n📍 {status or '-'}", parse_mode="Markdown")
        elif not barcode:
            await msg.reply_text("❌ Không tìm thấy QR/Barcode hợp lệ.")

    except Exception as e:
        print(f"Lỗi hệ thống: {e}")
    finally:
        if os.path.exists(temp_file): os.remove(temp_file)

# ==========================================
# 6. KHỞI CHẠY BOT
# ==========================================
if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    
    # Lệnh báo cáo
    app.add_handler(CommandHandler("report", send_report))
    
    # Xử lý media
    media_filter = filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE
    app.add_handler(MessageHandler(media_filter, handle_media))

    print("🚀 Bot vận hành: QR/Barcode + Video + Báo cáo /report")
    app.run_polling(drop_pending_updates=True)
