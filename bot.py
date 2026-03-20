import os
import cv2
from pyzbar.pyzbar import decode
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN chưa được thiết lập")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()

    input_path = "input.jpg"
    await file.download_to_drive(input_path)

    img = cv2.imread(input_path)
    results = decode(img)

    output_text = []

    for obj in results:
        data = obj.data.decode("utf-8")
        output_text.append(data)

        x, y, w, h = obj.rect
        cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(img, data, (x, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    output_path = "output.jpg"
    cv2.imwrite(output_path, img)

    if output_text:
        await update.message.reply_photo(photo=open(output_path, "rb"))
        await update.message.reply_text("\n".join(output_text))
    else:
        await update.message.reply_text("Không phát hiện mã")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

app.run_polling()
