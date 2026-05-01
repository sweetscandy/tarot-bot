from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, TextMessage,
    FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
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

【偏題時的標準回覆】
- 「親愛的，星象並未向我展示這個領域的答案喔 ✨ 我的魔法只對你的心靈指引與運勢有效，有什麼生活上的煩惱想跟我聊聊嗎？」
- 「這個問題超出了我的水晶球範圍呢 🔮 不如告訴我你最近的煩惱，讓塔羅牌為你指引方向？」
- 「我感應到這不是星運能解答的領域～有感情、工作或人生方向的困惑嗎？我在這裡 💫」"""


# ══════════════════════════════════════════
#  使用者管理
# ══════════════════════════════════════════

def get_or_create_user(line_user_id):
    """查詢使用者，若不存在則自動註冊並贈送 1 枚代幣"""
    result = supabase.table("users").select("*").eq("line_user_id", line_user_id).execute()

    if not result.data:
        supabase.table("users").insert({
            "line_user_id": line_user_id,
            "tokens": 1,
            "plan": "free"
        }).execute()
        supabase.table("token_logs").insert({
            "line_user_id": line_user_id,
            "change": 1,
            "reason": "註冊贈送"
        }).execute()
        # 回傳預設值
        return {"line_user_id": line_user_id, "tokens": 1, "plan": "free", "birth_date": None}

    return result.data[0]


def use_token(line_user_id):
    """消耗 1 枚代幣，回傳是否成功"""
    user = get_or_create_user(line_user_id)
    if user["tokens"] < 1:
        return False

    supabase.table("users").update(
        {"tokens": user["tokens"] - 1}
    ).eq("line_user_id", line_user_id).execute()

    supabase.table("token_logs").insert({
        "line_user_id": line_user_id,
        "change": -1,
        "reason": "急救占卜"
    }).execute()
    return True


# ══════════════════════════════════════════
#  占卜核心
# ══════════════════════════════════════════

def do_tarot_reading(line_user_id, user_msg):
    """執行塔羅占卜並儲存紀錄，回傳回覆文字"""
    card = random.choice(TAROT_CARDS)
    orientation = "逆位" if random.choice([True, False]) else "正位"

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

    # 儲存紀錄
    try:
        supabase.table("tarot_logs").insert({
            "line_user_id": line_user_id,
            "card_name": f"{card}｜{orientation}",
            "reading": response_text,
            "category": "一般占卜",
            "created_at": datetime.datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f"tarot_logs 寫入錯誤: {e}")

    return f"🃏 你抽到了【{card}｜{orientation}】\n\n{response_text}"


# ══════════════════════════════════════════
#  日期選擇器
# ══════════════════════════════════════════

def send_date_picker(reply_token):
    """發送生辰綁定的日期選擇 Flex Message"""
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "🔮 綁定生辰",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#6B4FA0"
                },
                {
                    "type": "text",
                    "text": "請用下方日曆選擇你的生日\n選完後星運導航就能為你量身解讀 ✨",
                    "wrap": True,
                    "color": "#666666",
                    "size": "sm"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#6B4FA0",
                    "action": {
                        "type": "datetimepicker",
                        "label": "📅 選擇生日",
                        "data": "bind_birth",
                        "mode": "date",
                        "initial": "1995-01-01",
                        "min": "1924-01-01",
                        "max": "2010-12-31"
                    }
                }
            ]
        }
    }

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    FlexMessage(
                        alt_text="請選擇你的生日",
                        contents=FlexContainer.from_dict(flex_content)
                    )
                ]
            )
        )


# ══════════════════════════════════════════
#  Webhook 路由
# ══════════════════════════════════════════

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
    line_user_id = event.source.user_id
    user_msg = event.message.text.strip()
    user = get_or_create_user(line_user_id)

    # ── 指令路由 ──
    if user_msg in ["綁定生辰", "設定生日", "綁定生日"]:
        send_date_picker(event.reply_token)
        return

    elif user_msg in ["我的代幣", "代幣"]:
        reply_text = (
            f"💎 你目前擁有 {user['tokens']} 枚急救代幣\n"
            f"每月自動補充 1 枚，或可購買儲值包 ✨"
        )

    elif user_msg in ["我的方案", "方案"]:
        plan_name = "⭐ 星運 VIP" if user["plan"] == "vip" else "🆓 免費版"
        birth = user.get("birth_date") or "尚未綁定"
        reply_text = (
            f"你目前的方案是：{plan_name}\n"
            f"💎 代幣餘額：{user['tokens']} 枚\n"
            f"🎂 綁定生辰：{birth}"
        )

    elif user_msg in ["急救占卜"]:
        if user["tokens"] < 1:
            reply_text = (
                "✨ 你目前沒有急救代幣了～\n"
                "每月會自動補充 1 枚，或可儲值獲得更多 🔮"
            )
        else:
            reply_text = (
                f"🔮 你有 {user['tokens']} 枚代幣\n"
                f"請直接說出你想深度解讀的問題\n"
                f"（下一則訊息將消耗 1 枚代幣）"
            )

    elif user_msg in ["說明", "使用說明", "help", "Help"]:
        reply_text = (
            "🔮 星運導航使用說明\n\n"
            "✨ 直接輸入任何煩惱 → 免費塔羅占卜\n"
            "📅 綁定生辰 → 設定你的生日\n"
            "🆘 急救占卜 → 深度解牌（消耗代幣）\n"
            "💎 我的代幣 → 查詢代幣餘額\n"
            "📋 我的方案 → 查詢目前方案"
        )

    else:
        # 一般免費占卜
        reply_text = do_tarot_reading(line_user_id, user_msg)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理日期選擇器的回傳"""
    line_user_id = event.source.user_id
    data = event.postback.data
    date_str = event.postback.params.get("date")  # 格式：1995-03-12

    if data == "bind_birth":
        try:
            get_or_create_user(line_user_id)
            supabase.table("users").update({
                "birth_date": date_str
            }).eq("line_user_id", line_user_id).execute()
            reply_text = (
                f"✨ 生辰綁定成功！\n"
                f"🎂 你的生日：{date_str}\n\n"
                f"星運導航已記住你的星盤\n"
                f"每日運勢將為你量身解讀 🔮"
            )
        except Exception as e:
            print(f"綁定生辰錯誤: {e}")
            reply_text = "綁定時發生錯誤，請稍後再試 🙏"

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
