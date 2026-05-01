from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from supabase import create_client
import os, random, datetime

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ.get("LINE_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

TAROT_CARDS = [
    "愚者", "魔術師", "女祭司", "女皇", "皇帝", "教皇", "戀人", "戰車",
    "力量", "隱者", "命運之輪", "正義", "倒吊人", "死神", "節制", "惡魔",
    "高塔", "星星", "月亮", "太陽", "審判", "世界"
]

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text.strip()

    card = random.choice(TAROT_CARDS)
    is_reversed = random.choice([True, False])
    orientation = "逆位" if is_reversed else "正位"

    prompt = f"""你是一位溫柔神秘的塔羅占卜師。
用戶的問題是：「{user_msg}」
抽到的牌是：{card}（{orientation}）
請用繁體中文給出約150字的占卜解讀，語氣溫柔有詩意。"""

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)
    reply_text = f"🃏 你抽到了【{card}｜{orientation}】\n\n{response.text}"

    # 儲存到 Supabase
    try:
        supabase.table("tarot_logs").insert({
            "user_id": user_id,
            "question": user_msg,
            "card": f"{card}｜{orientation}",
            "response": response.text,
            "created_at": datetime.datetime.utcnow().isoformat()
        }).execute()
    except:
        pass

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
