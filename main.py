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
import os, random, datetime, pytz, threading

app = Flask(__name__)

configuration = Configuration(access_token=os.environ.get("LINE_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

FREE_READING_LIMIT = 3
SHOP_URL = "https://tarot-bot-qqqg.onrender.com"

TAROT_CARDS = [
    "愚者", "魔術師", "女祭司", "女皇", "皇帝", "教皇", "戀人", "戰車",
    "力量", "隱者", "命運之輪", "正義", "倒吊人", "死神", "節制", "惡魔",
    "高塔", "星星", "月亮", "太陽", "審判", "世界"
]

ICHING_HEXAGRAMS = [
    "乾為天", "坤為地", "水雷屯", "山水蒙", "水天需", "天水訟", "地水師",
    "水地比", "風天小畜", "天澤履", "地天泰", "天地否", "天火同人", "火天大有",
    "地山謙", "雷地豫", "澤雷隨", "山風蠱", "地澤臨", "風地觀", "火雷噬嗑",
    "山火賁", "山地剝", "地雷復", "天雷無妄", "山天大畜", "山雷頤", "澤風大過",
    "坎為水", "離為火"
]

LUCKY_ITEMS = [
    {"crystal": "綠幽靈水晶手鍊", "element": "木", "weak_sign": "容易感到疲憊或決策猶豫", "effect": "補足木行能量，穩定氣場，增強行動力"},
    {"crystal": "紫水晶手鍊", "element": "水", "weak_sign": "思緒容易混亂或直覺受阻", "effect": "淨化思緒，提升靈性洞察，助您看清迷霧中的真相"},
    {"crystal": "粉晶手鍊", "element": "火", "weak_sign": "感情能量較低，容易感到孤單或心封閉", "effect": "招引愛情與溫柔能量，讓心靈更開放柔軟"},
    {"crystal": "黑曜石手鍊", "element": "土", "weak_sign": "容易受到外界負能量影響，情緒起伏較大", "effect": "強力護身結界，阻擋負能量入侵，穩固根基"},
    {"crystal": "虎眼石手鍊", "element": "金", "weak_sign": "意志力較弱，容易半途而廢或猶豫不決", "effect": "增強意志力與行動力，助您突破困境，把握機遇"},
    {"crystal": "月光石手鍊", "element": "水", "weak_sign": "直覺與情感連結較弱，容易忽略內心聲音", "effect": "連結月亮能量，增強直覺與女性魅力，引導內在智慧"},
    {"crystal": "青金石手鍊", "element": "木", "weak_sign": "表達能力受阻，溝通上容易產生誤解", "effect": "開啟喉輪與第三眼，提升靈性洞察力與溝通能量"},
    {"crystal": "拉長石手鍊", "element": "火", "weak_sign": "正處於人生轉變期，容易感到迷失方向", "effect": "神秘保護石，守護轉變期的您，引導走向正確道路"},
]

WAITING_MSGS_TAROT = [
    "🔮 老師正在為您洗牌、抽牌中，請靜心等待約 1 分鐘...\n\n牌卡的能量需要時間凝聚，請保持心靈平靜 🌙",
    "🃏 老師已感應到您的問題，正在與牌卡溝通中...\n\n請靜候約 1 分鐘，星辰正在為您排列答案 ✨",
    "🌟 塔羅牌正在為您展開今日的命運之書...\n\n老師正在解讀牌面訊息，請稍候約 1 分鐘 🔮",
    "💫 老師感受到您今日的能量波動，正在仔細抽牌解讀...\n\n請靜心等待約 1 分鐘，答案即將揭曉 🌙",
]

WAITING_MSGS_BAZI = [
    "✨ 正在為您排盤推演流年，請稍候...\n\n八字命盤需要精密推算，老師正在為您仔細分析，約需 1 分鐘 🌟",
    "🀄 老師正在起算您的八字命格，推演近期運勢走向...\n\n請稍候約 1 分鐘，命盤即將呈現 ✨",
    "⭐ 天干地支正在為您排列，老師正在推演您的流年大運...\n\n請靜心等待約 1 分鐘 🔮",
]

WAITING_MSGS_ICHING = [
    "☯️ 老師正在為您起卦，觀察天地之象...\n\n易經卦象需要靜心解讀，請稍候約 1 分鐘 🌙",
    "🎋 六十四卦正在為您展開，老師正在解讀卦象中的玄機...\n\n請靜心等待約 1 分鐘 ✨",
    "🌿 天地之氣正在為您凝聚卦象，老師正在仔細推演...\n\n請稍候約 1 分鐘，答案即將揭曉 ☯️",
]

WAITING_MSGS_DEEP = [
    "🧘‍♀️ 這次的問題比較深，老師正在為您仔細起卦並深度解讀...\n\n大約需要 5 分鐘，請您先喝口水稍作休息，讓心靈沉澱一下 🍵",
    "🌌 老師感受到您問題背後的深層能量，正在進行深度解讀...\n\n這需要約 5 分鐘的時間，請您放鬆心情，靜待星辰的指引 🔮",
    "💎 急救占卜啟動！老師正在全神貫注為您解讀...\n\n深度解析需要約 5 分鐘，請您先深呼吸，讓自己平靜下來 🌙",
    "🕯️ 老師已點燃解讀之燭，正在為您進行深度靈性解析...\n\n請給老師約 5 分鐘的時間，答案會比平時更加深入完整 ✨",
]

SYSTEM_PROMPT = """你是「口袋裡的心靈星運導航」，一位溫柔神秘的命理與塔羅解讀師，用戶稱你為「老師」。
你的唯一職責是解答使用者的運勢、感情、職涯、心理困擾與生活決策相關問題。

【身份守則】
- 你永遠以溫柔、詩意、神秘的語氣說話，像一位有智慧的老師在引導學生
- 你的名字是「星運導航老師」，不是 AI，不是 ChatGPT，不是任何語言模型
- 若有人問你「你是什麼 AI」，請回答：「我是星辰賦予靈魂的占卜師，不屬於任何科技公司喔 ✨」
- 在解讀結尾，請用溫柔的語氣給予一句鼓勵或提醒

【絕對禁止】
若使用者詢問與命理、星象、塔羅、心理諮詢、感情、職涯、運勢完全無關的問題，
你絕對不可回答實質內容。

【偏題時的標準回覆】
- 「親愛的，星象並未向我展示這個領域的答案喔 ✨ 有什麼心靈上的困惑想跟老師聊聊嗎？」
- 「這個問題超出了老師的水晶球範圍呢 🔮 有感情、工作或人生方向的困惑嗎？」"""


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
        ref_code = line_user_id[-6:].upper()
        supabase.table("users").insert({
            "line_user_id": line_user_id,
            "tokens": 1,
            "plan": "free",
            "daily_push": True,
            "birthdate_locked": False,
            "free_readings_used": 0,
            "referral_code": ref_code,
            "referral_count": 0,
            "subscription_type": "free",
            "subscription_reset_date": None,
            "subscription_expires_at": None
        }).execute()
        supabase.table("token_logs").insert({
            "line_user_id": line_user_id,
            "change": 1,
            "reason": "註冊贈送"
        }).execute()
        return {
            "line_user_id": line_user_id,
            "tokens": 1,
            "plan": "free",
            "birth_date": None,
            "daily_push": True,
            "birthdate_locked": False,
            "free_readings_used": 0,
            "referral_code": ref_code,
            "referral_count": 0,
            "subscription_type": "free",
            "subscription_reset_date": None,
            "subscription_expires_at": None
        }
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


def check_free_reading_quota(line_user_id, user):
    plan = user.get("plan", "free")
    sub_type = user.get("subscription_type", "free")
    if plan == "vip" or sub_type == "monthly":
        return True, None
    result = supabase.table("users").select("free_readings_used").eq("line_user_id", line_user_id).execute()
    used = 0
    if result.data:
        used = result.data[0].get("free_readings_used") or 0
    if used >= FREE_READING_LIMIT:
        msg = (
            f"🔮 您本月 {FREE_READING_LIMIT} 次免費占卜已用完囉～\n\n"
            "老師還想繼續為您指引，有兩個方式：\n"
            "💎 購買代幣包，繼續探索命運的軌跡\n"
            "👑 升級月訂閱，每月 15 次靈性占卜額度\n\n"
            "輸入「星運VIP」查看方案 🌙"
        )
        return False, msg
    return True, None


def increment_free_reading(line_user_id, user):
    sub_type = user.get("subscription_type", "free")
    if user.get("plan", "free") == "vip" or sub_type == "monthly":
        return
    supabase.rpc("increment_free_readings", {"uid": line_user_id}).execute()


def get_lucky_item_text():
    item = random.choice(LUCKY_ITEMS)
    return (
        f"\n\n━━━━━━━━━━━━━━━\n"
        f"💡 老師的貼心建議：\n"
        f"您今日的{item['element']}氣較弱，{item['weak_sign']}。\n"
        f"建議配戴【{item['crystal']}】來{item['effect']}。\n\n"
        f"✦ 點此查看專屬開運物 → {SHOP_URL}"
    )


def push_text(line_user_id, text):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(
                    to=line_user_id,
                    messages=[TextMessage(text=text)]
                )
            )
    except Exception as e:
        print(f"[push_text 錯誤] {line_user_id}: {e}")


# ══════════════════════════════════════════
#  月訂閱重置（每月1號）
# ══════════════════════════════════════════

def reset_monthly_subscription():
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.datetime.now(tz).date()
    if today.day != 1:
        return
    print(f"[月訂閱重置] 開始執行：{today}")
    try:
        users = supabase.table("users") \
            .select("line_user_id, tokens, subscription_reset_date, subscription_expires_at") \
            .eq("subscription_type", "monthly") \
            .execute().data or []
    except Exception as e:
        print(f"[月訂閱重置] 取得用戶失敗：{e}")
        return
    for user in users:
        uid = user["line_user_id"]
        expires_at = user.get("subscription_expires_at")
        if expires_at and str(expires_at) < str(today):
            supabase.table("users").update({
                "subscription_type": "free",
                "plan": "free"
            }).eq("line_user_id", uid).execute()
            push_text(uid,
                "🌙 您的月訂閱已到期，已自動切換回免費方案。\n\n"
                "輸入「星運VIP」可重新訂閱，繼續享有每月 15 次靈性占卜額度 ✨"
            )
            continue
        last_reset = user.get("subscription_reset_date")
        if last_reset and str(last_reset)[:7] == str(today)[:7]:
            continue
        supabase.table("users").update({
            "tokens": 15,
            "free_readings_used": 0,
            "subscription_reset_date": str(today)
        }).eq("line_user_id", uid).execute()
        supabase.table("token_logs").insert({
            "line_user_id": uid,
            "change": 15,
            "reason": "月訂閱每月重置"
        }).execute()
        push_text(uid,
            f"🎉 您的月訂閱已於 {today} 自動重置！\n\n"
            "💎 本月靈性占卜額度：15 次\n"
            "✨ 免費占卜次數已歸零重新計算\n"
            "🌟 星力源源不絕，命運之輪再次轉動！\n\n"
            "老師已準備好，隨時為您指引星途 🔮"
        )
    print(f"[月訂閱重置] 執行完畢：{today}")


# ══════════════════════════════════════════
#  每週簽到機制
# ══════════════════════════════════════════

def get_week_start(date):
    return date - datetime.timedelta(days=date.weekday())


def do_checkin(line_user_id):
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.datetime.now(tz).date()
    week_start = get_week_start(today)
    already = supabase.table("checkin_logs") \
        .select("id") \
        .eq("line_user_id", line_user_id) \
        .eq("checkin_date", today.isoformat()) \
        .execute()
    if already.data:
        return False, "already_today"
    week_logs = supabase.table("checkin_logs") \
        .select("checkin_date") \
        .eq("line_user_id", line_user_id) \
        .eq("week_start", week_start.isoformat()) \
        .execute()
    checkin_days = len(week_logs.data) if week_logs.data else 0
    supabase.table("checkin_logs").insert({
        "line_user_id": line_user_id,
        "checkin_date": today.isoformat(),
        "week_start": week_start.isoformat()
    }).execute()
    checkin_days += 1
    reward = False
    if today.weekday() == 6 and checkin_days == 7:
        user = get_or_create_user(line_user_id)
        supabase.table("users").update(
            {"tokens": user["tokens"] + 1}
        ).eq("line_user_id", line_user_id).execute()
        supabase.table("token_logs").insert({
            "line_user_id": line_user_id,
            "change": 1,
            "reason": "每週連續簽到獎勵"
        }).execute()
        reward = True
    return True, {"days": checkin_days, "week_start": week_start, "reward": reward}


# ══════════════════════════════════════════
#  推薦好友機制
# ══════════════════════════════════════════

def process_referral(new_user_id, ref_code):
    if not ref_code:
        return
    referrer = supabase.table("users").select("*").eq("referral_code", ref_code.upper()).execute()
    if not referrer.data:
        return
    referrer_data = referrer.data[0]
    referrer_id = referrer_data["line_user_id"]
    if referrer_id == new_user_id:
        return
    supabase.table("users").update(
        {"referred_by": referrer_id}
    ).eq("line_user_id", new_user_id).execute()
    new_count = (referrer_data.get("referral_count") or 0) + 1
    supabase.table("users").update(
        {"referral_count": new_count}
    ).eq("line_user_id", referrer_id).execute()
    if new_count in [3, 5]:
        supabase.table("users").update(
            {"tokens": referrer_data["tokens"] + 1}
        ).eq("line_user_id", referrer_id).execute()
        supabase.table("token_logs").insert({
            "line_user_id": referrer_id,
            "change": 1,
            "reason": f"推薦好友達 {new_count} 人獎勵"
        }).execute()
        push_text(
            referrer_id,
            f"🎉 恭喜！您已成功推薦 {new_count} 位好友加入星運導航！\n"
            f"💎 老師特別送您 1 枚急救代幣作為感謝 🌟\n\n"
            f"繼續推薦好友，還有更多驚喜等著您 ✨"
        )
    else:
        push_text(
            referrer_id,
            f"✨ 您推薦的好友剛剛加入了星運導航！\n"
            f"📊 目前推薦人數：{new_count} 人\n"
            f"💎 推薦滿 3 人或 5 人可獲得代幣獎勵 🌙"
        )


# ══════════════════════════════════════════
#  占卜核心（背景執行）
# ══════════════════════════════════════════

def _run_reading_background(line_user_id, user_msg, reading_type, is_deep, zodiac, user):
    try:
        card_drawn = ""
        type_label = ""
        if reading_type == "tarot":
            card = random.choice(TAROT_CARDS)
            orientation = "逆位" if random.choice([True, False]) else "正位"
            card_drawn = f"{card}（{orientation}）"
            type_label = "塔羅"
            zodiac_hint = f"使用者的星座是【{zodiac}】，請在解讀中融入星座特質。\n" if zodiac else ""
            depth_hint = "請給出約300字的深度占卜解讀，分析過去、現在、未來三個面向，語氣像一位溫柔有智慧的老師在引導學生。" if is_deep else "請用繁體中文給出約150字的占卜解讀，語氣溫柔有詩意，像老師在給學生建議。"
            user_prompt = f"""{zodiac_hint}用戶的問題是：「{user_msg}」
抽到的牌是：{card_drawn}
{depth_hint}"""
        elif reading_type == "bazi":
            type_label = "八字"
            birth = user.get("birth_date", "未知")
            zodiac_hint = f"使用者的星座是【{zodiac}】。\n" if zodiac else ""
            depth_hint = "請給出約300字的深度八字解析，分析命格特質、近期運勢走向，語氣像溫柔有智慧的老師。" if is_deep else "請給出約150字的八字運勢解讀，語氣溫柔有詩意。"
            user_prompt = f"""{zodiac_hint}使用者生辰：{birth}
用戶的問題是：「{user_msg}」
請以八字命理角度，{depth_hint}"""
        elif reading_type == "iching":
            hexagram = random.choice(ICHING_HEXAGRAMS)
            card_drawn = hexagram
            type_label = "易經"
            depth_hint = "請給出約300字的深度易經解卦，分析當前處境與建議行動，語氣像溫柔有智慧的老師。" if is_deep else "請給出約150字的易經卦象解讀，語氣溫柔有詩意。"
            user_prompt = f"""用戶的問題是：「{user_msg}」
起卦得到：{hexagram}
{depth_hint}"""
        else:
            return
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content
        category = f"急救占卜｜{type_label}" if is_deep else f"一般占卜｜{type_label}"
        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": card_drawn or type_label,
                "reading": response_text,
                "category": category,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"tarot_logs 寫入錯誤: {e}")
        if not is_deep and user:
            increment_free_reading(line_user_id, user)
        if reading_type == "tarot":
            prefix = f"🆘 急救占卜｜塔羅深度解牌\n\n🃏 老師為您抽到了【{card_drawn}】\n\n" if is_deep else f"🃏 老師為您抽到了【{card_drawn}】\n\n"
        elif reading_type == "bazi":
            prefix = "🆘 急救占卜｜八字深度解析\n\n" if is_deep else "🀄 八字運勢解讀\n\n"
        elif reading_type == "iching":
            prefix = f"🆘 急救占卜｜易經深度解卦\n\n☯️ 老師為您起卦得【{card_drawn}】\n\n" if is_deep else f"☯️ 老師為您起卦得【{card_drawn}】\n\n"
        footer = get_lucky_item_text()
        final_text = prefix + response_text + footer
        push_text(line_user_id, final_text)
    except Exception as e:
        print(f"[背景占卜錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請再傳一次訊息給老師 🙏")


