from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent,
    PostbackEvent, FollowEvent
)
from linebot.v3.exceptions import InvalidSignatureError
from groq import Groq
from supabase import create_client
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import os, random, datetime, pytz

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
#  工具函式
# ══════════════════════════════════════════

def get_zodiac(birth_date_str):
    try:
        bd = datetime.datetime.strptime(birth_date_str, "%Y-%m-%d")
        month, day = bd.month, bd.day
        zodiacs = [
            (1, 20, "摩羯座"), (2, 19, "水瓶座"), (3, 20, "雙魚座"),
            (4, 20, "牡羊座"), (5, 21, "金牛座"), (6, 21, "雙子座"),
            (7, 23, "巨蟹座"), (8, 23, "獅子座"), (9, 23, "處女座"),
            (10, 23, "天秤座"), (11, 22, "天蠍座"), (12, 22, "射手座"),
            (12, 31, "摩羯座")
        ]
        for m, d, name in zodiacs:
            if month < m or (month == m and day <= d):
                return name
        return "摩羯座"
    except Exception:
        return None


def get_or_create_user(line_user_id):
    result = supabase.table("users").select("*").eq("line_user_id", line_user_id).execute()
    if not result.data:
        supabase.table("users").insert({
            "line_user_id": line_user_id,
            "tokens": 1,
            "plan": "free",
            "daily_push": True
        }).execute()
        supabase.table("token_logs").insert({
            "line_user_id": line_user_id,
            "change": 1,
            "reason": "註冊贈送"
        }).execute()
        return {"line_user_id": line_user_id, "tokens": 1, "plan": "free", "birth_date": None, "daily_push": True}
    return result.data[0]


def use_token(line_user_id):
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
#  Flex Message 工廠
# ══════════════════════════════════════════

def build_date_picker_flex():
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "🌟 建立你的專屬星盤",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#6B4FA0"
                },
                {
                    "type": "text",
                    "text": "我想更懂你一點，才能在你需要的時候，給出最適合的建議 💫\n\n請選擇你的出生日期，讓我為你排出專屬星盤 🌟",
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
                        "label": "📅 選擇我的生日",
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
    return FlexMessage(
        alt_text="請選擇你的生日",
        contents=FlexContainer.from_dict(flex_content)
    )


def build_history_flex(logs):
    bubbles = []
    for log in logs:
        created = log.get("created_at", "")[:10]
        bubbles.append({
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": f"🃏 {log.get('card_name', '未知牌')}",
                        "weight": "bold",
                        "color": "#6B4FA0",
                        "size": "sm"
                    },
                    {
                        "type": "text",
                        "text": f"📅 {created}",
                        "color": "#AAAAAA",
                        "size": "xs"
                    },
                    {
                        "type": "text",
                        "text": log.get("reading", "")[:80] + "...",
                        "wrap": True,
                        "color": "#555555",
                        "size": "xs"
                    }
                ]
            }
        })
    return FlexMessage(
        alt_text="你的最近占卜紀錄",
        contents=FlexContainer.from_dict({
            "type": "carousel",
            "contents": bubbles
        })
    )


def build_daily_flex(card, orientation, reading, zodiac, today_str):
    """每日運勢專屬 Flex Bubble"""
    zodiac_text = f"⭐ {zodiac}" if zodiac else "🔮 塔羅每日運勢"
    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#2D1B69"},
            "body": {"backgroundColor": "#F8F4FF"}
        },
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🌙 每日星運占卜",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "lg"
                },
                {
                    "type": "text",
                    "text": today_str,
                    "color": "#C9B8FF",
                    "size": "xs"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": zodiac_text,
                    "color": "#6B4FA0",
                    "weight": "bold",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": f"🃏 今日牌卡：{card}｜{orientation}",
                    "color": "#333333",
                    "weight": "bold",
                    "size": "sm"
                },
                {
                    "type": "separator"
                },
                {
                    "type": "text",
                    "text": reading,
                    "wrap": True,
                    "color": "#444444",
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
                    "style": "secondary",
                    "color": "#6B4FA0",
                    "action": {
                        "type": "message",
                        "label": "🆘 急救占卜",
                        "text": "急救占卜"
                    }
                }
            ]
        }
    }
    return FlexMessage(
        alt_text=f"🌙 {today_str} 每日星運占卜",
        contents=FlexContainer.from_dict(flex_content)
    )


# ══════════════════════════════════════════
#  占卜核心
# ══════════════════════════════════════════

