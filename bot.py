import os
import cv2
import json
import gspread
import re
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ==========================================
# 1. CẤU HÌNH BIẾN MÔI TRƯỜNG
# ==========================================
TOKEN = os.environ.get("BOT_TOKEN")
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"

# ==========================================
# 2. KẾT NỐI GOOGLE SHEET
# ==========================================
def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if not creds_json:
            print("❌ Thiếu biến GOOGLE_CREDENTIALS_JSON")
            return None
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        print(f"❌ Lỗi kết nối Sheet: {e}")
        return None

sheet = connect_sheet()

# ==========================================
# 3. CHUẨN HÓA TIẾNG VIỆT (Fix lỗi nhận diện "BỂ VỠ")
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
    if not text: return "KHÁC"
    txt = clean_vntxt(text)

    is_wet = any(x in txt for x in ["uot", "nuoc", "uoc", "dich", "am", "tham"])
    is_broken = any(x in txt for x in ["be", "vo", "nat", "gay", "mop"])
    is_torn = any(x in txt for x in ["bung", "rach", "ho", "thung", "toat"])
    is_missing = any(x in txt for x in ["mat", "thieu", "rong", "trong"])

    if is_broken and is_wet: return "BỂ ƯỚT"
    if is_torn and is_wet: return "RÁCH ƯỚT"
    if is_broken: return "BỂ VỠ"
    if is_torn: return "BUNG RÁCH"
    if is_missing: return "MẤT RUỘT"
    return "KHÁC"

# ==========================================
# 4. QUÉT MÃ VẠCH BẰNG OPENCV (Thay thế pyzbar)
# ==========================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    temp_path = f"img_{update.message.chat_id}.jpg"
    try:
        caption = update.message.caption or ""
        
        # Tải ảnh từ Telegram
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_to_drive(temp_path)

        # Đọc ảnh
        img = cv2.imread(temp_path)
        if img is None:
            await update.message.reply_text("❌ Lỗi định dạng ảnh.")
            return

        barcode = None
        
        # Thử quét Barcode
        try:
            bd = cv2.barcode.BarcodeDetector()
            retval, decoded_info, _, _ = bd.detectAndDecode(img)
            if retval and decoded_info[0]:
                barcode = decoded_info[0]
        except: pass

        # Nếu không thấy, thử quét QR Code
        if not barcode:
            qr_detector = cv2.QRCodeDetector()
            retval, info, _, _ = qr_detector.detectAndDecode(img)
            if retval:
                barcode = info

        if not barcode:
            await update.message.reply_text("❌ Không tìm thấy mã vạch hoặc mã QR.")
            return

        # Phân loại lỗi và lưu dữ liệu
        issue = classify_issue(caption)
        user = update.message.from_user.full_name

        if sheet:
            sheet.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
                barcode, issue, user, caption
            ])
            await update.message.reply_text(
                f"✅ **GHI NHẬN THÀNH CÔNG**\n"
                f"📦 Mã: `{barcode}`\n"
                f"⚠️ Lỗi: **{issue}**\n"
                f"👤 NV: {user}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❗ Lỗi kết nối Google Sheets.")

    except Exception as e:
        print(f"Lỗi hệ thống: {e}")
        await update.message.reply_text("❗ Đã xảy ra lỗi khi xử lý ảnh.")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# ==========================================
# 5. KHỞI CHẠY
# ==========================================
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Thiếu BOT_TOKEN trong Environment Variables")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        print("🚀 Bot đang chạy ngầm trên Render...")
        app.run_polling(drop_pending_updates=True)