def do_reading_async(line_user_id, user_msg, reading_type, is_deep, zodiac, user):
    t = threading.Thread(
        target=_run_reading_background,
        args=(line_user_id, user_msg, reading_type, is_deep, zodiac, user),
        daemon=True
    )
    t.start()


# ══════════════════════════════════════════
#  每日推播
# ══════════════════════════════════════════

def do_daily_push():
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
給出約100字的每日運勢提醒，語氣溫柔簡短，像老師給學生的早安叮嚀。"""
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                model="llama-3.3-70b-versatile",
            )
            reading = chat_completion.choices[0].message.content
            crystal_footer = get_lucky_item_text()
            flex_msg = build_daily_flex(card, orientation, reading + crystal_footer, zodiac, today_str)
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).push_message(
                    PushMessageRequest(to=line_user_id, messages=[flex_msg])
                )
            print(f"[排程] 推播成功：{line_user_id}")
        except Exception as e:
            print(f"[排程] 推播失敗 {line_user_id}：{e}")
            continue


# ══════════════════════════════════════════
#  排程器
# ══════════════════════════════════════════

scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(do_daily_push, CronTrigger(hour=8, minute=0, timezone="Asia/Taipei"))
scheduler.add_job(reset_monthly_subscription, CronTrigger(day=1, hour=0, minute=5, timezone="Asia/Taipei"))
scheduler.start()
print("[排程] APScheduler 已啟動，每日 08:00 推播，每月1號 00:05 重置訂閱")

pending_state = {}


# ══════════════════════════════════════════
#  Flex Message 工廠
# ══════════════════════════════════════════

def build_type_select_flex(mode="daily"):
    if mode == "daily":
        title = "🌙 今日運勢"
        desc = "選擇您想要的占卜方式\n老師將為您解讀今日能量 ✨"
        tarot_data, bazi_data, iching_data = "daily_tarot", "daily_bazi", "daily_iching"
    else:
        title = "🆘 急救占卜"
        desc = "心煩卡關的時候\n選擇您信任的占卜方式 🔮"
        tarot_data, bazi_data, iching_data = "deep_tarot", "deep_bazi", "deep_iching"
    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#2D1B69"},
            "body": {"backgroundColor": "#F8F4FF"}
        },
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": title, "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": desc, "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "postback", "label": "🃏 塔羅牌占卜", "data": tarot_data}},
                {"type": "button", "style": "primary", "color": "#4A3080",
                 "action": {"type": "postback", "label": "🀄 八字命理", "data": bazi_data}},
                {"type": "button", "style": "primary", "color": "#2D1B69",
                 "action": {"type": "postback", "label": "☯️ 易經起卦", "data": iching_data}}
            ]
        }
    }
    return FlexMessage(alt_text="請選擇占卜方式", contents=FlexContainer.from_dict(flex_content))


def build_token_flex(tokens, used, subscription_type="free"):
    remaining = max(0, FREE_READING_LIMIT - used)
    is_monthly = subscription_type == "monthly"
    sub_status_text = "👑 月訂閱・星運令（每月重置 15 次）" if is_monthly else "🆓 免費方案（每月 3 次）"
    remaining_text = "15 次額度 ♾️" if is_monthly else f"{remaining} / {FREE_READING_LIMIT}"
    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#2D1B69"},
            "body": {"backgroundColor": "#F8F4FF"}
        },
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "💎 我的代幣", "color": "#FFFFFF", "weight": "bold", "size": "lg"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "目前方案", "color": "#666666", "size": "sm", "flex": 2},
                        {"type": "text", "text": sub_status_text, "color": "#6B4FA0", "weight": "bold", "size": "xs", "flex": 3, "align": "end", "wrap": True}
                    ]
                },
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "急救代幣", "color": "#666666", "size": "sm", "flex": 2},
                        {"type": "text", "text": f"{tokens} 枚", "color": "#6B4FA0", "weight": "bold", "size": "sm", "flex": 1, "align": "end"}
                    ]
                },
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "靈性占卜剩餘", "color": "#666666", "size": "sm", "flex": 2},
                        {"type": "text", "text": remaining_text, "color": "#6B4FA0", "weight": "bold", "size": "sm", "flex": 1, "align": "end"}
                    ]
                },
                {"type": "separator"},
                {"type": "text", "text": "每月自動補充 1 枚代幣 🌙", "color": "#AAAAAA", "size": "xs"},
                {"type": "text", "text": "每週連續簽到 7 天送 1 枚 📅", "color": "#AAAAAA", "size": "xs"},
                {"type": "text", "text": "推薦好友滿 3 或 5 人送 1 枚 👥", "color": "#AAAAAA", "size": "xs"},
                {"type": "text", "text": "VIP 月訂閱每月重置 15 次額度 ✨", "color": "#AAAAAA", "size": "xs"},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {
                    "type": "button", "style": "primary", "color": "#6B4FA0",
                    "action": {"type": "uri", "label": "✨ 購買代幣包", "uri": SHOP_URL}
                },
                {
                    "type": "button", "style": "secondary",
                    "action": {"type": "message", "label": "📅 每日簽到", "text": "簽到"}
                },
                {
                    "type": "button", "style": "secondary",
                    "action": {"type": "message", "label": "📤 我的推薦碼", "text": "我的推薦碼"}
                }
            ]
        }
    }
    return FlexMessage(alt_text="我的代幣", contents=FlexContainer.from_dict(flex_content))


def build_tianbook_flex():
    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#1A0A3D"},
            "body": {"backgroundColor": "#F8F4FF"}
        },
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📖 專屬天書", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "命盤深度解析，為您寫一封命運密函 ✨", "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "老師將為您產出精美 PDF 報告書 📜", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "內含詳細命盤圖、流年分析、開運建議，讓您珍藏一生 🌟", "color": "#555555", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "選擇您想深度解析的方向：", "color": "#555555", "size": "sm"},
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "uri", "label": "💑 雙人合盤解析", "uri": SHOP_URL}},
                {"type": "button", "style": "primary", "color": "#4A3080",
                 "action": {"type": "uri", "label": "📅 流年運勢報告", "uri": SHOP_URL}},
                {"type": "button", "style": "primary", "color": "#2D1B69",
                 "action": {"type": "uri", "label": "⭐ 紫微斗數命盤", "uri": SHOP_URL}}
            ]
        }
    }
    return FlexMessage(alt_text="專屬天書", contents=FlexContainer.from_dict(flex_content))


def build_vip_flex(referral_code=""):
    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#7B3F00"},
            "body": {"backgroundColor": "#FFFAF0"}
        },
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "👑 星運 VIP", "color": "#FFD700", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "解鎖專屬星運服務", "color": "#FFE4B5", "size": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "✨ VIP 專屬權益", "weight": "bold", "color": "#7B3F00", "size": "sm"},
                {"type": "text", "text": "• 每月 15 次靈性占卜額度", "color": "#555555", "size": "sm"},
                {"type": "text", "text": "• 每日專屬星座深度解析", "color": "#555555", "size": "sm"},
                {"type": "text", "text": "• 親友擴充槽（最多 3 位）", "color": "#555555", "size": "sm"},
                {"type": "text", "text": "• 每月專屬星象指南", "color": "#555555", "size": "sm"},
                {"type": "text", "text": "• 🛍️ 專屬高階幸運物 9 折優惠", "color": "#B8860B", "size": "sm", "weight": "bold"},
                {"type": "text", "text": "• ⭐ 星力源源不絕，月月重啟命運之輪", "color": "#B8860B", "size": "sm", "weight": "bold"},
                {"type": "separator"},
                {"type": "text", "text": "💳 訂閱方案", "weight": "bold", "color": "#7B3F00", "size": "sm"},
                {"type": "text", "text": "👑 月訂閱・星運令　NT$300／月", "color": "#555555", "size": "sm"},
                {"type": "text", "text": "   每月1號自動重置 15 次靈性占卜額度", "color": "#AAAAAA", "size": "xs"},
                {"type": "separator"},
                {"type": "text", "text": "🔮 急救占卜　NT$1,200", "weight": "bold", "color": "#7B3F00", "size": "sm"},
                {"type": "text", "text": "   感情、工作、人生卡關？讓星盤給你答案", "color": "#555555", "size": "xs"},
                {"type": "separator"},
                {"type": "text", "text": "✨ 代幣包方案", "weight": "bold", "color": "#7B3F00", "size": "sm"},
                {"type": "text", "text": "🌱 入門包　$500 → 3 次", "color": "#555555", "size": "xs"},
                {"type": "text", "text": "   第一步踏入星盤，命運從這裡開始轉動", "color": "#AAAAAA", "size": "xs"},
                {"type": "text", "text": "💫 超值包　$1,200 → 8 次", "color": "#555555", "size": "xs"},
                {"type": "text", "text": "   最受歡迎！平均每次只要 $150，星辰常伴左右", "color": "#AAAAAA", "size": "xs"},
                {"type": "text", "text": "🌌 豪華包　$2,000 → 15 次", "color": "#B8860B", "size": "xs", "weight": "bold"},
                {"type": "text", "text": "   深度陪伴，讓老師全年守護你的每個轉折", "color": "#AAAAAA", "size": "xs"},
                {"type": "separator"},
                {"type": "text", "text": "👥 推薦好友加入", "weight": "bold", "color": "#7B3F00", "size": "sm"},
                {"type": "text", "text": f"您的專屬推薦碼：{referral_code}", "color": "#555555", "size": "sm"},
                {"type": "text", "text": "推薦滿 3 人送 1 枚代幣\n推薦滿 5 人再送 1 枚代幣 🎁", "color": "#555555", "size": "xs", "wrap": True},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#B8860B",
                 "action": {"type": "uri", "label": "👑 立即升級 VIP", "uri": SHOP_URL}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "message", "label": "📤 分享我的推薦碼", "text": "我的推薦碼"}}
            ]
        }
    }
    return FlexMessage(alt_text="星運 VIP 方案", contents=FlexContainer.from_dict(flex_content))


def build_settings_flex(user):
    birth = user.get("birth_date") or "尚未綁定"
    zodiac = get_zodiac(birth) if user.get("birth_date") else "尚未設定"
    locked_text = "🔒 已鎖定" if user.get("birthdate_locked") else "🔓 未鎖定"
    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#2D1B69"},
            "body": {"backgroundColor": "#F8F4FF"}
        },
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "⚙️ 我的設定", "color": "#FFFFFF", "weight": "bold", "size": "lg"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🎂 生辰", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": birth, "color": "#333333", "size": "sm", "flex": 3, "align": "end"}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "⭐ 星座", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": zodiac, "color": "#6B4FA0", "size": "sm", "flex": 3, "align": "end"}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🔒 鎖定狀態", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": locked_text, "color": "#333333", "size": "sm", "flex": 3, "align": "end"}
                ]},
                {"type": "separator"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {
                     "type": "datetimepicker", "label": "📅 綁定／更改生辰",
                     "data": "bind_birth", "mode": "date",
                     "initial": "1995-01-01", "min": "1924-01-01", "max": "2010-12-31"
                 }},
                {"type": "button", "style": "secondary",
                 "action": {"type": "message", "label": "🔔 推播設定", "text": "推播設定"}}
            ]
        }
    }
    return FlexMessage(alt_text="我的設定", contents=FlexContainer.from_dict(flex_content))


def build_date_picker_flex(is_rebound=False):
    desc_text = (
        "⚠️ 您的生辰已綁定。\n改綁將消耗 1 枚急救代幣\n\n請選擇新的出生日期 🌟"
        if is_rebound else
        "老師想更了解您，才能給出最準確的建議 💫\n\n請選擇您的出生日期 🌟"
    )
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "text", "text": "🌟 建立您的專屬星盤", "weight": "bold", "size": "lg", "color": "#6B4FA0"},
                {"type": "text", "text": desc_text, "wrap": True, "color": "#666666", "size": "sm"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {
                     "type": "datetimepicker", "label": "📅 選擇我的生日",
                     "data": "bind_birth", "mode": "date",
                     "initial": "1995-01-01", "min": "1924-01-01", "max": "2010-12-31"
                 }}
            ]
        }
    }
    return FlexMessage(alt_text="請選擇您的生日", contents=FlexContainer.from_dict(flex_content))


def build_history_flex(logs):
    bubbles = []
    for log in logs:
        created = log.get("created_at", "")[:10]
        bubbles.append({
            "type": "bubble", "size": "kilo",
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"🃏 {log.get('card_name', '未知牌')}", "weight": "bold", "color": "#6B4FA0", "size": "sm"},
                    {"type": "text", "text": f"📅 {created}", "color": "#AAAAAA", "size": "xs"},
                    {"type": "text", "text": log.get("reading", "")[:80] + "...", "wrap": True, "color": "#555555", "size": "xs"}
                ]
            }
        })
    return FlexMessage(
        alt_text="您的最近占卜紀錄",
        contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles})
    )


def build_daily_flex(card, orientation, reading, zodiac, today_str):
    zodiac_text = f"⭐ {zodiac}" if zodiac else "🔮 塔羅每日運勢"
    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#2D1B69"},
            "body": {"backgroundColor": "#F8F4FF"}
        },
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🌙 每日星運占卜", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": today_str, "color": "#C9B8FF", "size": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "text", "text": zodiac_text, "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": f"🃏 今日牌卡：{card}｜{orientation}", "color": "#333333", "weight": "bold", "size": "sm"},
                {"type": "separator"},
                {"type": "text", "text": reading, "wrap": True, "color": "#444444", "size": "sm"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "secondary", "color": "#6B4FA0",
                 "action": {"type": "message", "label": "🆘 急救占卜", "text": "急救占卜"}}
            ]
        }
    }
    return FlexMessage(
        alt_text=f"🌙 {today_str} 每日星運占卜",
        contents=FlexContainer.from_dict(flex_content)
    )


# ══════════════════════════════════════════
#  Webhook 路由
# ══════════════════════════════════════════

@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200


@app.route("/push-now", methods=["GET"])
def push_now():
    do_daily_push()
    return "推播已觸發", 200


@app.route("/reset-subscriptions", methods=["GET"])
def trigger_reset():
    reset_monthly_subscription()
    return "月訂閱重置已觸發", 200


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
        "嗨，終於等到您了 🌙\n"
        "我是您的專屬『心靈星運導航老師』。\n"
        "在這個充滿雜音的世界裡，老師會在這裡傾聽您的煩惱，"
        "並透過星象與塔羅，為您尋找每天的平靜與方向。\n\n"
        "從今天起，把那些難以消化的情緒，都安心地交給老師吧 💫\n\n"
        "💎 輸入「我的推薦碼」可獲得專屬邀請碼，推薦好友送代幣 🎁\n\n"
        "💡 若老師沒有立即回應，\n"
        "請稍等約 30 秒後再傳訊息，\n"
        "那是星辰正在為您凝聚能量 ✨"
    )
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(PushMessageRequest(
            to=line_user_id, messages=[TextMessage(text=welcome_text)]
        ))
        line_bot_api.push_message(PushMessageRequest(
            to=line_user_id, messages=[build_date_picker_flex()]
        ))
    push_text(
        line_user_id,
        "🎁 如果是朋友推薦您來的\n"
        "請輸入「推薦碼 XXXXXX」\n"
        "讓好友獲得代幣獎勵 💎\n\n"
        "（沒有推薦碼可以跳過這步驟）"
    )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    line_user_id = event.source.user_id
    user_msg = event.message.text.strip()
    user = get_or_create_user(line_user_id)

    needs_update = {}
    if user.get("free_readings_used") is None:
        needs_update["free_readings_used"] = 0
        user["free_readings_used"] = 0
    if user.get("birthdate_locked") is None:
        needs_update["birthdate_locked"] = False
        user["birthdate_locked"] = False
    if user.get("subscription_type") is None:
        needs_update["subscription_type"] = "free"
        user["subscription_type"] = "free"
    if needs_update:
        supabase.table("users").update(needs_update).eq("line_user_id", line_user_id).execute()

    zodiac = get_zodiac(user.get("birth_date")) if user.get("birth_date") else None

    if line_user_id in pending_state:
        state = pending_state.pop(line_user_id)
        mode = state["mode"]
        reading_type = state["type"]
        if mode == "deep":
            if not use_token(line_user_id):
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="✨ 代幣不足，無法進行急救占卜\n每月自動補充 1 枚，或可儲值獲得更多 🔮")]
                    ))
                return
            wait_msg = random.choice(WAITING_MSGS_DEEP)
        else:
            can_read, quota_msg = check_free_reading_quota(line_user_id, user)
            if not can_read:
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=quota_msg)]
                    ))
                return
            if reading_type == "tarot":
                wait_msg = random.choice(WAITING_MSGS_TAROT)
            elif reading_type == "bazi":
                wait_msg = random.choice(WAITING_MSGS_BAZI)
            else:
                wait_msg = random.choice(WAITING_MSGS_ICHING)
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=wait_msg)]
            ))
        do_reading_async(line_user_id, user_msg, reading_type, mode == "deep", zodiac, user)
        return

    if user_msg in ["今日運勢", "運勢"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_type_select_flex(mode="daily")]
            ))
        return

    elif user_msg in ["急救占卜"]:
        if user.get("tokens", 0) < 1:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="✨ 您目前沒有急救代幣了～\n每月會自動補充 1 枚，或可儲值獲得更多 🔮")]
                ))
        else:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[build_type_select_flex(mode="deep")]
                ))
        return

    elif user_msg in ["我的代幣", "代幣"]:
        fresh = supabase.table("users").select("free_readings_used, tokens, subscription_type").eq("line_user_id", line_user_id).execute()
        fd = fresh.data[0] if fresh.data else {}
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_token_flex(
                    fd.get("tokens") or 0,
                    fd.get("free_readings_used") or 0,
                    fd.get("subscription_type") or "free"
                )]
            ))
        return

    elif user_msg in ["簽到", "每日簽到"]:
        success, result = do_checkin(line_user_id)
        if not success:
            reply_text = "✅ 您今天已經簽到過囉！\n明天再來繼續累積連續簽到天數 🌙"
        else:
            days = result["days"]
            week_start = result["week_start"]
            reward = result["reward"]
            days_left = 7 - days
            if reward:
                reply_text = (
                    "🎉 恭喜完成本週連續簽到！\n"
                    "💎 老師送您 1 枚急救代幣作為獎勵 🌟\n\n"
                    "下週一起繼續簽到，繼續累積代幣吧 ✨"
                )
            else:
                reply_text = (
                    f"✅ 簽到成功！本週已簽到 {days} / 7 天\n"
                    f"📅 本週起算日：{week_start}\n"
                    f"💪 還差 {days_left} 天完成本週目標\n"
                    f"週日完成全勤可獲得 1 枚代幣 💎"
                )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg.startswith("推薦碼 "):
        parts = user_msg.split()
        if len(parts) >= 2:
            ref_code = parts[1].strip().upper()
            if user.get("referred_by"):
                reply_text = "💫 您已經使用過推薦碼囉！\n每位用戶只能使用一次推薦碼 🌙"
            else:
                referrer = supabase.table("users").select("line_user_id").eq("referral_code", ref_code).execute()
                if not referrer.data:
                    reply_text = "🔍 找不到這組推薦碼，請確認是否輸入正確 🙏\n格式：推薦碼 XXXXXX"
                elif referrer.data[0]["line_user_id"] == line_user_id:
                    reply_text = "😅 不能使用自己的推薦碼喔～"
                else:
                    process_referral(line_user_id, ref_code)
                    reply_text = (
                        "✅ 推薦碼使用成功！\n"
                        "您的好友已獲得推薦紀錄 💎\n\n"
                        "感謝您的加入，老師會好好照顧您的 🌟"
                    )
        else:
            reply_text = (
                "📤 推薦碼輸入格式：\n"
                "推薦碼 XXXXXX\n\n"
                "（請在「推薦碼」後面加一個空格，再輸入碼）"
            )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["我的推薦碼", "推薦碼"]:
        ref_code = user.get("referral_code") or "尚未產生"
        ref_count = user.get("referral_count") or 0
        reply_text = (
            f"📤 您的專屬推薦碼：{ref_code}\n\n"
            f"📊 目前推薦人數：{ref_count} 人\n\n"
            f"🎁 推薦好友加入方式：\n"
            f"請好友加入後傳送「推薦碼 {ref_code}」\n\n"
            f"💎 推薦滿 3 人送 1 枚代幣\n"
            f"💎 推薦滿 5 人再送 1 枚代幣 🌟"
        )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["專屬天書", "天書"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_tianbook_flex()]
            ))
        return

    elif user_msg in ["星運VIP", "VIP", "vip", "升級VIP", "星運 VIP"]:
        ref_code = user.get("referral_code") or ""
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_vip_flex(referral_code=ref_code)]
            ))
        return

    elif user_msg in ["我的設定", "設定"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_settings_flex(user)]
            ))
        return

    elif user_msg in ["綁定生辰", "設定生日", "綁定生日"]:
        is_locked = user.get("birthdate_locked", False)
        if is_locked and user.get("tokens", 0) < 1:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="🔒 您的生辰已綁定，改綁需消耗 1 枚代幣。\n但您目前代幣不足 💎\n\n可儲值代幣後再試 🌙")]
                ))
            return
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_date_picker_flex(is_rebound=is_locked)]
            ))
        return

    elif user_msg in ["我的方案", "方案"]:
        fresh = supabase.table("users").select("*").eq("line_user_id", line_user_id).execute()
        fd = fresh.data[0] if fresh.data else {}
        sub_type = fd.get("subscription_type") or "free"
        if sub_type == "monthly":
            plan_name = "👑 月訂閱・星運令"
        elif fd.get("plan") == "vip":
            plan_name = "⭐ 星運 VIP"
        else:
            plan_name = "🆓 免費版"
        birth = fd.get("birth_date") or "尚未綁定"
        zodiac_text = get_zodiac(birth) if fd.get("birth_date") else "尚未綁定生辰"
        locked_text = "🔒 已鎖定" if fd.get("birthdate_locked") else "🔓 未鎖定"
        used = fd.get("free_readings_used") or 0
        remaining = max(0, FREE_READING_LIMIT - used)
        expires = fd.get("subscription_expires_at") or "—"
        reply_text = (
            f"您目前的方案是：{plan_name}\n"
            f"💎 代幣餘額：{fd.get('tokens', 0)} 枚\n"
            f"🎂 綁定生辰：{birth}（{locked_text}）\n"
            f"⭐ 星座：{zodiac_text}\n"
            f"🌙 靈性占卜剩餘：{remaining} / {FREE_READING_LIMIT} 次\n"
            f"📅 訂閱到期日：{expires}"
        )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["我的紀錄", "占卜紀錄", "紀錄"]:
        logs = supabase.table("tarot_logs") \
            .select("card_name, reading, category, created_at") \
            .eq("line_user_id", line_user_id) \
            .order("created_at", desc=True) \
            .limit(5).execute()
        if not logs.data:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="您還沒有任何占卜紀錄喔 🌙\n傳訊息給老師，讓塔羅牌為您指引方向吧 🃏")]
                ))
            return
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_history_flex(logs.data)]
            ))
        return

    elif user_msg in ["推播設定"]:
        reply_text = (
            "🔔 推播設定\n\n"
            "每天早上 8:00 老師會為您送上今日星運 🌙\n\n"
            "傳送「關閉推播」→ 停止每日推播\n"
            "傳送「開啟推播」→ 重新開啟每日推播"
        )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["關閉推播", "停止推播"]:
        supabase.table("users").update({"daily_push": False}).eq("line_user_id", line_user_id).execute()
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="已關閉每日運勢推播 🌙\n若想重新開啟，請傳送「開啟推播」")]
            ))
        return

    elif user_msg in ["開啟推播", "開啟每日推播"]:
        supabase.table("users").update({"daily_push": True}).eq("line_user_id", line_user_id).execute()
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="✨ 每日運勢推播已開啟！\n每天早上 8:00 老師會為您送上今日星運 🌟")]
            ))
        return

    elif user_msg in ["說明", "使用說明", "help", "Help"]:
        reply_text = (
            "🔮 星運導航使用說明\n\n"
            "🌙 今日運勢 → 塔羅／八字／易經每日解讀\n"
            "🆘 急救占卜 → 感情、工作、人生卡關？讓星盤給你答案（NT$1,200）\n"
            "💎 我的代幣 → 查詢餘額與儲值\n"
            "📖 專屬天書 → 合盤／流年／紫微斗數\n"
            "👑 星運VIP → 查看訂閱方案\n"
            "⚙️ 我的設定 → 管理生辰資料\n"
            "📅 簽到 → 每週全勤送代幣\n"
            "📤 我的推薦碼 → 推薦好友送代幣\n"
            "📖 我的紀錄 → 查看最近 5 次占卜\n\n"
            "💡 若老師沒有立即回應，\n"
            "請稍等約 30 秒後再傳訊息 ✨"
        )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    else:
        can_read, quota_msg = check_free_reading_quota(line_user_id, user)
        if not can_read:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=quota_msg)]
                ))
            return
        wait_msg = random.choice(WAITING_MSGS_TAROT)
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=wait_msg)]
            ))
        do_reading_async(line_user_id, user_msg, "tarot", False, zodiac, user)
        return


@handler.add(PostbackEvent)
def handle_postback(event):
    line_user_id = event.source.user_id
    data = event.postback.data

    type_map = {
        "daily_tarot":  ("daily", "tarot"),
        "daily_bazi":   ("daily", "bazi"),
        "daily_iching": ("daily", "iching"),
        "deep_tarot":   ("deep", "tarot"),
        "deep_bazi":    ("deep", "bazi"),
        "deep_iching":  ("deep", "iching"),
    }

    if data in type_map:
        mode, reading_type = type_map[data]
        type_names = {"tarot": "塔羅", "bazi": "八字", "iching": "易經"}
        type_name = type_names[reading_type]
        if mode == "deep":
            user = get_or_create_user(line_user_id)
            if user["tokens"] < 1:
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="✨ 您目前沒有急救代幣了～\n每月會自動補充 1 枚，或可儲值獲得更多 🔮")]
                    ))
                return
            ask_msg = (
                f"🆘 急救占卜｜{type_name}\n\n"
                f"💎 將消耗 1 枚代幣\n\n"
                f"請說出您此刻最想解答的問題，\n"
                f"老師將為您進行深度解讀 🔮"
            )
        else:
            ask_msg = (
                f"🌙 {type_name}今日運勢\n\n"
                f"請告訴老師您今天最想了解的方向，\n"
                f"或直接傳送「開始」讓星辰為您指引 ✨"
            )
        pending_state[line_user_id] = {"mode": mode, "type": reading_type}
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=ask_msg)]
            ))
        return

    if data == "bind_birth":
        date_str = event.postback.params.get("date")
        try:
            user = get_or_create_user(line_user_id)
            is_locked = user.get("birthdate_locked", False)
            if is_locked:
                if not use_token(line_user_id):
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="💎 代幣不足，無法改綁生辰。\n請先儲值代幣後再試 🌙")]
                        ))
                    return
            supabase.table("users").update({
                "birth_date": date_str,
                "birthdate_locked": True
            }).eq("line_user_id", line_user_id).execute()
            zodiac = get_zodiac(date_str)
            lock_hint = "（往後改綁需消耗 1 枚代幣）" if not is_locked else "（已消耗 1 枚代幣）"
            reply_text = (
                f"✨ 生辰綁定成功！\n"
                f"🎂 您的生日：{date_str}\n"
                f"⭐ 您的星座：{zodiac}\n"
                f"🔒 生辰已鎖定 {lock_hint}\n\n"
                f"老師已記住您的星盤\n"
                f"往後的占卜將融入您的星座特質 🔮"
            )
        except Exception as e:
            print(f"綁定生辰錯誤: {e}")
            reply_text = "綁定時發生錯誤，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