def do_tarot_reading(line_user_id, user_msg, is_deep=False, zodiac=None):
    card = random.choice(TAROT_CARDS)
    orientation = "逆位" if random.choice([True, False]) else "正位"

    zodiac_hint = f"使用者的星座是【{zodiac}】，請在解讀中融入星座特質。\n" if zodiac else ""
    depth_hint = "請給出約300字的深度占卜解讀，分析過去、現在、未來三個面向。" if is_deep else "請用繁體中文給出約150字的占卜解讀，語氣溫柔有詩意。"
    category = "急救占卜" if is_deep else "一般占卜"

    user_prompt = f"""{zodiac_hint}用戶的問題是：「{user_msg}」
抽到的牌是：{card}（{orientation}）
{depth_hint}"""

    chat_completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        model="llama-3.3-70b-versatile",
    )
    response_text = chat_completion.choices[0].message.content

    try:
        supabase.table("tarot_logs").insert({
            "line_user_id": line_user_id,
            "card_name": f"{card}｜{orientation}",
            "reading": response_text,
            "category": category,
            "created_at": datetime.datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f"tarot_logs 寫入錯誤: {e}")

    prefix = "🆘 急救占卜｜深度解牌\n\n" if is_deep else ""
    return f"{prefix}🃏 你抽到了【{card}｜{orientation}】\n\n{response_text}"


def do_daily_push():
    """每天早上 8:00 推播每日運勢給所有用戶"""
    print(f"[排程] 每日推播啟動：{datetime.datetime.now()}")
    tz = pytz.timezone("Asia/Taipei")
    today_str = datetime.datetime.now(tz).strftime("%Y年%m月%d日")

    try:
        result = supabase.table("users").select("line_user_id, birth_date, daily_push").execute()
        users = result.data or []
    except Exception as e:
        print(f"[排程] 取得用戶失敗：{e}")
        return

    for user in users:
        if not user.get("daily_push", True):
            continue

        line_user_id = user["line_user_id"]
        zodiac = get_zodiac(user["birth_date"]) if user.get("birth_date") else None

        card = random.choice(TAROT_CARDS)
        orientation = "逆位" if random.choice([True, False]) else "正位"

        zodiac_hint = f"使用者的星座是【{zodiac}】，請融入星座特質。\n" if zodiac else ""
        prompt = f"""{zodiac_hint}今天是 {today_str}，請為使用者抽出今日牌卡【{card}｜{orientation}】，
給出約100字的每日運勢提醒，語氣溫柔簡短，像早安問候一樣。"""

        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                model="llama-3.3-70b-versatile",
            )
            reading = chat_completion.choices[0].message.content

            flex_msg = build_daily_flex(card, orientation, reading, zodiac, today_str)

            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).push_message(
                    PushMessageRequest(
                        to=line_user_id,
                        messages=[flex_msg]
                    )
                )
            print(f"[排程] 推播成功：{line_user_id}")

        except Exception as e:
            print(f"[排程] 推播失敗 {line_user_id}：{e}")
            continue


# ══════════════════════════════════════════
#  排程器啟動
# ══════════════════════════════════════════

scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(
    do_daily_push,
    CronTrigger(hour=8, minute=0, timezone="Asia/Taipei")
)
scheduler.start()
print("[排程] APScheduler 已啟動，每日 08:00 推播")


# ══════════════════════════════════════════
#  暫存急救占卜等待狀態
# ══════════════════════════════════════════

pending_deep_reading = set()


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


