import os
import cv2
import json
import gspread
import re
import threading
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==========================================
# 1. SERVER GIẢ (GIỮ BOT CHẠY FREE)
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# ==========================================
# 2. CẤU HÌNH GOOGLE SHEET
# ==========================================
TOKEN = os.environ.get("BOT_TOKEN")
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"

def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
    except: return None

sheet = connect_sheet()

# ==========================================
# 3. CHUẨN HÓA TIẾNG VIỆT
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
    txt = clean_vntxt(text)
    if any(x in txt for x in ["be", "vo", "nat", "gay", "mop"]): return "BỂ VỠ"
    if any(x in txt for x in ["uot", "nuoc", "am", "tham"]): return "ƯỚT"
    if any(x in txt for x in ["rach", "thung", "bung", "ho"]): return "BUNG RÁCH"
    if any(x in txt for x in ["mat", "thieu", "rong"]): return "MẤT RUỘT"
    return "KHÁC"

# ==========================================
# 4. XỬ LÝ QUÉT MÃ NÂNG CAO
# ==========================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    temp_path = f"img_{update.message.chat_id}.jpg"
    try:
        caption = update.message.caption or ""
        f = await update.message.photo[-1].get_file()
        await f.download_to_drive(temp_path)

        # Đọc ảnh và chuyển hệ xám để quét tốt hơn
        img = cv2.imread(temp_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        barcode = None

        # Cách 1: Quét mã QR (Ưu tiên QRCodeDetector vì nó nhanh)
        qr_det = cv2.QRCodeDetector()
        ok, info, _, _ = qr_det.detectAndDecode(img)
        if ok: barcode = info

        # Cách 2: Nếu thất bại, quét Barcode bằng bộ lọc tăng tương phản
        if not barcode:
            bd = cv2.barcode.BarcodeDetector()
            # Thử trên ảnh gốc
            res = bd.detectAndDecode(img)
            if res[0] and res[1][0]:
                barcode = res[1][0]
            else:
                # Thử trên ảnh đã tăng độ nét (Laplacian)
                sharp = cv2.addWeighted(img, 1.5, cv2.GaussianBlur(img, (0,0), 3), -0.5, 0)
                res = bd.detectAndDecode(sharp)
                if res[0] and res[1][0]: barcode = res[1][0]

        if not barcode:
            await update.message.reply_text("❌ Không đọc được mã. Hãy chụp gần hơn và rõ nét nhé!")
            return

        # Ghi dữ liệu
        issue = classify_issue(caption)
        user = update.message.from_user.full_name
        if sheet:
            sheet.append_row([datetime.now().strftime("%d/%m/%Y %H:%M:%S"), barcode, issue, user, caption])
            await update.message.reply_text(f"✅ **GHI NHẬN THÀNH CÔNG**\n📦 Mã: `{barcode}`\n⚠️ Lỗi: **{issue}**", parse_mode="Markdown")
        else:
            await update.message.reply_text("❗ Lỗi kết nối Google Sheets.")

    except Exception as e:
        await update.message.reply_text(f"❗ Lỗi: {str(e)}")
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)

if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("🚀 Bot nâng cấp đang chạy...")
    app.run_polling(drop_pending_updates=True)
