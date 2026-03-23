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
TOKEN = os.environ.get("BOT_TOKEN", "8196905397:AAEgGhNZq_ziZt4qce0YVAAOxiXZbeJPxtM")
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"
LOCAL_JSON = "serviceaccountjson-460918-3c9ddf6c02df.json"

# ==========================================
# GOOGLE SHEET (ENV + LOCAL)
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
    return client.open_by_key(SHEET_ID).sheet1

sheet = connect_sheet()

# ==========================================
# LẤY TOÀN BỘ TEXT (FIX FORWARD)
# ==========================================
def get_full_text(msg):
    texts = []

    if msg.caption:
        texts.append(msg.caption)

    if msg.text:
        texts.append(msg.text)

    if msg.reply_to_message:
        if msg.reply_to_message.caption:
            texts.append(msg.reply_to_message.caption)
        if msg.reply_to_message.text:
            texts.append(msg.reply_to_message.text)

    return " ".join(texts).strip()

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
# GHI CHUẨN CỘT (KHÔNG LỆCH)
# ==========================================
def write_row(barcode, issue, status):
    next_row = len(sheet.col_values(1)) + 1

    sheet.update(f"A{next_row}", [[datetime.now().strftime("%Y-%m-%d %H:%M:%S")]])
    sheet.update(f"B{next_row}", [[barcode]])
    sheet.update(f"C{next_row}", [[issue]])
    sheet.update(f"D{next_row}", [[status]])

# ==========================================
# SCAN ẢNH (TỐI ƯU)
# ==========================================
def scan_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    variants = [
        gray,
        cv2.GaussianBlur(gray, (5,5), 0),
        cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
    ]

    for v in variants:
        results = decode(v)
        if results:
            return results[0].data.decode("utf-8")

    return None

# ==========================================
# SCAN VIDEO (PAUSE ẢO)
# ==========================================
def scan_barcode_from_video(video_path):
    cap = cv2.VideoCapture(video_path)

    best_barcode = None
    best_score = 0
    best_frame = None

    frame_id = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_id % 2 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score = cv2.Laplacian(gray, cv2.CV_64F).var()

            results = decode(gray)

            if results and score > best_score:
                best_score = score
                best_barcode = results[0].data.decode("utf-8")
                best_frame = frame.copy()

        frame_id += 1
        if frame_id > 800:
            break

    cap.release()

    if best_frame is not None:
        cv2.imwrite("best_frame.jpg", best_frame)

    return best_barcode, "best_frame.jpg" if best_frame is not None else None

# ==========================================
# HANDLE
# ==========================================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    caption = get_full_text(msg)

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
            barcode = scan_image(img)
            best_img = temp_file

        elif msg.video or msg.video_note:
            file = await (msg.video or msg.video_note).get_file()
            temp_file += ".mp4"
            await file.download_to_drive(temp_file)

            barcode, best_img = scan_barcode_from_video(temp_file)

        else:
            return

        if barcode:
            write_row(barcode, issue, status)

            if best_img and os.path.exists(best_img):
                with open(best_img, "rb") as p:
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
        if os.path.exists("best_frame.jpg"):
            os.remove("best_frame.jpg")

# ==========================================
# RUN
# ==========================================
if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()

    media_filter = filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE | filters.TEXT
    app.add_handler(MessageHandler(media_filter, handle_media))

    print("🚀 Bot FULL đang chạy...")
    app.run_polling()
