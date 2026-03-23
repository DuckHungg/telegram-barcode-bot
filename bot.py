import os
import cv2
import json
import gspread
import re
from pyzbar.pyzbar import decode
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ==========================================
# CONFIG
# ==========================================
TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN")
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"
LOCAL_JSON = "serviceaccountjson-460918-3c9ddf6c02df.json"

# ==========================================
# GOOGLE SHEET
# ==========================================
def connect_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if "GOOGLE_CREDENTIALS_JSON" in os.environ:
        creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name(LOCAL_JSON, scope)

    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1

    # đảm bảo header đúng
    header = ["Time", "Barcode", "Issue", "Status"]
    if sheet.row_values(1) != header:
        sheet.insert_row(header, 1)

    return sheet

sheet = connect_sheet()

# ==========================================
# CLEAN TEXT
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

# ==========================================
# PHÂN LOẠI
# ==========================================
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

    if "cho lay" in txt: return "CHỜ LẤY"
    if "dang lay" in txt: return "ĐANG LẤY"
    if "dang giao" in txt: return "ĐANG GIAO"
    if "da giao" in txt: return "ĐÃ GIAO"
    if "cho tra" in txt: return "CHỜ TRẢ"
    if "da tra" in txt: return "ĐÃ TRẢ"
    if "huy" in txt: return "HỦY"
    if "that lac" in txt: return "THẤT LẠC"

    return ""

# ==========================================
# TĂNG ĐỘ NHẠY QUÉT
# ==========================================
def scan_image_advanced(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # nhiều phương án xử lý ảnh
    variants = [
        gray,
        cv2.GaussianBlur(gray, (5,5), 0),
        cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY,11,2)
    ]

    for var in variants:
        results = decode(var)
        if results:
            return results[0].data.decode("utf-8")

    return None

def scan_barcode_from_video(video_path):
    cap = cv2.VideoCapture(video_path)
    count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        if count % 3 == 0:  # tăng tần suất scan
            barcode = scan_image_advanced(frame)
            if barcode:
                cap.release()
                return barcode

        count += 1
        if count > 600: break

    cap.release()
    return None

# ==========================================
# HANDLE
# ==========================================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    caption = (msg.caption or "").strip()

    issue = classify_issue(caption)
    status = classify_status(caption)

    if not issue and not status:
        return

    temp_file = f"temp_{msg.chat_id}"

    try:
        if msg.photo:
            file = await msg.photo[-1].get_file()
            temp_file += ".jpg"
            await file.download_to_drive(temp_file)

            img = cv2.imread(temp_file)
            barcode = scan_image_advanced(img)

        elif msg.video or msg.video_note:
            file = await (msg.video or msg.video_note).get_file()
            temp_file += ".mp4"
            await file.download_to_drive(temp_file)

            barcode = scan_barcode_from_video(temp_file)

        else:
            return

        if barcode:
            sheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                barcode,
                issue,
                status
            ])

            # trả lại ảnh
            if msg.photo:
                with open(temp_file, "rb") as p:
                    await msg.reply_photo(
                        photo=p,
                        caption=f"📦 {barcode}\n⚠️ {issue or '-'}\n📍 {status or '-'}"
                    )
            else:
                await msg.reply_text(f"📦 {barcode}")

        else:
            await msg.reply_text("❌ Không đọc được mã")

    except Exception as e:
        print("Lỗi:", e)

    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

# ==========================================
# RUN
# ==========================================
if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()

    media_filter = filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE
    app.add_handler(MessageHandler(media_filter, handle_media))

    print("🚀 Bot tối ưu đang chạy...")
    app.run_polling()
