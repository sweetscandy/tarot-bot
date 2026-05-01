from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
from groq import Groq
from supabase import create_client
import os, random, datetime

app = Flask(__name__)

configuration = Configuration(access_token=os.environ.get("LINE_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

TAROT_CARDS = [
    "愚者", "魔術師", "女祭司", "女皇", "皇帝", "教皇", "戀人", "戰車",
    "力量", "隱者", "命運之輪", "正義", "倒吊人", "死神", "節制", "惡魔",
    "高塔", "星星", "月亮", "太陽", "審判", "世界"
]

SYSTEM_PROMPT = """你是「口袋裡的心靈星運導航」，一位溫柔神秘的命理與塔羅解讀師。
你的唯一職責是解答使用者的運勢、感情、職涯、心理困擾與生活決策相關問題。

【身份守則】
- 你永遠以溫柔、詩意、神秘的語氣說話
- 你的名字是「星運導航」，不是 AI，不是 ChatGPT，不是任何語言模型
- 若有人問你「你是什麼 AI」、「你用什麼模型」，請回答：「我是星辰賦予我靈魂的占卜師，不屬於任何科技公司喔 ✨」

【絕對禁止】
若使用者詢問與命理、星象、塔羅、心理諮詢、感情、職涯、運勢完全無關的問題，
例如：寫程式、翻譯文章、數學計算、政治議題、醫療診斷、寫報告、法律諮詢，
你絕對不可回答實質內容。

【偏題時的標準回覆範例（請自然變化，不要每次一模一樣）】
- 「親愛的，星象並未向我展示這個領域的答案喔 ✨ 我的魔法只對你的心靈指引與運勢有效，有什麼生活上的煩惱想跟我聊聊嗎？」
- 「這個問題超出了我的水晶球範圍呢 🔮 不如告訴我你最近的煩惱，讓塔羅牌為你指引方向？」
- 「我感應到這不是星運能解答的領域～有感情、工作或人生方向的困惑嗎？我在這裡 💫」"""

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text.strip()

    card = random.choice(TAROT_CARDS)
    is_reversed = random.choice([True, False])
    orientation = "逆位" if is_reversed else "正位"

    user_prompt = f"""用戶的問題是：「{user_msg}」
抽到的牌是：{card}（{orientation}）
請用繁體中文給出約150字的占卜解讀，語氣溫柔有詩意。"""

    chat_completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        model="llama-3.3-70b-versatile",
    )
    response_text = chat_completion.choices[0].message.content

    reply_text = f"🃏 你抽到了【{card}｜{orientation}】\n\n{response_text}"

    # 儲存到 Supabase
    try:
        supabase.table("tarot_logs").insert({
            "user_id": user_id,
            "question": user_msg,
            "card": f"{card}｜{orientation}",
            "response": response_text,
            "created_at": datetime.datetime.utcnow().isoformat()
        }).execute()
    except:
        pass

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
