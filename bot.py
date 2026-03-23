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
# CONFIG (ENV cho Render)
# ==========================================
TOKEN = os.environ.get("BOT_TOKEN")
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"

def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1

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
# PHÂN LOẠI LỖI
# ==========================================
def classify_issue(text):
    if not text: return None
    txt = clean_vntxt(text)

    is_wet = any(x in txt for x in ["uot", "nuoc", "am", "tham"])
    is_torn = any(x in txt for x in ["rach", "bung", "thung", "ho"])
    is_broken = any(x in txt for x in ["be", "vo", "nat", "gay", "mop"])

    if is_torn and is_wet: return "RÁCH ƯỚT"
    if is_broken and is_wet: return "BỂ ƯỚT"
    if is_broken: return "BỂ VỠ"
    if is_torn: return "BUNG RÁCH"
    if any(x in txt for x in ["mat", "thieu", "rong"]): return "MẤT RUỘT"

    return None

# ==========================================
# PHÂN LOẠI TRẠNG THÁI MỚI
# ==========================================
def classify_status(text):
    if not text: return None
    txt = clean_vntxt(text)

    if "cho lay" in txt: return "CHỜ LẤY"
    if "dang lay" in txt: return "ĐANG LẤY"
    if "dang giao" in txt: return "ĐANG GIAO"
    if "da giao" in txt: return "ĐÃ GIAO"
    if "cho tra" in txt: return "CHỜ TRẢ"
    if "da tra" in txt: return "ĐÃ TRẢ"
    if "huy" in txt: return "HỦY"
    if "that lac" in txt: return "THẤT LẠC"

    return None

# ==========================================
# QUÉT VIDEO
# ==========================================
def scan_barcode_from_video(video_path):
    cap = cv2.VideoCapture(video_path)
    count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        if count % 6 == 0:
            results = decode(frame)
            if results:
                cap.release()
                return results[0].data.decode("utf-8")
        count += 1
        if count > 400: break
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

    # chỉ xử lý nếu có ít nhất 1 trong 2
    if not issue and not status:
        return

    user_name = msg.from_user.full_name
    temp_file = f"temp_{msg.chat_id}"

    try:
        # tải file
        if msg.photo:
            file = await msg.photo[-1].get_file()
            temp_file += ".jpg"
            await file.download_to_drive(temp_file)
            img = cv2.imread(temp_file)
            results = decode(img)
            barcode = results[0].data.decode("utf-8") if results else None

        elif msg.video or msg.video_note:
            v_obj = msg.video or msg.video_note
            file = await v_obj.get_file()
            temp_file += ".mp4"
            await file.download_to_drive(temp_file)
            barcode = scan_barcode_from_video(temp_file)

        else:
            return

        # lưu sheet
        if barcode and sheet:
            sheet.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                barcode,
                issue if issue else "",
                status if status else "",
                user_name,
                caption
            ])

            # gửi lại ảnh + caption
            if msg.photo:
                with open(temp_file, "rb") as p:
                    await msg.reply_photo(
                        photo=p,
                        caption=(
                            f"✅ OK\n"
                            f"📦 {barcode}\n"
                            f"⚠️ {issue if issue else '-'}\n"
                            f"📍 {status if status else '-'}"
                        )
                    )
            else:
                await msg.reply_text(
                    f"✅ OK\n📦 {barcode}\n⚠️ {issue}\n📍 {status}"
                )

        elif not barcode:
            await msg.reply_text("❌ Không đọc được mã")

    except Exception as e:
        print(e)

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

    print("Bot running...")
    app.run_polling()
