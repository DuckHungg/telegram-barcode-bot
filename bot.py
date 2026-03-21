import os
import cv2
import json
import gspread
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ==========================================
# 1. ENV (Lấy từ Environment Variables trên Render)
# ==========================================
TOKEN = os.environ.get("BOT_TOKEN")
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"

# ==========================================
# 2. GOOGLE SHEET
# ==========================================
def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        print(f"Lỗi kết nối Sheet: {e}")
        return None

sheet = connect_sheet()

# ==========================================
# 3. CHUẨN HÓA VÀ PHÂN LOẠI (Nhận diện thông minh)
# ==========================================
def clean_vntxt(text):
    if not text: return ""
    s = text.lower().strip()
    # Loại bỏ dấu tiếng Việt để so khớp chính xác
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

    # Kiểm tra ƯỚT
    is_wet = any(x in txt for x in ["uot", "nuoc", "uoc", "dich", "am", "tham"])
    # Kiểm tra BỂ VỠ
    is_broken = any(x in txt for x in ["be", "vo", "nat", "gay", "mop"])
    # Kiểm tra BUNG RÁCH
    is_torn = any(x in txt for x in ["bung", "rach", "ho", "thung", "toat"])
    # Kiểm tra MẤT RUỘT
    is_missing = any(x in txt for x in ["mat", "thieu", "rong", "trong"])

    if is_broken and is_wet: return "BỂ ƯỚT"
    if is_torn and is_wet: return "RÁCH ƯỚT"
    if is_broken: return "BỂ VỠ"
    if is_torn: return "BUNG RÁCH"
    if is_missing: return "MẤT RUỘT"
    return "KHÁC"

# ==========================================
# 4. XỬ LÝ ẢNH (Dùng OpenCV thay pyzbar)
# ==========================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    temp_path = f"input_{update.message.chat_id}.jpg"
    try:
        caption = update.message.caption or ""
        
        # Tải ảnh
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_to_drive(temp_path)

        # Đọc mã vạch bằng OpenCV BarcodeDetector
        img = cv2.imread(temp_path)
        detector = cv2.barcode.BarcodeDetector()
        retval, decoded_info, decoded_type, points = detector.detectAndDecode(img)

        # Nếu không ra barcode, thử tìm QR code
        if not retval or not decoded_info[0]:
            qr_detector = cv2.QRCodeDetector()
            retval, info, points, _ = qr_detector.detectAndDecode(img)
            barcode = info if retval else None
        else:
            barcode = decoded_info[0]

        if not barcode:
            await update.message.reply_text("❌ Không đọc được mã vạch/QR.")
            return

        # Phân loại và lưu kết quả
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

    except Exception as e:
        await update.message.reply_text(f"❗ Lỗi hệ thống: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# ==========================================
# 5. CHẠY BOT
# ==========================================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print("Bot đang khởi động trên Render...")
    # drop_pending_updates giúp tránh lỗi Conflict khi khởi động lại
    app.run_polling(drop_pending_updates=True)