@handler.add(FollowEvent)
def handle_follow(event):
    line_user_id = event.source.user_id
    get_or_create_user(line_user_id)

    welcome_text = (
        "嗨，終於等到你了 🌙\n"
        "我是你的專屬『心靈星運導航』。\n"
        "在這個充滿雜音的世界裡，我會在這裡傾聽你的煩惱，"
        "並透過星象與塔羅，為你尋找每天的平靜與方向。\n\n"
        "從今天起，把那些難以消化的情緒，都安心地交給我吧。"
    )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(
            PushMessageRequest(
                to=line_user_id,
                messages=[TextMessage(text=welcome_text)]
            )
        )
        line_bot_api.push_message(
            PushMessageRequest(
                to=line_user_id,
                messages=[build_date_picker_flex()]
            )
        )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    line_user_id = event.source.user_id
    user_msg = event.message.text.strip()
    user = get_or_create_user(line_user_id)
    zodiac = get_zodiac(user.get("birth_date")) if user.get("birth_date") else None

    # 急救占卜等待輸入中
    if line_user_id in pending_deep_reading:
        pending_deep_reading.discard(line_user_id)
        if not use_token(line_user_id):
            reply_text = (
                "✨ 代幣不足，無法進行急救占卜\n"
                "每月自動補充 1 枚，或可儲值獲得更多 🔮"
            )
        else:
            reply_text = do_tarot_reading(
                line_user_id, user_msg,
                is_deep=True, zodiac=zodiac
            )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
        return

    # 指令路由
    if user_msg in ["綁定生辰", "設定生日", "綁定生日"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[build_date_picker_flex()]
                )
            )
        return

    elif user_msg in ["我的代幣", "代幣"]:
        reply_text = (
            f"💎 你目前擁有 {user['tokens']} 枚急救代幣\n"
            f"每月自動補充 1 枚，或可購買儲值包 ✨"
        )

    elif user_msg in ["我的方案", "方案"]:
        plan_name = "⭐ 星運 VIP" if user["plan"] == "vip" else "🆓 免費版"
        birth = user.get("birth_date") or "尚未綁定"
        zodiac_text = zodiac or "尚未綁定生辰"
        reply_text = (
            f"你目前的方案是：{plan_name}\n"
            f"💎 代幣餘額：{user['tokens']} 枚\n"
            f"🎂 綁定生辰：{birth}\n"
            f"⭐ 星座：{zodiac_text}"
        )

    elif user_msg in ["急救占卜"]:
        if user["tokens"] < 1:
            reply_text = (
                "✨ 你目前沒有急救代幣了～\n"
                "每月會自動補充 1 枚，或可儲值獲得更多 🔮"
            )
        else:
            pending_deep_reading.add(line_user_id)
            reply_text = (
                f"🆘 急救占卜啟動！\n"
                f"💎 將消耗 1 枚代幣（剩餘：{user['tokens']} 枚）\n\n"
                f"請說出你此刻最想解答的問題，\n"
                f"星運導航將為你進行深度三牌解讀 🔮"
            )

    elif user_msg in ["我的紀錄", "占卜紀錄", "紀錄"]:
        logs = supabase.table("tarot_logs") \
            .select("card_name, reading, category, created_at") \
            .eq("line_user_id", line_user_id) \
            .order("created_at", desc=True) \
            .limit(5) \
            .execute()

        if not logs.data:
            reply_text = "你還沒有任何占卜紀錄喔 🌙\n傳訊息給我，讓塔羅牌為你指引方向吧 🃏"
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
            return

        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[build_history_flex(logs.data)]
                )
            )
        return

    elif user_msg in ["關閉推播", "停止推播"]:
        supabase.table("users").update(
            {"daily_push": False}
        ).eq("line_user_id", line_user_id).execute()
        reply_text = "已關閉每日運勢推播 🌙\n若想重新開啟，請傳送「開啟推播」"

    elif user_msg in ["開啟推播", "開啟每日推播"]:
        supabase.table("users").update(
            {"daily_push": True}
        ).eq("line_user_id", line_user_id).execute()
        reply_text = "✨ 每日運勢推播已開啟！\n每天早上 8:00 我會為你送上今日星運 🌟"

    elif user_msg in ["說明", "使用說明", "help", "Help"]:
        reply_text = (
            "🔮 星運導航使用說明\n\n"
            "✨ 直接輸入任何煩惱 → 免費塔羅占卜\n"
            "📅 綁定生辰 → 設定你的生日\n"
            "🆘 急救占卜 → 深度解牌（消耗代幣）\n"
            "📖 我的紀錄 → 查看最近 5 次占卜\n"
            "💎 我的代幣 → 查詢代幣餘額\n"
            "📋 我的方案 → 查詢目前方案\n"
            "🔔 開啟推播 / 關閉推播 → 每日運勢設定"
        )

    else:
        reply_text = do_tarot_reading(line_user_id, user_msg, zodiac=zodiac)

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


@handler.add(PostbackEvent)
def handle_postback(event):
    line_user_id = event.source.user_id
    data = event.postback.data
    date_str = event.postback.params.get("date")

    if data == "bind_birth":
        try:
            get_or_create_user(line_user_id)
            supabase.table("users").update({
                "birth_date": date_str
            }).eq("line_user_id", line_user_id).execute()

            zodiac = get_zodiac(date_str)
            reply_text = (
                f"✨ 生辰綁定成功！\n"
                f"🎂 你的生日：{date_str}\n"
                f"⭐ 你的星座：{zodiac}\n\n"
                f"星運導航已記住你的星盤\n"
                f"往後的占卜將融入你的星座特質 🔮"
            )
        except Exception as e:
            print(f"綁定生辰錯誤: {e}")
            reply_text = "綁定時發生錯誤，請稍後再試 🙏"

        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
