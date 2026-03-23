import os
import cv2
import gspread
import re
import asyncio
from pyzbar.pyzbar import decode, ZBarSymbol
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ==========================================
# 1. CẤU HÌNH & BỘ NHỚ
# ==========================================
TOKEN = "8196905397:AAEgGhNZq_ziZt4qce0YVAAOxiXZbeJPxtM"
SHEET_ID = "12ZYDWey6kFsFqAeYnN31BH8rVlDTQXZu8aG62B4JKi4"
LOCAL_JSON = "serviceaccountjson-460918-3c9ddf6c02df.json"

BARCODE_TYPES = [ZBarSymbol.QRCODE, ZBarSymbol.CODE128, ZBarSymbol.CODE39, ZBarSymbol.EAN13]

media_storage = {} 
user_cache = {}

def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(LOCAL_JSON, scope)
        return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
    except: return None

sheet = connect_sheet()

# ==========================================
# 2. LOGIC ĐIỀU KIỆN (GIỮ NGUYÊN)
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
    txt_orig = text.lower().strip()
    txt_no_acc = clean_vntxt(txt_orig)
    status_map = {"cho lay": "CHỜ LẤY", "dang lay": "ĐANG LẤY", "dang giao": "ĐANG GIAO", "da giao": "ĐÃ GIAO", "cho tra": "CHỜ TRẢ", "da tra": "ĐÃ TRẢ", "huy": "HỦY"}
    for k, v in status_map.items():
        if k in txt_no_acc: return v
    if any(x in txt_no_acc for x in ["be", "vo", "nat", "mop"]): return "BỂ VỠ"
    if any(x in txt_no_acc for x in ["rach", "bung", "thung"]) or re.search(r'\b(ho|hở)\b', txt_orig): return "BUNG RÁCH"
    return "KHÁC"

def scan_logic(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    res = decode(gray, symbols=BARCODE_TYPES)
    if not res:
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        res = decode(thresh, symbols=BARCODE_TYPES)
    return res[0].data.decode("utf-8") if res else None

# ==========================================
# 3. XỬ LÝ MEDIA & PHẢN HỒI ĐỦ ALBUM
# ==========================================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = msg.chat_id
    mg_id = msg.media_group_id
    
    # Tạo định danh cho nhóm gửi
    group_key = mg_id if mg_id else f"single_{msg.message_id}_{uid}"
    
    if group_key not in media_storage:
        media_storage[group_key] = {"msgs": [], "caption": "", "processed": False}
    
    # Lưu tin nhắn vào nhóm
    media_storage[group_key]["msgs"].append(msg)
    if msg.caption:
        media_storage[group_key]["caption"] = msg.caption

    # Chờ 2 giây để Telegram đẩy hết ảnh trong album qua
    await asyncio.sleep(2) 
    
    # Kiểm tra nếu chưa được xử lý bởi tin nhắn cùng nhóm khác
    if group_key in media_storage and not media_storage[group_key]["processed"]:
        media_storage[group_key]["processed"] = True
        current_data = media_storage.pop(group_key)
        
        condition = get_synced_condition(current_data["caption"])
        media_results = []
        final_barcode = None

        # Quét TẤT CẢ ảnh trong Album
        for m in current_data["msgs"]:
            barcode = None
            t_path = f"temp_{m.message_id}"
            
            if m.photo:
                t_path += ".jpg"
                f = await m.photo[-1].get_file()
                await f.download_to_drive(t_path)
                barcode = scan_logic(cv2.imread(t_path))
                media_results.append({"type": "photo", "path": t_path})
            
            elif m.video or m.video_note:
                t_path += ".mp4"
                f = await (m.video or m.video_note).get_file()
                await f.download_to_drive(t_path)
                cap = cv2.VideoCapture(t_path)
                # Quét nhanh 30 frame
                for f_id in range(0, 300, 10):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, f_id)
                    ret, frame = cap.read()
                    if not ret: break
                    barcode = scan_logic(frame)
                    if barcode: break
                cap.release()
                media_results.append({"type": "video", "path": t_path})

            if barcode and not final_barcode:
                final_barcode = barcode

        if final_barcode:
            if condition:
                await send_full_group(update, final_barcode, condition, media_results)
            else:
                # Chờ chữ rời
                user_cache[uid] = {"barcode": final_barcode, "media": media_results}
                await asyncio.sleep(5)
                if uid in user_cache:
                    for r in media_results:
                        if os.path.exists(r["path"]): os.remove(r["path"])
                    del user_cache[uid]
        else:
            # Xóa file nếu không tìm thấy mã
            for r in media_results:
                if os.path.exists(r["path"]): os.remove(r["path"])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    condition = get_synced_condition(update.message.text)
    if uid in user_cache and condition:
        data = user_cache.pop(uid)
        await send_full_group(update, data["barcode"], condition, data["media"])

async def send_full_group(update, barcode, condition, media_list):
    if sheet:
        sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), barcode, condition, "Album Record"])
    
    result_txt = f"📦 `{barcode}`\n📌 {condition}"
    final_media_group = []
    
    # Đóng gói TOÀN BỘ file đã tải vào 1 Media Group
    for i, item in enumerate(media_list):
        caption = result_txt if i == 0 else None # Gán chữ vào tấm đầu tiên
        if item["type"] == "photo":
            final_media_group.append(InputMediaPhoto(open(item["path"], 'rb'), caption=caption, parse_mode="Markdown"))
        else:
            final_media_group.append(InputMediaVideo(open(item["path"], 'rb'), caption=caption, parse_mode="Markdown"))

    # Gửi lại toàn bộ cụm
    if final_media_group:
        await update.message.reply_media_group(media=final_media_group)

    # Dọn dẹp sau khi gửi
    for item in media_list:
        if os.path.exists(item["path"]): os.remove(item["path"])

if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    print("🚀 Đã fix lỗi gửi Album: Bạn gửi bao nhiêu - Trả bấy nhiêu!")
    app.run_polling(drop_pending_updates=True)
