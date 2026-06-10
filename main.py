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
from payuni import create_payment as ecpay_create, verify_notify, is_payment_success, get_order_id_from_notify
import os, random, datetime, pytz, threading, uuid, time
import requests
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ══════════════════════════════════════════
#  管理員設定
# ══════════════════════════════════════════
ADMIN_USER_ID = "U50df8621612919931dee55554de9692a"

# ══════════════════════════════════════════
#  自我 ping — 防止 Render 休眠
# ══════════════════════════════════════════
def _keep_alive():
    time.sleep(60)
    while True:
        try:
            url = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
            res = requests.get(f"{url}/", timeout=10)
            print(f"[Keep-Alive] {datetime.datetime.now()} → {res.status_code}")
        except Exception as e:
            print(f"[Keep-Alive] Ping 失敗：{e}")
        time.sleep(5 * 60)

_ping_thread = threading.Thread(target=_keep_alive, daemon=True)
_ping_thread.start()

configuration = Configuration(access_token=os.environ.get("LINE_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

RENDER_URL = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
FREE_READING_LIMIT = 3
SHOP_URL = "https://crystal-shop-62a69.web.app/index.html"

# ══ 追問上限設定 ══
FOLLOW_UP_LIMITS = {
    "double_chart": 1,
    "year_fortune":  1,
    "ziwei":         2,
    "love_reading":  5,
    "career":        2,
    "wealth":        1,
}

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

WAITING_MSGS_SPIRITUAL = [
    "🌌 靈性占卜啟動中...\n\n老師正在整合您的靈性能量，進行深層解讀，約需 5 分鐘 ✨",
    "🔮 老師已接收到您的靈性訊息，正在為您進行深度靈魂解析...\n\n請靜心等待約 5 分鐘 🌙",
    "💫 靈魂之書正在為您翻開...\n\n老師正在解讀您的靈性課題，請稍候約 5 分鐘 🕯️",
]

WAITING_MSGS_WEEKLY = [
    "🌟 老師正在為您解讀本週星圖能量...\n\n一週運勢需要整合七日氣場，請靜心等待約 1 分鐘 ✨",
    "📅 星辰正在為您排列本週命運之書...\n\n老師正在仔細推演，請稍候約 1 分鐘 🔮",
    "🌙 本週的星象正在凝聚中...\n\n老師將為您帶來完整一週指引，請靜心等待約 1 分鐘 💫",
]

WAITING_MSGS_TIANBOOK = [
    "📖 老師正在為您開啟命運密函...\n\n深度命盤解析需要仔細推算，約需 15 分鐘，請您耐心等候 🔮",
    "🌌 命盤的星辰正在一一排列...\n\n老師正在為您進行深度解讀，約需 15 分鐘，請先休息一下 ✨",
    "⭐ 老師已接收到您的命格訊息，正在仔細推演...\n\n這份專屬命盤報告約需 15 分鐘，請靜心等待 🕯️",
]

WAITING_MSGS_LOVE = [
    "💔 老師正在為您抽出這一題的牌卡...\n\n感情的答案需要靜心感應，請稍候約 1 分鐘 🌙",
    "🃏 牌卡正在為您的感情問題凝聚能量...\n\n請靜心等待約 1 分鐘，老師即將為您解讀 ✨",
]

WAITING_MSGS_CAREER = [
    "💼 老師正在以八字推演您的職場運勢...\n\n命格分析需要精密推算，約需 5 分鐘，請稍候 🌟",
    "⭐ 天干地支正在為您的職涯排列...\n\n老師正在仔細解讀，約需 5 分鐘 🔮",
]

WAITING_MSGS_WEALTH = [
    "💰 老師正在為您起卦解讀財運走向...\n\n易經卦象需要靜心推演，約需 5 分鐘，請稍候 🌙",
    "☯️ 財運卦象正在為您凝聚...\n\n老師正在仔細解讀您的錢途，約需 5 分鐘 ✨",
]

FORTUNE_STICK_CATEGORIES = {
    "愛情":   ["感情現況如何？", "對方對我有意思嗎？", "這段感情值得繼續嗎？", "何時能遇到對的人？", "分手後還有復合機會嗎？"],
    "事業學業": ["工作轉換時機到了嗎？", "升遷機會近了嗎？", "創業適合現在嗎？", "考試能順利通過嗎？", "目前的努力方向正確嗎？"],
    "財運":   ["近期偏財運如何？", "投資時機成熟了嗎？", "借出去的錢能要回來嗎？", "加薪機會近了嗎？", "財務困境何時能解？"],
    "健康":   ["身體近期需要注意什麼？", "長期的困擾何時能改善？", "心理狀態需要調整嗎？", "家人的健康狀況如何？", "目前的養生方式正確嗎？"],
    "生活":   ["搬家或換環境的時機到了嗎？", "家庭關係如何改善？", "近期出行平安嗎？", "這個重要決定該如何選擇？", "貴人何時出現？"],
}

FORTUNE_STICK_POEMS = [
    {"num": 1,  "grade": "上上籤", "poem": "春風得意馬蹄疾，一日看盡長安花，時機已至莫猶豫，萬事俱備東風來"},
    {"num": 8,  "grade": "上吉籤", "poem": "雲開霧散見青天，撥雲見日喜心田，貴人相助逢吉時，前程似錦步步高"},
    {"num": 15, "grade": "中吉籤", "poem": "靜待花開自有時，莫急莫躁守本心，水到渠成天自助，耐心等候好時機"},
    {"num": 22, "grade": "中平籤", "poem": "半晴半雨過雲天，得失之間需謹慎，守住本分莫貪進，平穩度日自安然"},
    {"num": 30, "grade": "平籤",   "poem": "山重水複疑無路，柳暗花明又一村，困境之中藏轉機，靜心思量自有解"},
    {"num": 38, "grade": "中吉籤", "poem": "月圓之後有月缺，事緩則圓勿操急，積累能量待時發，厚積薄發終成事"},
    {"num": 45, "grade": "上吉籤", "poem": "金風玉露一相逢，便勝卻人間無數，緣分天定莫強求，順其自然得圓滿"},
    {"num": 52, "grade": "中平籤", "poem": "欲速則不達其功，穩紮穩打方為上，步步為營守正道，終有一日見光明"},
    {"num": 60, "grade": "小吉籤", "poem": "潮起潮落皆有時，人生起伏是常事，保持初心不忘本，終將迎來好時節"},
    {"num": 68, "grade": "中吉籤", "poem": "蟄伏之龍待時飛，厚積薄發自有期，莫因眼前小困頓，放棄心中大志向"},
    {"num": 75, "grade": "上上籤", "poem": "龍騰四海志凌雲，天時地利人和聚，把握當下勇向前，輝煌就在不遠處"},
    {"num": 88, "grade": "中吉籤", "poem": "花開花落自有時，緣來緣去莫強留，順應天命守本心，自然而然得圓滿"},
    {"num": 99, "grade": "上吉籤", "poem": "九九歸一萬事成，天道酬勤終有報，堅持信念不動搖，美好未來在前方"},
]
FORTUNE_STICKS = FORTUNE_STICK_POEMS


SHICHEN_LIST = [
    "子時（23:00–01:00）", "丑時（01:00–03:00）",
    "寅時（03:00–05:00）", "卯時（05:00–07:00）",
    "辰時（07:00–09:00）", "巳時（09:00–11:00）",
    "午時（11:00–13:00）", "未時（13:00–15:00）",
    "申時（15:00–17:00）", "酉時（17:00–19:00）",
    "戌時（19:00–21:00）", "亥時（21:00–23:00）",
    "不知道時辰"
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

pending_state = {}
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


def parse_birth_input(text):
    import re
    text = text.strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", text)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$", text)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"
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


def use_tokens(line_user_id, amount=2, reason="占卜消耗"):
    user = get_or_create_user(line_user_id)
    if user["tokens"] < amount:
        return False
    supabase.table("users").update(
        {"tokens": user["tokens"] - amount}
    ).eq("line_user_id", line_user_id).execute()
    supabase.table("token_logs").insert({
        "line_user_id": line_user_id,
        "change": -amount,
        "reason": reason
    }).execute()
    return True


def add_tokens(line_user_id, amount, reason="管理員補充"):
    try:
        result = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        if not result.data:
            return 0
        current = result.data[0].get("tokens") or 0
        new_tokens = current + amount
        supabase.table("users").update({"tokens": new_tokens}).eq("line_user_id", line_user_id).execute()
        supabase.table("token_logs").insert({
            "line_user_id": line_user_id,
            "change": amount,
            "reason": reason
        }).execute()
        return new_tokens
    except Exception as e:
        print(f"[add_tokens 錯誤] {e}")
        return 0


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
            "老師還想繼續為您指引：\n"
            "💎 消耗 1 顆代幣，繼續占卜\n"
            "🌌 靈性占卜 / 急救占卜 消耗 2 顆代幣\n\n"
            "輸入「購買代幣」補充代幣 🌙"
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
                PushMessageRequest(to=line_user_id, messages=[TextMessage(text=text)])
            )
    except Exception as e:
        print(f"[push_text 錯誤] {line_user_id}: {e}")


def push_flex(line_user_id, flex_msg):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(to=line_user_id, messages=[flex_msg])
            )
    except Exception as e:
        print(f"[push_flex 錯誤] {line_user_id}: {e}")


def create_order(line_user_id, product_type, amount, tokens_to_add=0):
    order_id = str(uuid.uuid4()).replace("-", "")[:20]
    supabase.table("orders").insert({
        "order_id": order_id,
        "user_id": line_user_id,
        "product_type": product_type,
        "amount": amount,
        "status": "pending"
    }).execute()
    return order_id


def create_service(line_user_id, service_type, order_id):
    supabase.table("services").insert({
        "user_id": line_user_id,
        "service_type": service_type,
        "status": "unused",
        "order_id": order_id,
        "follow_up_count": 0
    }).execute()


def get_unused_service(line_user_id, service_type):
    result = supabase.table("services") \
        .select("*") \
        .eq("user_id", line_user_id) \
        .eq("service_type", service_type) \
        .eq("status", "unused") \
        .order("created_at", desc=False) \
        .limit(1).execute()
    return result.data[0] if result.data else None


def get_active_service(line_user_id, service_type):
    result = supabase.table("services") \
        .select("*") \
        .eq("user_id", line_user_id) \
        .eq("service_type", service_type) \
        .eq("status", "used") \
        .order("used_at", desc=True) \
        .limit(1).execute()
    if not result.data:
        return None
    svc = result.data[0]
    limit = FOLLOW_UP_LIMITS.get(service_type, 0)
    if (svc.get("follow_up_count") or 0) < limit:
        return svc
    return None


def mark_service_used(service_id):
    supabase.table("services").update({
        "status": "used",
        "used_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }).eq("service_id", service_id).execute()


def increment_follow_up(service_id):
    result = supabase.table("services").select("follow_up_count").eq("service_id", service_id).execute()
    current = result.data[0].get("follow_up_count") or 0 if result.data else 0
    supabase.table("services").update({"follow_up_count": current + 1}).eq("service_id", service_id).execute()
    return current + 1


# ══════════════════════════════════════════
#  付款開通共用函式
# ══════════════════════════════════════════

def _activate_payment(order_id):
    if not order_id:
        return
    try:
        result = supabase.table("payments").select("*").eq("order_id", order_id).execute()
        if result.data:
            payment = result.data[0]
            if payment.get("status") == "confirmed":
                return
            _activate_subscription(order_id, payment)
            return
        result2 = supabase.table("orders").select("*").eq("order_id", order_id).execute()
        if result2.data:
            order = result2.data[0]
            if order.get("status") == "paid":
                return
            _activate_single_service(order_id, order)
    except Exception as e:
        print(f"[_activate_payment 錯誤] {e}")


def _activate_subscription(order_id, payment):
    try:
        line_user_id = payment["user_id"]
        package_type = payment.get("package_type", "monthly")
        tz = pytz.timezone("Asia/Taipei")
        now = datetime.datetime.now(tz)
        supabase.table("payments").update({
            "status": "confirmed",
            "confirmed_at": now.isoformat()
        }).eq("order_id", order_id).execute()
        tokens_to_add = payment.get("tokens_to_add") or 0
        if tokens_to_add > 0:
            user = get_or_create_user(line_user_id)
            new_tokens = (user.get("tokens") or 0) + tokens_to_add
            supabase.table("users").update({"tokens": new_tokens}).eq("line_user_id", line_user_id).execute()
            supabase.table("token_logs").insert({
                "line_user_id": line_user_id,
                "change": tokens_to_add,
                "reason": f"{package_type}付款成功"
            }).execute()
            pkg_names = {
                "星塵入門包": "✨ 星塵入門包",
                "月光超值包": "🌙 月光超值包",
                "星河豪華包": "🌌 星河豪華包"
            }
            pkg_label = pkg_names.get(package_type, package_type)
            push_text(
                line_user_id,
                f"🎉 付款成功！代幣已入帳！\n\n"
                f"📦 方案：{pkg_label}\n"
                f"💎 新增代幣：{tokens_to_add} 顆\n"
                f"💰 目前代幣餘額：{new_tokens} 顆\n\n"
                f"老師已準備好，隨時為您進行占卜 🔮"
            )
    except Exception as e:
        print(f"[_activate_subscription 錯誤] {e}")


def _activate_single_service(order_id, order):
    try:
        line_user_id = order["user_id"]
        product_type = order["product_type"]
        tz = pytz.timezone("Asia/Taipei")
        now = datetime.datetime.now(tz)
        supabase.table("orders").update({
            "status": "paid",
            "paid_at": now.isoformat()
        }).eq("order_id", order_id).execute()
        create_service(line_user_id, product_type, order_id)

        service_names = {
            "double_chart": "💑 雙人合盤解析",
            "year_fortune": "📅 流年運勢報告",
            "ziwei":        "⭐ 紫微斗數命盤",
            "love_reading": "💔 復合分析",
            "career":       "💼 職場運勢",
            "wealth":       "💰 財運分析",
        }
        service_label = service_names.get(product_type, product_type)

        svc = get_unused_service(line_user_id, product_type)
        service_id = svc["service_id"] if svc else None

        if product_type == "love_reading":
            if service_id:
                pending_state[line_user_id] = {
                    "mode": "love_reading",
                    "step": "question",
                    "service_id": service_id,
                    "question_num": 1
                }
            push_text(
                line_user_id,
                f"🎉 付款成功！{service_label}已開通！\n\n"
                f"💔 老師將為您抽牌解讀感情狀況 🃏\n\n"
                f"📝 請直接描述您的感情狀況或想問的問題\n\n"
                f"例如：\n「我和前任分開 3 個月，對方最近突然聯絡我，復合機會大嗎？」\n\n"
                f"💎 本服務共可提問 {FOLLOW_UP_LIMITS['love_reading']} 次"
            )

        elif product_type == "career":
            if service_id:
                pending_state[line_user_id] = {
                    "mode": "career",
                    "step": "birth",
                    "service_id": service_id,
                    "follow_up_num": 1,
                    "data": {}
                }
            push_text(
                line_user_id,
                f"🎉 付款成功！{service_label}已開通！\n\n"
                f"💼 老師將以八字命理為您解讀職場運勢 🔮\n\n"
                f"請輸入您的出生日期：\n\n"
                f"格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                f"⚠️ 請使用西元國曆（陽曆）"
            )

        elif product_type == "wealth":
            if service_id:
                pending_state[line_user_id] = {
                    "mode": "wealth",
                    "step": "birth",
                    "service_id": service_id,
                    "follow_up_num": 1,
                    "data": {}
                }
            push_text(
                line_user_id,
                f"🎉 付款成功！{service_label}已開通！\n\n"
                f"💰 老師將以易經卦象為您解讀財運走向 🔮\n\n"
                f"請輸入您的出生日期：\n\n"
                f"格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                f"⚠️ 請使用西元國曆（陽曆）"
            )

        elif product_type == "double_chart":
            if service_id:
                pending_state[line_user_id] = {
                    "mode": "double_chart",
                    "step": "birth1",
                    "service_id": service_id,
                    "data": {}
                }
            push_text(
                line_user_id,
                f"🎉 付款成功！{service_label}已開通！\n\n"
                f"💑 老師將為您解讀兩人的命格相容性 🔮\n\n"
                f"📅 請輸入甲方（您自己）的出生日期\n\n"
                f"格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                f"⚠️ 請使用西元國曆（陽曆）"
            )

        elif product_type == "year_fortune":
            if service_id:
                pending_state[line_user_id] = {
                    "mode": "year_fortune",
                    "step": "birth",
                    "service_id": service_id,
                    "data": {}
                }
            push_text(
                line_user_id,
                f"🎉 付款成功！{service_label}已開通！\n\n"
                f"📅 老師將為您推演今年完整運勢 🔮\n\n"
                f"請輸入您的出生日期：\n\n"
                f"格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                f"⚠️ 請使用西元國曆（陽曆）"
            )

        elif product_type == "ziwei":
            if service_id:
                pending_state[line_user_id] = {
                    "mode": "ziwei",
                    "step": "birth",
                    "service_id": service_id,
                    "data": {}
                }
            push_text(
                line_user_id,
                f"🎉 付款成功！{service_label}已開通！\n\n"
                f"⭐ 老師將為您排出專屬紫微命盤 🔮\n\n"
                f"請輸入您的出生日期：\n\n"
                f"格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                f"⚠️ 請使用西元國曆（陽曆）\n下一步將請您選擇出生時辰"
            )

    except Exception as e:
        print(f"[_activate_single_service 錯誤] {e}")


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
    new_user = get_or_create_user(new_user_id)
    if new_user.get("referred_by"):
        return
    if referrer_data.get("referred_by") == new_user_id:
        return
    supabase.table("users").update({"referred_by": referrer_id}).eq("line_user_id", new_user_id).execute()
    new_count = (referrer_data.get("referral_count") or 0) + 1
    supabase.table("users").update({"referral_count": new_count}).eq("line_user_id", referrer_id).execute()
    if new_count in [3, 5]:
        supabase.table("users").update(
            {"tokens": referrer_data["tokens"] + 1}
        ).eq("line_user_id", referrer_id).execute()
        supabase.table("token_logs").insert({
            "line_user_id": referrer_id,
            "change": 1,
            "reason": f"推薦好友達 {new_count} 人獎勵"
        }).execute()
        push_text(referrer_id,
            f"🎉 恭喜！您已成功推薦 {new_count} 位好友加入星運導航！\n"
            f"💎 老師特別送您 1 顆代幣作為感謝 🌟"
        )
    else:
        push_text(referrer_id,
            f"✨ 您推薦的好友剛剛加入了星運導航！\n"
            f"📊 目前推薦人數：{new_count} 人\n"
            f"💎 推薦滿 3 人或 5 人可獲得代幣獎勵 🌙"
        )

# ══════════════════════════════════════════
#  占卜核心（背景執行）
# ══════════════════════════════════════════

def _run_reading_background(line_user_id, user_msg, reading_type, is_deep, zodiac, user):
    try:
        if is_deep:
            time.sleep(random.uniform(240, 360))
        else:
            time.sleep(random.uniform(45, 75))

        card_drawn = ""
        type_label = ""
        if reading_type == "tarot":
            card = random.choice(TAROT_CARDS)
            orientation = "逆位" if random.choice([True, False]) else "正位"
            card_drawn = f"{card}（{orientation}）"
            type_label = "塔羅"
            zodiac_hint = f"使用者的星座是【{zodiac}】，請在解讀中融入星座特質。\n" if zodiac else ""
            depth_hint = "請給出約300字的深度占卜解讀，分析過去、現在、未來三個面向，語氣像一位溫柔有智慧的老師在引導學生。" if is_deep else "請用繁體中文給出約150字的占卜解讀，語氣溫柔有詩意，像老師在給學生建議。"
            user_prompt = f"{zodiac_hint}用戶的問題是：「{user_msg}」\n抽到的牌是：{card_drawn}\n{depth_hint}"
        elif reading_type == "bazi":
            type_label = "八字"
            birth = user.get("birth_date", "未知")
            zodiac_hint = f"使用者的星座是【{zodiac}】。\n" if zodiac else ""
            depth_hint = "請給出約300字的深度八字解析，分析命格特質、近期運勢走向，語氣像溫柔有智慧的老師。" if is_deep else "請給出約150字的八字運勢解讀，語氣溫柔有詩意。"
            user_prompt = f"{zodiac_hint}使用者生辰：{birth}\n用戶的問題是：「{user_msg}」\n請以八字命理角度，{depth_hint}"
        elif reading_type == "iching":
            hexagram = random.choice(ICHING_HEXAGRAMS)
            card_drawn = hexagram
            type_label = "易經"
            depth_hint = "請給出約300字的深度易經解卦，分析當前處境與建議行動，語氣像溫柔有智慧的老師。" if is_deep else "請給出約150字的易經卦象解讀，語氣溫柔有詩意。"
            user_prompt = f"用戶的問題是：「{user_msg}」\n起卦得到：{hexagram}\n{depth_hint}"
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
        else:
            prefix = ""

        footer = get_lucky_item_text()
        push_text(line_user_id, prefix + response_text + footer)

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
#  一週運勢核心（背景執行）
# ══════════════════════════════════════════

def _run_weekly_fortune_background(line_user_id, reading_type, zodiac, user):
    try:
        time.sleep(random.uniform(45, 75))

        tz = pytz.timezone("Asia/Taipei")
        now = datetime.datetime.now(tz)
        week_start = now - datetime.timedelta(days=now.weekday())
        week_end = week_start + datetime.timedelta(days=6)
        week_str = f"{week_start.strftime('%m/%d')}～{week_end.strftime('%m/%d')}"
        birth = user.get("birth_date", "未知") if user else "未知"
        zodiac_hint = f"使用者的星座是【{zodiac}】，請融入星座特質。\n" if zodiac else ""

        if reading_type == "tarot":
            day_names = ["一", "二", "三", "四", "五", "六", "日"]
            cards = []
            for i in range(7):
                card = random.choice(TAROT_CARDS)
                orientation = "逆位" if random.choice([True, False]) else "正位"
                cards.append(f"週{day_names[i]}：{card}（{orientation}）")
            cards_str = "\n".join(cards)
            user_prompt = f"""{zodiac_hint}請為使用者進行本週（{week_str}）塔羅一週運勢解讀。
每日牌卡如下：
{cards_str}

請給出約350字的一週運勢總覽，包含：
- 本週整體能量走向（2~3句）
- 感情運（1~2句）
- 事業工作運（1~2句）
- 財運（1句）
- 本週幸運提示（1句）
語氣溫柔有詩意，像老師給學生的週一早安叮嚀。"""
            prefix = f"🃏 本週塔羅運勢｜{week_str}\n\n"

        elif reading_type == "bazi":
            user_prompt = f"""{zodiac_hint}使用者生辰：{birth}
請以八字命理角度，給出本週（{week_str}）的一週運勢解讀，約350字，包含：
- 本週整體氣場與能量
- 感情運勢提示
- 事業財運走向
- 本週需注意事項
- 開運小建議
語氣溫柔神秘，像老師給學生的週一叮嚀。"""
            prefix = f"🀄 本週八字運勢｜{week_str}\n\n"

        elif reading_type == "iching":
            hexagram = random.choice(ICHING_HEXAGRAMS)
            user_prompt = f"""{zodiac_hint}本週（{week_str}）起卦得【{hexagram}】。
請以易經卦象角度，給出約350字的一週運勢解讀，包含：
- 卦象本週寓意
- 感情運勢
- 事業財運
- 本週行動建議
- 一句鼓勵結語
語氣溫柔神秘，像老師給學生的週一叮嚀。"""
            prefix = f"☯️ 本週易經運勢｜{week_str}\n\n卦象：【{hexagram}】\n\n"

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

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": f"一週運勢｜{reading_type}",
                "reading": response_text,
                "category": "一週運勢",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"[一週運勢 tarot_logs 寫入錯誤] {e}")

        if user:
            increment_free_reading(line_user_id, user)

        footer = get_lucky_item_text()
        push_text(line_user_id, prefix + response_text + footer)

    except Exception as e:
        print(f"[一週運勢背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請再傳一次訊息給老師 🙏")


# ══════════════════════════════════════════
#  靈性占卜核心（背景執行）
# ══════════════════════════════════════════

def _run_spiritual_background(line_user_id, data, zodiac):
    try:
        time.sleep(random.uniform(240, 360))

        birth = data.get("birth", "未知")
        q1 = data.get("q1", "")
        q2 = data.get("q2", "")
        q3 = data.get("q3", "")
        q4 = data.get("q4", "")
        zodiac_hint = f"使用者的星座是【{zodiac}】。\n" if zodiac else ""

        user_prompt = f"""{zodiac_hint}使用者生辰：{birth}
靈性占卜問卷：
1. 最近最困擾您的事：{q1}
2. 您希望在哪個方面得到指引：{q2}
3. 您目前的心情狀態：{q3}
4. 您對未來的期望：{q4}

請以靈性命理師的角度，給出約400字的深度靈性解讀，包含：
- 靈魂課題分析
- 當前能量狀態
- 具體行動建議
- 溫柔的鼓勵話語
語氣溫柔神秘，像一位有智慧的靈性導師。"""

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
                "card_name": "靈性占卜",
                "reading": response_text,
                "category": "靈性占卜",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"tarot_logs 寫入錯誤: {e}")

        footer = get_lucky_item_text()
        push_text(line_user_id, f"🌌 靈性占卜解讀\n\n{response_text}{footer}")

    except Exception as e:
        print(f"[靈性占卜背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請再傳一次訊息給老師 🙏")


# ══════════════════════════════════════════
#  求籤問卜核心（背景執行）
# ══════════════════════════════════════════

def _run_fortune_stick_background(line_user_id, category, question, stick):
    try:
        time.sleep(random.uniform(12, 15))

        user_prompt = f"""請進行求籤解析：
問卜類別：{category}
問題：{question}
籤號：第 {stick['num']} 籤 — {stick['grade']}
籤詩：{stick['poem']}

請以溫柔神秘的命理師角度，給出約200字的解籤內容，包含：
- 針對「{question}」這個問題的具體解讀
- 籤詩的意涵說明
- 實際行動建議 1~2 點
- 一句溫柔的鼓勵結語

語氣溫柔有詩意，像廟裡智慧的老師在為信徒解籤。"""

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
                "card_name": f"第{stick['num']}籤",
                "reading": response_text,
                "category": f"求籤問卜｜{category}",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"[求籤 tarot_logs 寫入錯誤] {e}")

        poem_lines = stick['poem'].replace('，', '\n')
        result_text = (
            f"🎊 第 {stick['num']} 籤 — {stick['grade']}\n\n"
            f"📜 籤詩：\n{poem_lines}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔮 解籤｜{category}\n"
            f"問：{question}\n\n"
            f"{response_text}"
        )
        push_text(line_user_id, result_text)

    except Exception as e:
        print(f"[求籤背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請再試一次 🙏")



# ══════════════════════════════════════════
#  復合分析核心（背景執行）
# ══════════════════════════════════════════

def _run_love_reading_background(line_user_id, situation, question_num, service_id):
    try:
        time.sleep(random.uniform(45, 75))

        card = random.choice(TAROT_CARDS)
        orientation = "逆位" if random.choice([True, False]) else "正位"
        card_drawn = f"{card}（{orientation}）"

        user_prompt = f"""請進行復合分析塔羅解讀：
感情狀況描述：{situation}
這是第 {question_num} 張牌
抽到的牌：{card_drawn}

請給出約200字的感情塔羅解讀，針對用戶描述的狀況，
從這張牌的角度分析復合的可能性與建議。
語氣溫柔有詩意，像老師在為學生解讀感情困惑。"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content

        limit = FOLLOW_UP_LIMITS.get("love_reading", 5)
        remaining = limit - question_num

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": f"復合分析第{question_num}張｜{card_drawn}",
                "reading": response_text,
                "category": "復合分析",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"[復合分析 tarot_logs 寫入錯誤] {e}")

        prefix = f"💔 復合分析｜第 {question_num} 張牌\n\n🃏 老師為您抽到了【{card_drawn}】\n\n"

        if remaining > 0:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"💬 您還可以繼續追問 {remaining} 次\n"
                f"請直接輸入您的下一個感情問題 🌙"
            )
        else:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"🌟 本次復合分析已完成，感謝您的信任\n"
                f"若有新的困惑，可重新購買服務 💎"
            )
            if service_id:
                supabase.table("services").update({
                    "status": "completed"
                }).eq("service_id", service_id).execute()

        push_text(line_user_id, prefix + response_text + footer_hint)

    except Exception as e:
        print(f"[復合分析背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請稍後再試 🙏")


# ══════════════════════════════════════════
#  職場運勢核心（背景執行）
# ══════════════════════════════════════════

def _run_career_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(240, 360))

        birth = data.get("birth", "未知")
        question = data.get("question", "")
        zodiac = get_zodiac(birth) or "未知"
        follow_up_num = data.get("follow_up_num", 1)

        user_prompt = f"""請進行職場運勢八字解析：
使用者生辰：{birth}（{zodiac}）
職場問題：{question}
這是第 {follow_up_num} 次解讀

請給出約350字的職場運勢八字解析，包含：
- 命格中的事業特質
- 近期職場運勢走向
- 針對問題的具體建議
- 貴人方位與時機提示
語氣溫柔神秘，像一位有智慧的命理師。"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content

        limit = FOLLOW_UP_LIMITS.get("career", 2)
        remaining = limit - follow_up_num

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": f"職場運勢第{follow_up_num}次",
                "reading": response_text,
                "category": "職場運勢",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"[職場運勢 tarot_logs 寫入錯誤] {e}")

        if follow_up_num == 1:
            mark_service_used(service_id)

        if remaining > 0:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"💬 您還可以追問 {remaining} 次\n"
                f"請直接輸入您的下一個職場問題 🌙"
            )
        else:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"🌟 本次職場運勢解析已完成\n"
                f"若有新的困惑，可重新購買服務 💎"
            )
            supabase.table("services").update({
                "status": "completed"
            }).eq("service_id", service_id).execute()

        footer = get_lucky_item_text()
        push_text(line_user_id, f"💼 職場運勢解析\n\n{response_text}{footer_hint}{footer}")

    except Exception as e:
        print(f"[職場運勢背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請稍後再試 🙏")


# ══════════════════════════════════════════
#  財運分析核心（背景執行）
# ══════════════════════════════════════════

def _run_wealth_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(240, 360))

        birth = data.get("birth", "未知")
        question = data.get("question", "")
        zodiac = get_zodiac(birth) or "未知"
        hexagram = random.choice(ICHING_HEXAGRAMS)
        follow_up_num = data.get("follow_up_num", 1)

        user_prompt = f"""請進行財運分析易經解讀：
使用者生辰：{birth}（{zodiac}）
財運問題：{question}
起卦得：{hexagram}
這是第 {follow_up_num} 次解讀

請給出約350字的財運易經解析，包含：
- 卦象對財運的啟示
- 近期財運走向
- 投資／理財建議
- 需要注意的財務風險
語氣溫柔神秘，像一位有智慧的命理師。"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content

        limit = FOLLOW_UP_LIMITS.get("wealth", 1)
        remaining = limit - follow_up_num

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": f"財運分析｜{hexagram}",
                "reading": response_text,
                "category": "財運分析",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"[財運分析 tarot_logs 寫入錯誤] {e}")

        if follow_up_num == 1:
            mark_service_used(service_id)

        if remaining > 0:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"💬 您還可以追問 {remaining} 次\n"
                f"請直接輸入您的下一個財運問題 🌙"
            )
        else:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"🌟 本次財運分析已完成\n"
                f"若有新的困惑，可重新購買服務 💎"
            )
            supabase.table("services").update({
                "status": "completed"
            }).eq("service_id", service_id).execute()

        footer = get_lucky_item_text()
        push_text(line_user_id, f"💰 財運分析｜{hexagram}\n\n{response_text}{footer_hint}{footer}")

    except Exception as e:
        print(f"[財運分析背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請稍後再試 🙏")


# ══════════════════════════════════════════
#  天書服務核心（背景執行）
# ══════════════════════════════════════════

def _run_double_chart_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(720, 1080))

        birth1 = data.get("birth1", "未知")
        birth2 = data.get("birth2", "未知")
        zodiac1 = get_zodiac(birth1) or "未知"
        zodiac2 = get_zodiac(birth2) or "未知"

        user_prompt = f"""請進行雙人合盤解析：
甲方生辰：{birth1}（{zodiac1}）
乙方生辰：{birth2}（{zodiac2}）

請給出約500字的深度合盤解讀，包含：
- 兩人的命格特質與相容性
- 感情/緣分分析
- 相處模式建議
- 未來發展走向
語氣溫柔神秘，像一位有智慧的命理師。"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content
        mark_service_used(service_id)

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": "雙人合盤",
                "reading": response_text,
                "category": "雙人合盤",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"tarot_logs 寫入錯誤: {e}")

        limit = FOLLOW_UP_LIMITS.get("double_chart", 1)
        follow_up_hint = (
            f"\n\n━━━━━━━━━━━━━━━\n"
            f"💬 您還可以追問 {limit} 次\n"
            f"請直接輸入您想深入了解的問題 🌙"
        )
        footer = get_lucky_item_text()
        push_text(line_user_id, f"💑 雙人合盤解析\n\n{response_text}{follow_up_hint}{footer}")

    except Exception as e:
        print(f"[雙人合盤背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請稍後再試 🙏")


def _run_year_fortune_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(720, 1080))

        birth = data.get("birth", "未知")
        zodiac = get_zodiac(birth) or "未知"
        tz = pytz.timezone("Asia/Taipei")
        current_year = datetime.datetime.now(tz).year

        user_prompt = f"""請進行流年運勢解析：
使用者生辰：{birth}（{zodiac}）
解析年份：{current_year} 年

請給出約500字的流年運勢報告，包含：
- {current_year} 年整體運勢走向
- 感情運
- 事業財運
- 健康運
- 每季重點提示
- 開運建議
語氣溫柔神秘，像一位有智慧的命理師。"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content
        mark_service_used(service_id)

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": "流年運勢",
                "reading": response_text,
                "category": "流年運勢",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"tarot_logs 寫入錯誤: {e}")

        limit = FOLLOW_UP_LIMITS.get("year_fortune", 1)
        follow_up_hint = (
            f"\n\n━━━━━━━━━━━━━━━\n"
            f"💬 您還可以追問 {limit} 次\n"
            f"請直接輸入您想深入了解的問題 🌙"
        )
        footer = get_lucky_item_text()
        push_text(line_user_id, f"📅 {current_year} 流年運勢報告\n\n{response_text}{follow_up_hint}{footer}")

    except Exception as e:
        print(f"[流年運勢背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請稍後再試 🙏")


def _run_ziwei_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(720, 1080))

        birth = data.get("birth", "未知")
        shichen = data.get("shichen", "不知道時辰")
        zodiac = get_zodiac(birth) or "未知"
        shichen_hint = f"出生時辰：{shichen}" if shichen != "不知道時辰" else "出生時辰：未知（將以主要格局推算）"

        user_prompt = f"""請進行紫微斗數命盤解析：
使用者生辰：{birth}（{zodiac}）
{shichen_hint}

請給出約500字的紫微斗數命盤解讀，包含：
- 命宮主星分析
- 個人命格特質
- 事業宮解析
- 感情宮解析
- 財帛宮解析
- 近期流年重點
語氣溫柔神秘，像一位有智慧的紫微命理師。"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content
        mark_service_used(service_id)

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": "紫微斗數",
                "reading": response_text,
                "category": "紫微斗數",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"tarot_logs 寫入錯誤: {e}")

        limit = FOLLOW_UP_LIMITS.get("ziwei", 2)
        follow_up_hint = (
            f"\n\n━━━━━━━━━━━━━━━\n"
            f"💬 您還可以追問 {limit} 次\n"
            f"請直接輸入您想深入了解的問題 🌙"
        )
        footer = get_lucky_item_text()
        push_text(line_user_id, f"⭐ 紫微斗數命盤解析\n\n{response_text}{follow_up_hint}{footer}")

    except Exception as e:
        print(f"[紫微斗數背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請稍後再試 🙏")


# ══════════════════════════════════════════
#  追問處理（天書服務共用）
# ══════════════════════════════════════════

def _run_follow_up_background(line_user_id, service_type, question, service_id, follow_up_num):
    try:
        time.sleep(random.uniform(240, 360))

        service_labels = {
            "double_chart": "💑 雙人合盤",
            "year_fortune":  "📅 流年運勢",
            "ziwei":         "⭐ 紫微斗數",
        }
        label = service_labels.get(service_type, "占卜")

        user_prompt = f"""這是{label}服務的第 {follow_up_num} 次追問。
用戶的追問：{question}

請根據之前的解讀脈絡，給出約250字的深入回答。
語氣溫柔神秘，像一位有智慧的命理師繼續為學生解惑。"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content

        new_count = increment_follow_up(service_id)
        limit = FOLLOW_UP_LIMITS.get(service_type, 0)
        remaining = limit - new_count

        try:
            supabase.table("tarot_logs").insert({
                "line_user_id": line_user_id,
                "card_name": f"{label}追問第{follow_up_num}次",
                "reading": response_text,
                "category": f"{label}追問",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"[追問 tarot_logs 寫入錯誤] {e}")

        if remaining > 0:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"💬 您還可以追問 {remaining} 次\n"
                f"請直接輸入您的問題 🌙"
            )
        else:
            footer_hint = (
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"🌟 本次服務追問次數已用完\n"
                f"感謝您的信任，祝您一切順心 💎"
            )

        push_text(line_user_id, f"{label}｜追問解讀\n\n{response_text}{footer_hint}")

    except Exception as e:
        print(f"[追問背景錯誤] {line_user_id}: {e}")
        push_text(line_user_id, "✨ 星辰訊號有些微干擾，請稍後再試 🙏")


# ══════════════════════════════════════════
#  每日推播 + 生日推播
# ══════════════════════════════════════════

def do_daily_push():
    print(f"[排程] 每日推播啟動：{datetime.datetime.now()}")
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.datetime.now(tz)
    today_str = today.strftime("%Y年%m月%d日")
    today_mmdd = today.strftime("%m-%d")

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
        birth_date = user.get("birth_date")
        zodiac = get_zodiac(birth_date) if birth_date else None

        is_birthday = False
        if birth_date:
            try:
                bd = datetime.datetime.strptime(birth_date, "%Y-%m-%d")
                if bd.strftime("%m-%d") == today_mmdd:
                    is_birthday = True
            except Exception:
                pass

        if is_birthday:
            try:
                birthday_prompt = f"""今天是使用者的生日！
生辰：{birth_date}，星座：{zodiac or "未知"}

請給出一段約150字的生日特別占卜祝福，包含：
- 溫暖的生日祝福
- 今年整體運勢提示
- 一句鼓勵的話
語氣溫柔神秘，充滿祝福與愛，像老師給學生的生日叮嚀。"""

                chat_completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": birthday_prompt}
                    ],
                    model="llama-3.3-70b-versatile",
                )
                birthday_reading = chat_completion.choices[0].message.content
                crystal_footer = get_lucky_item_text()
                birthday_text = (
                    f"🎂 生日快樂！\n\n"
                    f"親愛的，今天是您的特別日子 🌟\n"
                    f"老師特別為您準備了生日占卜祝福 ✨\n\n"
                    f"━━━━━━━━━━━━━━━\n\n"
                    f"{birthday_reading}{crystal_footer}"
                )
                push_text(line_user_id, birthday_text)
                continue
            except Exception as e:
                print(f"[生日推播失敗] {line_user_id}：{e}")

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
        except Exception as e:
            print(f"[排程] 推播失敗 {line_user_id}：{e}")


# ══════════════════════════════════════════
#  Flex Message 工廠
# ══════════════════════════════════════════

def build_confirm_token_flex(action_type, tokens_required, current_tokens):
    titles = {
        "spiritual": "🌌 靈性占卜",
        "deep":      "🆘 急救占卜"
    }
    descs = {
        "spiritual": "深度靈魂解析，探索您的靈性課題",
        "deep":      "感情、工作、人生卡關？讓星盤給你答案"
    }
    title = titles.get(action_type, "占卜確認")
    desc = descs.get(action_type, "")
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": title, "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": desc, "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "消耗代幣", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": f"{tokens_required} 顆", "color": "#E05C5C", "weight": "bold", "size": "sm", "flex": 1, "align": "end"}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "目前代幣", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": f"{current_tokens} 顆", "color": "#6B4FA0", "weight": "bold", "size": "sm", "flex": 1, "align": "end"}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "占卜後剩餘", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": f"{current_tokens - tokens_required} 顆", "color": "#333333", "size": "sm", "flex": 1, "align": "end"}
                ]}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "postback", "label": "✅ 確認，開始占卜", "data": f"confirm_{action_type}"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "postback", "label": "❌ 取消", "data": "cancel_reading"}}
            ]
        }
    }
    return FlexMessage(alt_text="確認消耗代幣", contents=FlexContainer.from_dict(flex_content))


def build_confirm_weekly_flex(reading_type, current_tokens, free_remaining):
    type_labels = {
        "tarot":  "🃏 塔羅一週運勢",
        "bazi":   "🀄 八字一週運勢",
        "iching": "☯️ 易經一週運勢",
    }
    label = type_labels.get(reading_type, "一週運勢")

    if free_remaining > 0:
        cost_text = "免費額度（剩餘 {} 次）".format(free_remaining)
        cost_color = "#27AE60"
        after_text = "使用後剩餘：{} 次免費".format(free_remaining - 1)
    else:
        cost_text = "1 顆代幣"
        cost_color = "#E05C5C"
        after_text = "使用後剩餘：{} 顆代幣".format(current_tokens - 1)

    flex_content = {
        "type": "bubble",
        "styles": {
            "header": {"backgroundColor": "#2D1B69"},
            "body":   {"backgroundColor": "#F8F4FF"}
        },
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": label, "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "老師將為您解讀本週完整星象能量 ✨", "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "本次費用", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": cost_text, "color": cost_color, "weight": "bold", "size": "sm", "flex": 3, "align": "end", "wrap": True}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "使用後", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": after_text, "color": "#888888", "size": "sm", "flex": 3, "align": "end", "wrap": True}
                ]},
                {"type": "separator"},
                {"type": "text", "text": "⏳ 解讀約需 1 分鐘，請耐心等候 🌙", "color": "#AAAAAA", "size": "xs", "wrap": True}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "postback", "label": "✅ 確認，開始解讀", "data": f"confirm_weekly_{reading_type}"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "postback", "label": "❌ 取消", "data": "cancel_reading"}}
            ]
        }
    }
    return FlexMessage(alt_text=f"確認{label}", contents=FlexContainer.from_dict(flex_content))


def build_confirm_service_flex(service_type, price, tokens_required, current_tokens, title, desc):
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": title, "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": desc, "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "服務費用", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": price, "color": "#E05C5C", "weight": "bold", "size": "sm", "flex": 2, "align": "end"}
                ]},
                {"type": "separator"},
                {"type": "text", "text": "付款後可立即開始使用 🌟", "color": "#888888", "size": "xs", "wrap": True},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "message", "label": "✅ 前往付款", "text": f"購買{service_type}"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "postback", "label": "❌ 取消", "data": "cancel_reading"}}
            ]
        }
    }
    return FlexMessage(alt_text=f"確認購買{title}", contents=FlexContainer.from_dict(flex_content))


def build_shichen_flex():
    rows = []
    shichen_pairs = [
        ("子時", "丑時"), ("寅時", "卯時"), ("辰時", "巳時"), ("午時", "未時"),
        ("申時", "酉時"), ("戌時", "亥時"),
    ]
    shichen_full = {
        "子時": "子時（23:00–01:00）", "丑時": "丑時（01:00–03:00）",
        "寅時": "寅時（03:00–05:00）", "卯時": "卯時（05:00–07:00）",
        "辰時": "辰時（07:00–09:00）", "巳時": "巳時（09:00–11:00）",
        "午時": "午時（11:00–13:00）", "未時": "未時（13:00–15:00）",
        "申時": "申時（15:00–17:00）", "酉時": "酉時（17:00–19:00）",
        "戌時": "戌時（19:00–21:00）", "亥時": "亥時（21:00–23:00）",
    }
    for left, right in shichen_pairs:
        rows.append({
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "secondary", "flex": 1, "height": "sm",
                 "action": {"type": "postback", "label": left, "data": f"shichen_{shichen_full[left]}"}},
                {"type": "button", "style": "secondary", "flex": 1, "height": "sm",
                 "action": {"type": "postback", "label": right, "data": f"shichen_{shichen_full[right]}"}}
            ]
        })
    rows.append({
        "type": "button", "style": "primary", "color": "#4A3080",
        "action": {"type": "postback", "label": "不知道時辰", "data": "shichen_不知道時辰"}
    })
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "⭐ 請選擇出生時辰", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "不知道也沒關係，仍可推算主要格局 🌙", "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows}
    }
    return FlexMessage(alt_text="請選擇出生時辰", contents=FlexContainer.from_dict(flex_content))


def build_weekly_type_select_flex():
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🌟 一週運勢", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "選擇您想要的占卜方式\n老師將為您解讀本週完整能量 ✨", "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "postback", "label": "🃏 塔羅一週運勢", "data": "weekly_tarot"}},
                {"type": "button", "style": "primary", "color": "#4A3080",
                 "action": {"type": "postback", "label": "🀄 八字一週運勢", "data": "weekly_bazi"}},
                {"type": "button", "style": "primary", "color": "#2D1B69",
                 "action": {"type": "postback", "label": "☯️ 易經一週運勢", "data": "weekly_iching"}}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "💎 消耗 1 次免費額度或 1 顆代幣", "color": "#AAAAAA", "size": "xs", "align": "center"}
            ]
        }
    }
    return FlexMessage(alt_text="一週運勢 - 選擇占卜方式", contents=FlexContainer.from_dict(flex_content))


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
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
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


def build_divination_service_flex():
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🔮 占卜服務", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "選擇您需要的占卜方式 ✨", "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "🌌 靈性占卜　2 顆代幣", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "深度靈魂解析，4 題問卷後老師為您解讀靈性課題", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "🆘 急救占卜　2 顆代幣", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "感情、工作、人生卡關？讓星盤深度為你指引方向", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "🎋 求籤問卜　1 顆代幣", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "五大類別誠心問卜，老師 解籤為您指引方向", "color": "#888888", "size": "xs", "wrap": True},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "message", "label": "🌌 靈性占卜", "text": "靈性占卜"}},
                {"type": "button", "style": "primary", "color": "#2D1B69",
                 "action": {"type": "message", "label": "🆘 急救占卜", "text": "急救占卜"}},
                {"type": "button", "style": "primary", "color": "#4A3080",
                 "action": {"type": "message", "label": "🎋 求籤問卜", "text": "求籤問卜"}}
            ]
        }
    }
    return FlexMessage(alt_text="占卜服務", contents=FlexContainer.from_dict(flex_content))


def build_life_navigation_flex():
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#1A0A3D"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🧭 人生迷航決策指南", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "迷茫時刻，讓老師為您指引方向 ✨", "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "💔 復合分析　NT$150／題，上限 5 題", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "塔羅牌解讀，每題抽一張牌，最多追問 5 次", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "💼 職場運勢　NT$800", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "八字命理深度解析，含 2 次追問機會", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "💰 財運分析　NT$500", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "易經卦象解讀，含 1 次追問機會", "color": "#888888", "size": "xs", "wrap": True},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "message", "label": "💔 復合分析 NT$150／題", "text": "復合分析"}},
                {"type": "button", "style": "primary", "color": "#4A3080",
                 "action": {"type": "message", "label": "💼 職場運勢 NT$800", "text": "職場運勢"}},
                {"type": "button", "style": "primary", "color": "#2D1B69",
                 "action": {"type": "message", "label": "💰 財運分析 NT$500", "text": "財運分析"}}
            ]
        }
    }
    return FlexMessage(alt_text="人生迷航決策指南", contents=FlexContainer.from_dict(flex_content))


def build_fortune_stick_category_flex():
    buttons = []
    category_icons = {
        "愛情": "💕", "事業學業": "💼", "財運": "💰", "健康": "🌿", "生活": "🏠"
    }
    for cat, icon in category_icons.items():
        buttons.append({
            "type": "button", "style": "secondary", "height": "sm",
            "action": {"type": "postback", "label": f"{icon} {cat}", "data": f"fortune_cat_{cat}"}
        })
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🎋 求籤問卜", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "誠心一問，神明為您指引方向 🙏", "color": "#C9B8FF", "size": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "請選擇問卜類別：", "color": "#555555", "size": "sm"},
                {"type": "separator"}
            ] + buttons
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "💎 每次消耗 1 顆代幣", "color": "#AAAAAA", "size": "xs", "align": "center"}
            ]
        }
    }
    return FlexMessage(alt_text="求籤問卜 - 選擇類別", contents=FlexContainer.from_dict(flex_content))


def build_fortune_stick_question_flex(category):
    questions = FORTUNE_STICK_CATEGORIES.get(category, [])
    buttons = []
    for i, q in enumerate(questions):
        buttons.append({
            "type": "button", "style": "secondary", "height": "sm",
            "action": {"type": "postback", "label": q, "data": f"fortune_q_{category}_{i}"}
        })
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"🎋 {category}・求籤", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "請選擇您想問的問題 🙏", "color": "#C9B8FF", "size": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": buttons
        }
    }
    return FlexMessage(alt_text=f"{category}求籤 - 選擇問題", contents=FlexContainer.from_dict(flex_content))


def build_fortune_stick_shake_flex(category, question):
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#1A0A3D"}, "body": {"backgroundColor": "#F0EBF8"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🎋 籤筒已備妥", "color": "#FFD700", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "請誠心默念後搖動籤筒 🙏", "color": "#C9B8FF", "size": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "text", "text": "📿 祈求文", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text",
                 "text": f"「信徒今因\n【{question}】\n前來問卜，欲知吉凶禍福，\n請賜籤指點迷津 🙏」",
                 "wrap": True, "color": "#444444", "size": "sm"},
                {"type": "separator"},
                {"type": "text", "text": "默念完畢，點下方按鈕搖籤 👇", "color": "#888888", "size": "xs", "align": "center"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#4A2080",
                 "action": {"type": "postback",
                            "label": "🎋 搖動籤筒！",
                            "data": f"fortune_shake_{category}_{question}"}}
            ]
        }
    }
    return FlexMessage(alt_text="搖動籤筒", contents=FlexContainer.from_dict(flex_content))


def build_token_flex(tokens, used, subscription_type="free"):
    remaining = max(0, FREE_READING_LIMIT - used)
    sub_status_text = "🆓 免費方案（每月 3 次）"
    remaining_text = f"{remaining} / {FREE_READING_LIMIT}"
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "💎 我的代幣", "color": "#FFFFFF", "weight": "bold", "size": "lg"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "目前方案", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": sub_status_text, "color": "#6B4FA0", "weight": "bold", "size": "xs", "flex": 3, "align": "end", "wrap": True}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "代幣餘額", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": f"{tokens} 顆", "color": "#6B4FA0", "weight": "bold", "size": "sm", "flex": 1, "align": "end"}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "免費占卜剩餘", "color": "#666666", "size": "sm", "flex": 2},
                    {"type": "text", "text": remaining_text, "color": "#6B4FA0", "weight": "bold", "size": "sm", "flex": 1, "align": "end"}
                ]},
                {"type": "separator"},
                {"type": "text", "text": "代幣用途：", "color": "#888888", "size": "xs", "weight": "bold"},
                {"type": "text", "text": "🌟 一週運勢（額度用完）1 顆｜🌌 靈性占卜 2 顆｜🆘 急救占卜 2 顆｜🎋 求籤問卜 1 顆", "color": "#AAAAAA", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "代幣獲取方式：", "color": "#888888", "size": "xs", "weight": "bold"},
                {"type": "text", "text": "每月自動補充 1 顆 🌙", "color": "#AAAAAA", "size": "xs"},
                {"type": "text", "text": "每週連續簽到 7 天送 1 顆 📅", "color": "#AAAAAA", "size": "xs"},
                {"type": "text", "text": "推薦好友滿 3 或 5 人送 1 顆 👥", "color": "#AAAAAA", "size": "xs"},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "message", "label": "✨ 購買代幣包", "text": "購買代幣"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "message", "label": "📅 每日簽到", "text": "簽到"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "message", "label": "📤 我的推薦碼", "text": "我的推薦碼"}}
            ]
        }
    }
    return FlexMessage(alt_text="我的代幣", contents=FlexContainer.from_dict(flex_content))


def build_token_shop_flex():
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "✨ 購買代幣包", "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "選擇最適合您的方案 🔮", "color": "#C9B8FF", "size": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "✨ 星塵入門包　$500 → 3 顆", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "踏入星盤的第一步，命運從這裡開始轉動", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "🌙 月光超值包　$1,200 → 8 顆", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "最受歡迎！平均每顆只要 $150，星辰常伴左右", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "🌌 星河豪華包　$2,000 → 15 顆", "color": "#B8860B", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "深度陪伴，讓老師全年守護你的每個轉折", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "💡 代幣用途", "color": "#888888", "size": "xs", "weight": "bold"},
                {"type": "text", "text": "🌟 一週運勢（額度用完）1 顆｜🌌 靈性占卜 2 顆｜🆘 急救占卜 2 顆｜🎋 求籤問卜 1 顆", "color": "#AAAAAA", "size": "xs", "wrap": True},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "message", "label": "✨ 星塵入門包 $500 → 3顆", "text": "購買星塵入門包"}},
                {"type": "button", "style": "primary", "color": "#4A3080",
                 "action": {"type": "message", "label": "🌙 月光超值包 $1,200 → 8顆", "text": "購買月光超值包"}},
                {"type": "button", "style": "primary", "color": "#2D1B69",
                 "action": {"type": "message", "label": "🌌 星河豪華包 $2,000 → 15顆", "text": "購買星河豪華包"}}
            ]
        }
    }
    return FlexMessage(alt_text="購買代幣包", contents=FlexContainer.from_dict(flex_content))


def build_tianbook_flex():
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#1A0A3D"}, "body": {"backgroundColor": "#F8F4FF"}},
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
                {"type": "text", "text": "選擇您想深度解析的方向：", "color": "#555555", "size": "sm"},
                {"type": "separator"},
                {"type": "text", "text": "💑 雙人合盤　NT$1,500", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "兩人命格相容性、緣分深度解析 + 1 次追問", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "📅 流年運勢　NT$1,000", "color": "#6B4FA0", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "本年度完整運勢報告 + 1 次追問", "color": "#888888", "size": "xs", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "⭐ 紫微斗數　NT$2,000", "color": "#B8860B", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "命宮主星、六大宮位深度解析 + 2 次追問", "color": "#888888", "size": "xs", "wrap": True},
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B4FA0",
                 "action": {"type": "message", "label": "💑 雙人合盤 NT$1,500", "text": "購買雙人合盤"}},
                {"type": "button", "style": "primary", "color": "#4A3080",
                 "action": {"type": "message", "label": "📅 流年運勢 NT$1,000", "text": "購買流年運勢"}},
                {"type": "button", "style": "primary", "color": "#2D1B69",
                 "action": {"type": "message", "label": "⭐ 紫微斗數 NT$2,000", "text": "購買紫微斗數"}}
            ]
        }
    }
    return FlexMessage(alt_text="專屬天書", contents=FlexContainer.from_dict(flex_content))


def build_settings_flex(user):
    birth = user.get("birth_date") or "尚未綁定"
    zodiac = get_zodiac(birth) if user.get("birth_date") else "尚未設定"
    locked_text = "🔒 已鎖定" if user.get("birthdate_locked") else "🔓 未鎖定"
    flex_content = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
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
                {"type": "separator"},
                {"type": "text", "text": "💡 說明", "color": "#888888", "size": "xs", "weight": "bold"},
                {"type": "text", "text": "生辰綁定後將鎖定，改綁需消耗 1 顆代幣", "color": "#AAAAAA", "size": "xs", "wrap": True},
                {"type": "text", "text": "生辰用於八字、紫微、流年等命盤解析", "color": "#AAAAAA", "size": "xs", "wrap": True},
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
                 "action": {"type": "message", "label": "🔔 推播設定", "text": "推播設定"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "uri", "label": "🛍️ 飾品商店", "uri": SHOP_URL}}
            ]
        }
    }
    return FlexMessage(alt_text="我的設定", contents=FlexContainer.from_dict(flex_content))


def build_date_picker_flex(is_rebound=False):
    desc_text = (
        "⚠️ 您的生辰已綁定。\n改綁將消耗 1 顆代幣\n\n請選擇新的出生日期 🌟"
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
                    {"type": "text", "text": f"🃏 {log.get('card_name', '未知')}", "weight": "bold", "color": "#6B4FA0", "size": "sm"},
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
        "styles": {"header": {"backgroundColor": "#2D1B69"}, "body": {"backgroundColor": "#F8F4FF"}},
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
                {"type": "button", "style": "secondary",
                 "action": {"type": "message", "label": "🔮 占卜服務", "text": "占卜服務"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "uri", "label": "🛍️ 查看開運飾品", "uri": SHOP_URL}}
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


@app.route("/shop", methods=["GET"])
def shop_page():
    from flask import redirect
    return redirect("https://crystal-shop-62a69.web.app/index.html", code=301)


@app.route("/push-now", methods=["GET"])
def push_now():
    token = request.args.get("token", "")
    if token != os.environ.get("PUSH_SECRET", ""):
        return "Unauthorized", 403
    do_daily_push()
    return "推播已觸發", 200


# ══════════════════════════════════════════
#  PayUni 金流路由
# ══════════════════════════════════════════

@app.route("/pay/go/<order_id>", methods=["GET"])
def ecpay_go(order_id):
    try:
        result = supabase.table("payments").select("*").eq("order_id", order_id).execute()
        if result.data:
            payment = result.data[0]
            if payment.get("status") == "confirmed":
                return "<html><body style='font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;'><h2>✅ 此訂單已完成付款</h2><p>請返回 LINE 查看詳情 🌟</p></body></html>", 200
            pkg_name = payment.get("package_type", "代幣包")
            confirm_url = f"{RENDER_URL}/pay/confirm"
            html, _ = ecpay_create(
                user_id=payment["user_id"], amount=payment["amount"],
                order_id=order_id, product_name=f"星運導航-{pkg_name}",
                confirm_url=confirm_url
            )
            return html
        result2 = supabase.table("orders").select("*").eq("order_id", order_id).execute()
        if result2.data:
            order = result2.data[0]
            if order.get("status") == "paid":
                return "<html><body style='font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;'><h2>✅ 此訂單已完成付款</h2><p>請返回 LINE 查看詳情 🌟</p></body></html>", 200
            service_names = {
                "double_chart": "雙人合盤解析",
                "year_fortune": "流年運勢報告",
                "ziwei":        "紫微斗數命盤",
                "love_reading": "復合分析",
                "career":       "職場運勢",
                "wealth":       "財運分析",
            }
            pkg_name = service_names.get(order["product_type"], order["product_type"])
            confirm_url = f"{RENDER_URL}/pay/confirm"
            html, _ = ecpay_create(
                user_id=order["user_id"], amount=order["amount"],
                order_id=order_id, product_name=f"星運導航-{pkg_name}",
                confirm_url=confirm_url
            )
            return html
        return "找不到訂單", 404
    except Exception as e:
        print(f"[ecpay_go 錯誤] {e}")
        return "伺服器錯誤，請返回 LINE 重新操作", 500


# ★ 修正：/pay/notify 使用正確欄位名 MerTradeNo
@app.route("/pay/notify", methods=["POST"])
def ecpay_notify():
    try:
        form_data = request.form.to_dict()
        print(f"[PayUni notify] 收到原始資料: {form_data}")
        if not verify_notify(form_data):
            print(f"[PayUni notify] 驗簽失敗：{form_data}")
            return "failure", 200
        from payuni import get_notify_data
        notify_data = get_notify_data(form_data)
        print(f"[PayUni notify] 解密後資料: {notify_data}")
        if is_payment_success(notify_data):
            order_id = notify_data.get("MerTradeNo", "")  # ★ 修正欄位名
            print(f"[PayUni notify] 付款成功，order_id={order_id}")
            _activate_payment(order_id)
        return "success", 200
    except Exception as e:
        print(f"[payuni_notify 錯誤] {e}")
        return "failure", 200


# ★ 修正：/pay/confirm 使用正確欄位名 MerTradeNo，POST 時先解密
@app.route("/pay/confirm", methods=["GET", "POST"])
def ecpay_confirm():
    try:
        print(f"[pay/confirm] method={request.method}, form={request.form.to_dict()}, args={request.args.to_dict()}")
        if request.method == "POST":
            form_data = request.form.to_dict()
            from payuni import get_notify_data, verify_notify as _verify
            if _verify(form_data):
                notify_data = get_notify_data(form_data)
                status   = notify_data.get("Status", "")
                order_id = notify_data.get("MerTradeNo", "")  # ★ 修正欄位名
            else:
                # 驗簽失敗時 fallback 直接讀原始欄位
                status   = form_data.get("Status", "")
                order_id = form_data.get("MerTradeNo", "")
        else:
            status   = request.args.get("Status", "")
            order_id = request.args.get("MerTradeNo", "")  # ★ 修正欄位名

        print(f"[pay/confirm] status={status}, order_id={order_id}")

        if status == "SUCCESS" and order_id:
            _activate_payment(order_id)
            return """<html>
            <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <title>付款成功</title>
            <style>body{font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;}h2{color:#6B4FA0;}p{color:#555;}</style>
            </head><body>
            <h2>✅ 付款成功！</h2><p>感謝您的購買 🌟</p>
            <p>請返回 LINE 查看最新狀態</p>
            <p style="color:#aaa;font-size:0.85em;margin-top:32px;">老師已準備好，隨時為您指引星途 🔮</p>
            </body></html>""", 200
        else:
            return """<html>
            <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <title>付款未完成</title>
            <style>body{font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;}h2{color:#cc4444;}p{color:#555;}</style>
            </head><body>
            <h2>❌ 付款未完成</h2><p>請返回 LINE 重新操作</p>
            <p style="color:#aaa;font-size:0.85em;">若有疑問請聯繫客服 🙏</p>
            </body></html>""", 200
    except Exception as e:
        print(f"[ecpay_confirm 錯誤] {e}")
        return "伺服器錯誤", 500


@app.route("/pay/cancel", methods=["GET"])
def ecpay_cancel():
    order_id = request.args.get("orderId", "")
    if order_id:
        try:
            supabase.table("payments").update({"status": "cancelled"}).eq("order_id", order_id).execute()
            supabase.table("orders").update({"status": "cancelled"}).eq("order_id", order_id).execute()
        except Exception as e:
            print(f"[ecpay_cancel 錯誤] {e}")
    return """<html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>已取消</title>
    <style>body{font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;}h2{color:#888;}p{color:#555;}</style>
    </head><body>
    <h2>❌ 付款已取消</h2><p>請返回 LINE 重新操作</p>
    </body></html>""", 200


# ══════════════════════════════════════════
#  LINE Webhook 路由
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
        "嗨，終於等到您了 🌙\n"
        "我是您的專屬『心靈星運導航老師』。\n"
        "在這個充滿雜音的世界裡，老師會在這裡傾聽您的煩惱，"
        "並透過星象與塔羅，為您尋找每天的平靜與方向。\n\n"
        "從今天起，把那些難以消化的情緒，都安心地交給老師吧 💫\n\n"
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
        "讓好友獲得代幣獎勵 💎"
    )


# ══════════════════════════════════════════
#  訊息處理
# ══════════════════════════════════════════

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    line_user_id = event.source.user_id
    user_msg = event.message.text.strip()
    user = get_or_create_user(line_user_id)

    needs_update = {}
    for field, default in [
        ("free_readings_used", 0),
        ("birthdate_locked", False),
        ("subscription_type", "free")
    ]:
        if user.get(field) is None:
            needs_update[field] = default
            user[field] = default
    if needs_update:
        supabase.table("users").update(needs_update).eq("line_user_id", line_user_id).execute()

    zodiac = get_zodiac(user.get("birth_date")) if user.get("birth_date") else None

    # ══════════════════════════════════════
    #  管理員指令
    # ══════════════════════════════════════
    if line_user_id == ADMIN_USER_ID:

        if user_msg in ["管理員指令", "admin", "Admin"]:
            reply_text = (
                "🔐 管理員指令清單\n\n"
                "【代幣管理】\n"
                "補代幣 [USER_ID] [數量]\n"
                "→ 為指定用戶補充代幣\n\n"
                "【用戶查詢】\n"
                "查用戶 [USER_ID]\n"
                "→ 查看用戶詳細資料\n\n"
                "【開通服務】\n"
                "開通服務 [USER_ID] [服務代碼]\n"
                "→ 手動開通付費服務\n\n"
                "服務代碼對照：\n"
                "• love_reading　復合分析\n"
                "• career　　　　職場運勢\n"
                "• wealth　　　　財運分析\n"
                "• double_chart　雙人合盤\n"
                "• year_fortune　流年運勢\n"
                "• ziwei　　　　 紫微斗數\n\n"
                "範例：\n"
                "開通服務 Uxxxxx double_chart\n"
                "補代幣 Uxxxxx 5\n"
                "查用戶 Uxxxxx"
            )
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                ))
            return

        if user_msg.startswith("補代幣 "):
            parts = user_msg.split()
            if len(parts) == 3:
                target_id = parts[1].strip()
                try:
                    amount = int(parts[2])
                    new_total = add_tokens(target_id, amount, "管理員補充")
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"✅ 已為 {target_id}\n補充 {amount} 顆代幣\n目前餘額：{new_total} 顆")]
                        ))
                except ValueError:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="⚠️ 格式錯誤\n補代幣 [LINE_USER_ID] [數量]")]
                        ))
            else:
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="⚠️ 格式：補代幣 [LINE_USER_ID] [數量]")]
                    ))
            return

        if user_msg.startswith("查用戶 "):
            parts = user_msg.split()
            if len(parts) == 2:
                target_id = parts[1].strip()
                result = supabase.table("users").select("*").eq("line_user_id", target_id).execute()
                if result.data:
                    u = result.data[0]
                    info = (
                        f"👤 用戶資料\n"
                        f"ID：{u.get('line_user_id', '')}\n"
                        f"代幣：{u.get('tokens', 0)} 顆\n"
                        f"方案：{u.get('plan', 'free')}\n"
                        f"生辰：{u.get('birth_date', '未綁定')}\n"
                        f"星座：{get_zodiac(u['birth_date']) if u.get('birth_date') else '未知'}\n"
                        f"免費次數已用：{u.get('free_readings_used', 0)}\n"
                        f"推薦碼：{u.get('referral_code', '')}\n"
                        f"推薦人數：{u.get('referral_count', 0)}\n"
                        f"推播：{'開' if u.get('daily_push') else '關'}"
                    )
                else:
                    info = f"❌ 找不到用戶：{target_id}"
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=info)]
                    ))
            return

        if user_msg.startswith("開通服務 "):
            parts = user_msg.split()
            if len(parts) == 3:
                target_id = parts[1].strip()
                service_type = parts[2].strip()
                valid_services = {
                    "love_reading": "💔 復合分析",
                    "career":       "💼 職場運勢",
                    "wealth":       "💰 財運分析",
                    "double_chart": "💑 雙人合盤",
                    "year_fortune": "📅 流年運勢",
                    "ziwei":        "⭐ 紫微斗數",
                }
                if service_type not in valid_services:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=(
                                "⚠️ 服務代碼錯誤\n\n"
                                "可用代碼：\n"
                                "love_reading / career / wealth\n"
                                "double_chart / year_fortune / ziwei"
                            ))]
                        ))
                    return

                try:
                    order_id = str(uuid.uuid4()).replace("-", "")[:20]
                    supabase.table("orders").insert({
                        "order_id": order_id,
                        "user_id": target_id,
                        "product_type": service_type,
                        "amount": 0,
                        "status": "paid",
                        "paid_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }).execute()
                    create_service(target_id, service_type, order_id)

                    svc = get_unused_service(target_id, service_type)
                    service_id = svc["service_id"] if svc else None
                    service_label = valid_services[service_type]

                    if service_type == "love_reading":
                        if service_id:
                            pending_state[target_id] = {
                                "mode": "love_reading",
                                "step": "question",
                                "service_id": service_id,
                                "question_num": 1
                            }
                        push_text(target_id,
                            f"🎁 {service_label}已由管理員為您開通！\n\n"
                            f"💔 請直接描述您的感情狀況或想問的問題 🃏\n\n"
                            f"💎 本服務共可提問 {FOLLOW_UP_LIMITS['love_reading']} 次"
                        )
                    elif service_type == "career":
                        if service_id:
                            pending_state[target_id] = {
                                "mode": "career",
                                "step": "birth",
                                "service_id": service_id,
                                "follow_up_num": 1,
                                "data": {}
                            }
                        push_text(target_id,
                            f"🎁 {service_label}已由管理員為您開通！\n\n"
                            f"💼 請輸入您的出生日期開始解析 🔮\n\n格式範例：1990-05-20"
                        )
                    elif service_type == "wealth":
                        if service_id:
                            pending_state[target_id] = {
                                "mode": "wealth",
                                "step": "birth",
                                "service_id": service_id,
                                "follow_up_num": 1,
                                "data": {}
                            }
                        push_text(target_id,
                            f"🎁 {service_label}已由管理員為您開通！\n\n"
                            f"💰 請輸入您的出生日期開始解析 🔮\n\n格式範例：1990-05-20"
                        )
                    elif service_type == "double_chart":
                        if service_id:
                            pending_state[target_id] = {
                                "mode": "double_chart",
                                "step": "birth1",
                                "service_id": service_id,
                                "data": {}
                            }
                        push_text(target_id,
                            f"🎁 {service_label}已由管理員為您開通！\n\n"
                            f"💑 請輸入甲方（您自己）的出生日期 🔮\n\n格式範例：1990-05-20"
                        )
                    elif service_type == "year_fortune":
                        if service_id:
                            pending_state[target_id] = {
                                "mode": "year_fortune",
                                "step": "birth",
                                "service_id": service_id,
                                "data": {}
                            }
                        push_text(target_id,
                            f"🎁 {service_label}已由管理員為您開通！\n\n"
                            f"📅 請輸入您的出生日期開始解析 🔮\n\n格式範例：1990-05-20"
                        )
                    elif service_type == "ziwei":
                        if service_id:
                            pending_state[target_id] = {
                                "mode": "ziwei",
                                "step": "birth",
                                "service_id": service_id,
                                "data": {}
                            }
                        push_text(target_id,
                            f"🎁 {service_label}已由管理員為您開通！\n\n"
                            f"⭐ 請輸入您的出生日期開始排盤 🔮\n\n格式範例：1990-05-20\n下一步將請您選擇出生時辰"
                        )

                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=(
                                f"✅ 開通成功！\n\n"
                                f"用戶：{target_id}\n"
                                f"服務：{service_label}\n\n"
                                f"已推播引導訊息給用戶 🌟"
                            ))]
                        ))
                except Exception as e:
                    print(f"[開通服務錯誤] {e}")
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"❌ 開通失敗：{e}")]
                        ))
            else:
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="⚠️ 格式：開通服務 [USER_ID] [服務代碼]")]
                    ))
            return

    # ══════════════════════════════════════
    #  pending_state 狀態機
    # ══════════════════════════════════════
    if line_user_id in pending_state:
        state = pending_state[line_user_id]
        mode = state.get("mode")
        step = state.get("step")

        if mode == "spiritual":
            data = state.get("data", {})
            if step == "q1":
                data["q1"] = user_msg
                state["data"] = data
                state["step"] = "q2"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="🌙 第二題\n\n您希望在哪個方面得到老師的指引？\n（感情、事業、家庭、人生方向...）")]
                    ))
                return
            elif step == "q2":
                data["q2"] = user_msg
                state["data"] = data
                state["step"] = "q3"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="💫 第三題\n\n請描述您目前的心情狀態\n（平靜、焦慮、迷茫、期待...）")]
                    ))
                return
            elif step == "q3":
                data["q3"] = user_msg
                state["data"] = data
                state["step"] = "q4"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="✨ 最後一題\n\n您對未來最深的期望是什麼？\n（請用一句話描述）")]
                    ))
                return
            elif step == "q4":
                data["q4"] = user_msg
                data["birth"] = user.get("birth_date") or "未知"
                pending_state.pop(line_user_id, None)
                wait_msg = random.choice(WAITING_MSGS_SPIRITUAL)
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=wait_msg)]
                    ))
                t = threading.Thread(target=_run_spiritual_background, args=(line_user_id, data, zodiac), daemon=True)
                t.start()
                return

        elif mode == "deep" and step == "question":
            reading_type = state.get("type", "tarot")
            pending_state.pop(line_user_id, None)
            wait_msg = random.choice(WAITING_MSGS_DEEP)
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=wait_msg)]
                ))
            do_reading_async(line_user_id, user_msg, reading_type, True, zodiac, user)
            return

        elif mode == "daily" and step == "question":
            reading_type = state.get("type", "tarot")
            can_read, quota_msg = check_free_reading_quota(line_user_id, user)
            if not can_read:
                pending_state.pop(line_user_id, None)
                fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
                current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
                if current_tokens >= 1:
                    use_tokens(line_user_id, 1, "今日運勢（免費額度已用完）")
                    if reading_type == "tarot":
                        wait_msg = random.choice(WAITING_MSGS_TAROT)
                    elif reading_type == "bazi":
                        wait_msg = random.choice(WAITING_MSGS_BAZI)
                    else:
                        wait_msg = random.choice(WAITING_MSGS_ICHING)
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"💎 已消耗 1 顆代幣（免費額度已用完）\n\n{wait_msg}")]
                        ))
                    do_reading_async(line_user_id, user_msg, reading_type, False, zodiac, user)
                else:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=quota_msg)]
                        ))
                return
            pending_state.pop(line_user_id, None)
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
            do_reading_async(line_user_id, user_msg, reading_type, False, zodiac, user)
            return

        elif mode == "double_chart":
            data = state.get("data", {})
            if step == "birth1":
                parsed = parse_birth_input(user_msg)
                if not parsed:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="⚠️ 格式不正確，請重新輸入\n\n📅 請使用西元國曆，例如：\n1990-05-20\n1990/05/20\n1990年5月20日")]
                        ))
                    return
                data["birth1"] = parsed
                state["data"] = data
                state["step"] = "birth1_confirm"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📅 甲方生辰：{parsed}\n\n確認正確嗎？\n✅ 輸入「確認」繼續\n❌ 輸入「重填」重新輸入")]
                    ))
                return
            elif step == "birth1_confirm":
                if user_msg in ["確認", "是", "對", "正確"]:
                    state["step"] = "birth2"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"✅ 甲方生辰確認：{data['birth1']}\n\n請輸入乙方（另一人）的出生日期 🌙\n\n📅 格式：1990-05-20\n（西元國曆）")]
                        ))
                elif user_msg in ["重填", "重新", "不對", "錯了"]:
                    state["step"] = "birth1"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="請重新輸入甲方出生日期：\n\n📅 格式：1990-05-20")]
                        ))
                else:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"📅 甲方生辰：{data.get('birth1')}\n\n請輸入「確認」或「重填」")]
                        ))
                return
            elif step == "birth2":
                parsed = parse_birth_input(user_msg)
                if not parsed:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="⚠️ 格式不正確，請重新輸入\n\n📅 請使用西元國曆，例如：\n1990-05-20")]
                        ))
                    return
                data["birth2"] = parsed
                state["data"] = data
                state["step"] = "birth2_confirm"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📅 乙方生辰：{parsed}\n\n確認正確嗎？\n✅ 輸入「確認」開始解析\n❌ 輸入「重填」重新輸入")]
                    ))
                return
            elif step == "birth2_confirm":
                if user_msg in ["確認", "是", "對", "正確"]:
                    service_id = state.get("service_id")
                    data_copy = data.copy()
                    pending_state.pop(line_user_id, None)
                    wait_msg = random.choice(WAITING_MSGS_TIANBOOK)
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=wait_msg)]
                        ))
                    t = threading.Thread(target=_run_double_chart_background, args=(line_user_id, data_copy, service_id), daemon=True)
                    t.start()
                elif user_msg in ["重填", "重新", "不對", "錯了"]:
                    state["step"] = "birth2"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="請重新輸入乙方出生日期：\n\n📅 格式：1990-05-20")]
                        ))
                else:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"📅 乙方生辰：{data.get('birth2')}\n\n請輸入「確認」或「重填」")]
                        ))
                return

        elif mode == "year_fortune":
            data = state.get("data", {})
            if step == "birth":
                parsed = parse_birth_input(user_msg)
                if not parsed:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="⚠️ 格式不正確，請重新輸入\n\n📅 請使用西元國曆，例如：\n1990-05-20")]
                        ))
                    return
                data["birth"] = parsed
                state["data"] = data
                state["step"] = "birth_confirm"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📅 您的生辰：{parsed}\n\n確認正確嗎？\n✅ 輸入「確認」開始解析\n❌ 輸入「重填」重新輸入")]
                    ))
                return
            elif step == "birth_confirm":
                if user_msg in ["確認", "是", "對", "正確"]:
                    service_id = state.get("service_id")
                    data_copy = data.copy()
                    pending_state.pop(line_user_id, None)
                    wait_msg = random.choice(WAITING_MSGS_TIANBOOK)
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=wait_msg)]
                        ))
                    t = threading.Thread(target=_run_year_fortune_background, args=(line_user_id, data_copy, service_id), daemon=True)
                    t.start()
                elif user_msg in ["重填", "重新", "不對", "錯了"]:
                    state["step"] = "birth"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="請重新輸入您的出生日期：\n\n📅 格式：1990-05-20")]
                        ))
                else:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"📅 您的生辰：{data.get('birth')}\n\n請輸入「確認」或「重填」")]
                        ))
                return

        elif mode == "ziwei":
            data = state.get("data", {})
            if step == "birth":
                parsed = parse_birth_input(user_msg)
                if not parsed:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="⚠️ 格式不正確，請重新輸入\n\n📅 請使用西元國曆，例如：\n1990-05-20")]
                        ))
                    return
                data["birth"] = parsed
                state["data"] = data
                state["step"] = "birth_confirm"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📅 您的生辰：{parsed}\n\n確認正確嗎？\n✅ 輸入「確認」繼續選擇時辰\n❌ 輸入「重填」重新輸入")]
                    ))
                return
            elif step == "birth_confirm":
                if user_msg in ["確認", "是", "對", "正確"]:
                    state["step"] = "shichen"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[build_shichen_flex()]
                        ))
                elif user_msg in ["重填", "重新", "不對", "錯了"]:
                    state["step"] = "birth"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="請重新輸入您的出生日期：\n\n📅 格式：1990-05-20")]
                        ))
                else:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"📅 您的生辰：{data.get('birth')}\n\n請輸入「確認」或「重填」")]
                        ))
                return

        elif mode == "love_reading":
            if step == "question":
                service_id = state.get("service_id")
                question_num = state.get("question_num", 1)
                pending_state.pop(line_user_id, None)
                wait_msg = random.choice(WAITING_MSGS_LOVE)
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=wait_msg)]
                    ))
                if service_id and question_num > 1:
                    increment_follow_up(service_id)
                t = threading.Thread(
                    target=_run_love_reading_background,
                    args=(line_user_id, user_msg, question_num, service_id),
                    daemon=True
                )
                t.start()
                limit = FOLLOW_UP_LIMITS.get("love_reading", 5)
                if question_num < limit:
                    pending_state[line_user_id] = {
                        "mode": "love_reading",
                        "step": "question",
                        "service_id": service_id,
                        "question_num": question_num + 1
                    }
                return

        elif mode == "career":
            data = state.get("data", {})
            if step == "birth":
                parsed = parse_birth_input(user_msg)
                if not parsed:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="⚠️ 格式不正確，請重新輸入\n\n📅 請使用西元國曆，例如：\n1990-05-20")]
                        ))
                    return
                data["birth"] = parsed
                state["data"] = data
                state["step"] = "birth_confirm"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📅 您的生辰：{parsed}\n\n確認正確嗎？\n✅ 輸入「確認」繼續\n❌ 輸入「重填」重新輸入")]
                    ))
                return
            elif step == "birth_confirm":
                if user_msg in ["確認", "是", "對", "正確"]:
                    state["step"] = "question"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"✅ 生辰確認：{data['birth']}\n\n💼 請描述您的職場困境或想了解的方向\n\n例如：轉職時機、升遷機會、職場人際...")]
                        ))
                elif user_msg in ["重填", "重新", "不對", "錯了"]:
                    state["step"] = "birth"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="請重新輸入您的出生日期：\n\n📅 格式：1990-05-20")]
                        ))
                else:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"📅 您的生辰：{data.get('birth')}\n\n請輸入「確認」或「重填」")]
                        ))
                return
            elif step == "question":
                service_id = state.get("service_id")
                follow_up_num = state.get("follow_up_num", 1)
                data["question"] = user_msg
                data["follow_up_num"] = follow_up_num
                limit = FOLLOW_UP_LIMITS.get("career", 2)
                pending_state.pop(line_user_id, None)
                wait_msg = random.choice(WAITING_MSGS_CAREER)
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=wait_msg)]
                    ))
                if follow_up_num < limit:
                    pending_state[line_user_id] = {
                        "mode": "career",
                        "step": "question",
                        "service_id": service_id,
                        "follow_up_num": follow_up_num + 1,
                        "data": {"birth": data.get("birth", "")}
                    }
                t = threading.Thread(
                    target=_run_career_background,
                    args=(line_user_id, data.copy(), service_id),
                    daemon=True
                )
                t.start()
                return

        elif mode == "follow_up":
            if step == "question":
                service_type = state.get("service_type")
                service_id   = state.get("service_id")
                follow_up_num = state.get("follow_up_num", 1)
                pending_state.pop(line_user_id, None)
                wait_msg = random.choice(WAITING_MSGS_TIANBOOK)
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=wait_msg)]
                    ))
                t = threading.Thread(
                    target=_run_follow_up_background,
                    args=(line_user_id, service_type, user_msg, service_id, follow_up_num),
                    daemon=True
                )
                t.start()
                return

        elif mode == "wealth":
            data = state.get("data", {})
            if step == "birth":
                parsed = parse_birth_input(user_msg)
                if not parsed:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="⚠️ 格式不正確，請重新輸入\n\n📅 請使用西元國曆，例如：\n1990-05-20")]
                        ))
                    return
                data["birth"] = parsed
                state["data"] = data
                state["step"] = "birth_confirm"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📅 您的生辰：{parsed}\n\n確認正確嗎？\n✅ 輸入「確認」繼續\n❌ 輸入「重填」重新輸入")]
                    ))
                return
            elif step == "birth_confirm":
                if user_msg in ["確認", "是", "對", "正確"]:
                    state["step"] = "question"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"✅ 生辰確認：{data['birth']}\n\n💰 請描述您的財運困境或想了解的方向\n\n例如：投資時機、偏財運、財務規劃...")]
                        ))
                elif user_msg in ["重填", "重新", "不對", "錯了"]:
                    state["step"] = "birth"
                    pending_state[line_user_id] = state
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="請重新輸入您的出生日期：\n\n📅 格式：1990-05-20")]
                        ))
                else:
                    with ApiClient(configuration) as api_client:
                        MessagingApi(api_client).reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"📅 您的生辰：{data.get('birth')}\n\n請輸入「確認」或「重填」")]
                        ))
                return
            elif step == "question":
                service_id = state.get("service_id")
                follow_up_num = state.get("follow_up_num", 1)
                data["question"] = user_msg
                data["follow_up_num"] = follow_up_num
                limit = FOLLOW_UP_LIMITS.get("wealth", 1)
                pending_state.pop(line_user_id, None)
                wait_msg = random.choice(WAITING_MSGS_WEALTH)
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=wait_msg)]
                    ))
                if follow_up_num < limit:
                    pending_state[line_user_id] = {
                        "mode": "wealth",
                        "step": "question",
                        "service_id": service_id,
                        "follow_up_num": follow_up_num + 1,
                        "data": {"birth": data.get("birth", "")}
                    }
                t = threading.Thread(
                    target=_run_wealth_background,
                    args=(line_user_id, data.copy(), service_id),
                    daemon=True
                )
                t.start()
                return

    # ══════════════════════════════════════
    #  一般指令處理
    # ══════════════════════════════════════

    if user_msg in ["一週運勢"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_weekly_type_select_flex()]
            ))
        return

    elif user_msg in ["占卜服務"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_divination_service_flex()]
            ))
        return

    elif user_msg in ["人生迷航決策指南"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_life_navigation_flex()]
            ))
        return

    elif user_msg in ["復合分析", "購買復合分析"]:
        service = get_unused_service(line_user_id, "love_reading")
        if service:
            pending_state[line_user_id] = {
                "mode": "love_reading",
                "step": "question",
                "service_id": service["service_id"],
                "question_num": 1
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💔 復合分析｜塔羅解讀\n\n"
                        "老師將為您抽牌解讀感情狀況 🃏\n\n"
                        "📝 請描述您的感情狀況或想問的問題\n\n"
                        "例如：\n「我和前任分開 3 個月，對方最近突然聯絡我，復合機會大嗎？」\n\n"
                        f"💎 本服務共可提問 {FOLLOW_UP_LIMITS['love_reading']} 次，每次 NT$150"
                    ))]
                ))
            return
        try:
            order_id = create_order(line_user_id, "love_reading", 150)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            reply_text = (
                "💔 復合分析　NT$150／題\n\n"
                "✨ 服務內容：\n• 塔羅牌逐題解讀\n• 每題抽一張牌\n"
                f"• 最多可提問 {FOLLOW_UP_LIMITS['love_reading']} 題\n• 無需生辰\n\n"
                f"請點以下連結完成付款：\n{pay_url}\n\n付款完成後老師會立即引導您開始 🌟"
            )
        except Exception as e:
            print(f"[復合分析建立訂單錯誤] {e}")
            reply_text = "✨ 付款連結建立失敗，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["職場運勢", "購買職場運勢"]:
        service = get_unused_service(line_user_id, "career")
        if service:
            pending_state[line_user_id] = {
                "mode": "career",
                "step": "birth",
                "service_id": service["service_id"],
                "follow_up_num": 1,
                "data": {}
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💼 職場運勢｜八字解析\n\n"
                        "老師將以八字命理為您解讀職場運勢 🔮\n\n"
                        "請輸入您的出生日期：\n\n"
                        "格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                        "⚠️ 請使用西元國曆（陽曆）"
                    ))]
                ))
            return
        try:
            order_id = create_order(line_user_id, "career", 800)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            reply_text = (
                "💼 職場運勢　NT$800\n\n"
                "✨ 服務內容：\n• 八字命理職場深度解析\n• 需提供生辰\n"
                f"• 含 {FOLLOW_UP_LIMITS['career']} 次追問機會\n• 等待約 5 分鐘\n\n"
                f"請點以下連結完成付款：\n{pay_url}\n\n付款完成後老師會立即引導您開始 🌟"
            )
        except Exception as e:
            print(f"[職場運勢建立訂單錯誤] {e}")
            reply_text = "✨ 付款連結建立失敗，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["財運分析", "購買財運分析"]:
        service = get_unused_service(line_user_id, "wealth")
        if service:
            pending_state[line_user_id] = {
                "mode": "wealth",
                "step": "birth",
                "service_id": service["service_id"],
                "follow_up_num": 1,
                "data": {}
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💰 財運分析｜易經解讀\n\n"
                        "老師將以易經卦象為您解讀財運走向 🔮\n\n"
                        "請輸入您的出生日期：\n\n"
                        "格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                        "⚠️ 請使用西元國曆（陽曆）"
                    ))]
                ))
            return
        try:
            order_id = create_order(line_user_id, "wealth", 500)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            reply_text = (
                "💰 財運分析　NT$500\n\n"
                "✨ 服務內容：\n• 易經卦象財運深度解析\n• 需提供生辰\n"
                f"• 含 {FOLLOW_UP_LIMITS['wealth']} 次追問機會\n• 等待約 5 分鐘\n\n"
                f"請點以下連結完成付款：\n{pay_url}\n\n付款完成後老師會立即引導您開始 🌟"
            )
        except Exception as e:
            print(f"[財運分析建立訂單錯誤] {e}")
            reply_text = "✨ 付款連結建立失敗，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["求籤問卜", "求籤", "問卜"]:
        fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
        if current_tokens < 1:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💎 代幣不足\n\n"
                        f"求籤問卜需要 1 顆代幣\n"
                        f"您目前只有 {current_tokens} 顆\n\n"
                        "輸入「購買代幣」補充代幣 🌙"
                    ))]
                ))
            return
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_fortune_stick_category_flex()]
            ))
        return

    elif user_msg in ["靈性占卜"]:
        fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
        if current_tokens < 2:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💎 代幣不足\n\n"
                        f"靈性占卜需要 2 顆代幣\n"
                        f"您目前只有 {current_tokens} 顆\n\n"
                        "輸入「購買代幣」補充代幣 🌙"
                    ))]
                ))
            return
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_confirm_token_flex("spiritual", 2, current_tokens)]
            ))
        return

    elif user_msg in ["急救占卜"]:
        fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
        if current_tokens < 2:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💎 代幣不足\n\n"
                        f"急救占卜需要 2 顆代幣\n"
                        f"您目前只有 {current_tokens} 顆\n\n"
                        "輸入「購買代幣」補充代幣 🌙"
                    ))]
                ))
            return
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_confirm_token_flex("deep", 2, current_tokens)]
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
                    "💎 老師送您 1 顆代幣作為獎勵 🌟\n\n"
                    "下週繼續簽到，繼續累積代幣吧 ✨"
                )
            else:
                reply_text = (
                    f"✅ 簽到成功！本週已簽到 {days} / 7 天\n"
                    f"📅 本週起算日：{week_start}\n"
                    f"💪 還差 {days_left} 天完成本週目標\n"
                    f"週日完成全勤可獲得 1 顆代幣 💎"
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
                reply_text = "💫 您已經使用過推薦碼囉！每位用戶只能使用一次 🌙"
            else:
                referrer = supabase.table("users").select("line_user_id").eq("referral_code", ref_code).execute()
                if not referrer.data:
                    reply_text = "🔍 找不到這組推薦碼，請確認是否輸入正確 🙏\n格式：推薦碼 XXXXXX"
                elif referrer.data[0]["line_user_id"] == line_user_id:
                    reply_text = "😅 不能使用自己的推薦碼喔～"
                else:
                    process_referral(line_user_id, ref_code)
                    reply_text = "✅ 推薦碼使用成功！\n您的好友已獲得推薦紀錄 💎\n\n感謝您的加入，老師會好好照顧您的 🌟"
        else:
            reply_text = "📤 推薦碼輸入格式：\n推薦碼 XXXXXX\n\n（請在「推薦碼」後加一個空格，再輸入碼）"
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
            f"🎁 推薦好友方式：\n"
            f"請好友加入後傳送「推薦碼 {ref_code}」\n\n"
            f"💎 推薦滿 3 人送 1 顆代幣\n"
            f"💎 推薦滿 5 人再送 1 顆代幣 🌟"
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

    elif user_msg in ["雙人合盤", "購買雙人合盤"]:
        service = get_unused_service(line_user_id, "double_chart")
        if service:
            pending_state[line_user_id] = {
                "mode": "double_chart",
                "step": "birth1",
                "service_id": service["service_id"],
                "data": {}
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💑 雙人合盤解析\n\n"
                        "老師將為您解讀兩人的命格相容性 🔮\n\n"
                        "📅 請輸入甲方（您自己）的出生日期\n\n"
                        "格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                        "⚠️ 請使用西元國曆（陽曆）"
                    ))]
                ))
            return
        try:
            order_id = create_order(line_user_id, "double_chart", 1500)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            reply_text = (
                "💑 雙人合盤解析　NT$1,500\n\n"
                "✨ 服務內容：\n• 兩人命格特質與相容性分析\n• 感情緣分深度解讀\n"
                f"• 相處模式建議\n• 未來發展走向\n• 含 {FOLLOW_UP_LIMITS['double_chart']} 次追問\n\n"
                f"請點以下連結完成付款：\n{pay_url}\n\n付款完成後老師會立即引導您開始 🌟"
            )
        except Exception as e:
            print(f"[雙人合盤建立訂單錯誤] {e}")
            reply_text = "✨ 付款連結建立失敗，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["流年運勢", "購買流年運勢"]:
        service = get_unused_service(line_user_id, "year_fortune")
        if service:
            pending_state[line_user_id] = {
                "mode": "year_fortune",
                "step": "birth",
                "service_id": service["service_id"],
                "data": {}
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "📅 流年運勢解析\n\n"
                        "老師將為您推演今年完整運勢 🔮\n\n"
                        "請輸入您的出生日期：\n\n"
                        "格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                        "⚠️ 請使用西元國曆（陽曆）"
                    ))]
                ))
            return
        try:
            order_id = create_order(line_user_id, "year_fortune", 1000)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            reply_text = (
                "📅 流年運勢報告　NT$1,000\n\n"
                "✨ 服務內容：\n• 本年度整體運勢走向\n• 感情運、事業財運、健康運\n"
                f"• 每季重點提示\n• 個人化開運建議\n• 含 {FOLLOW_UP_LIMITS['year_fortune']} 次追問\n\n"
                f"請點以下連結完成付款：\n{pay_url}\n\n付款完成後老師會立即引導您開始 🌟"
            )
        except Exception as e:
            print(f"[流年運勢建立訂單錯誤] {e}")
            reply_text = "✨ 付款連結建立失敗，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["紫微斗數", "購買紫微斗數"]:
        service = get_unused_service(line_user_id, "ziwei")
        if service:
            pending_state[line_user_id] = {
                "mode": "ziwei",
                "step": "birth",
                "service_id": service["service_id"],
                "data": {}
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "⭐ 紫微斗數命盤解析\n\n"
                        "老師將為您排出專屬命盤 🔮\n\n"
                        "請輸入您的出生日期：\n\n"
                        "格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n"
                        "⚠️ 請使用西元國曆（陽曆）\n下一步將請您選擇出生時辰"
                    ))]
                ))
            return
        try:
            order_id = create_order(line_user_id, "ziwei", 2000)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            reply_text = (
                "⭐ 紫微斗數命盤　NT$2,000\n\n"
                "✨ 服務內容：\n• 命宮主星深度分析\n• 個人命格特質解讀\n"
                f"• 事業、感情、財帛三宮解析\n• 近期流年重點提示\n• 含 {FOLLOW_UP_LIMITS['ziwei']} 次追問\n\n"
                f"請點以下連結完成付款：\n{pay_url}\n\n付款完成後老師會立即引導您開始 🌟"
            )
        except Exception as e:
            print(f"[紫微斗數建立訂單錯誤] {e}")
            reply_text = "✨ 付款連結建立失敗，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["購買代幣", "代幣包", "購買代幣包"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_token_shop_flex()]
            ))
        return

    elif user_msg in ["購買星塵入門包", "購買月光超值包", "購買星河豪華包"]:
        pkg_map = {
            "購買星塵入門包": {"amount": 500,  "tokens": 3,  "name": "星塵入門包", "label": "✨ 星塵入門包"},
            "購買月光超值包": {"amount": 1200, "tokens": 8,  "name": "月光超值包", "label": "🌙 月光超值包"},
            "購買星河豪華包": {"amount": 2000, "tokens": 15, "name": "星河豪華包", "label": "🌌 星河豪華包"},
        }
        pkg = pkg_map[user_msg]
        try:
            order_id = str(uuid.uuid4()).replace("-", "")[:20]
            supabase.table("payments").insert({
                "user_id": line_user_id,
                "order_id": order_id,
                "amount": pkg["amount"],
                "currency": "TWD",
                "package_type": pkg["name"],
                "tokens_to_add": pkg["tokens"],
                "status": "pending"
            }).execute()
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            reply_text = (
                f"{pkg['label']}\n"
                f"NT${pkg['amount']} → {pkg['tokens']} 顆代幣\n\n"
                f"請點以下連結完成付款：\n{pay_url}\n\n"
                f"付款完成後代幣將立即入帳 🌟"
            )
        except Exception as e:
            print(f"[代幣包建立付款錯誤] {e}")
            reply_text = "✨ 付款連結建立失敗，請稍後再試 🙏"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
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
                    messages=[TextMessage(text="🔒 您的生辰已綁定，改綁需消耗 1 顆代幣。\n但您目前代幣不足 💎\n\n可儲值代幣後再試 🌙")]
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
        plan_name = "🆓 免費版"
        birth = fd.get("birth_date") or "尚未綁定"
        zodiac_text = get_zodiac(birth) if fd.get("birth_date") else "尚未綁定生辰"
        locked_text = "🔒 已鎖定" if fd.get("birthdate_locked") else "🔓 未鎖定"
        used = fd.get("free_readings_used") or 0
        remaining = max(0, FREE_READING_LIMIT - used)
        reply_text = (
            f"您目前的方案：{plan_name}\n"
            f"💎 代幣餘額：{fd.get('tokens', 0)} 顆\n"
            f"🎂 綁定生辰：{birth}（{locked_text}）\n"
            f"⭐ 星座：{zodiac_text}\n"
            f"🌙 免費占卜剩餘：{remaining} / {FREE_READING_LIMIT} 次"
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

    elif user_msg in ["飾品商店", "開運商店", "商店"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"🛍️ 星運導航・開運飾品商店\n\n點此前往查看專屬開運物 ✨\n{SHOP_URL}")]
            ))
        return

    elif user_msg in ["說明", "使用說明", "help", "Help", "/help"]:
        reply_text = (
            "🔮 星運導航使用說明\n\n"
            "【選單功能】\n"
            "🌟 一週運勢 → 塔羅／八字／易經本週完整解讀\n"
            "（每月 3 次免費，額度用完消耗 1 顆代幣）\n\n"
            "🔮 占卜服務 → 靈性占卜／急救占卜（各 2 顆代幣）\n"
            "　　　　　　求籤問卜（1 顆代幣）\n\n"
            "🧭 人生迷航決策指南\n"
            "　💔 復合分析 NT$150／題（塔羅，最多5題）\n"
            "　💼 職場運勢 NT$800（八字，含2次追問）\n"
            "　💰 財運分析 NT$500（易經，含1次追問）\n\n"
            "📖 專屬天書 → 合盤／流年／紫微斗數\n\n"
            "💎 我的代幣 → 查詢餘額與儲值\n\n"
            "【其他指令】\n"
            "⚙️ 我的設定 → 管理生辰、推播、飾品商店\n"
            "📅 簽到 → 每週全勤送代幣\n"
            "📤 我的推薦碼 → 推薦好友送代幣\n"
            "📖 我的紀錄 → 查看最近 5 次占卜\n"
            "👑 星運VIP → 查看代幣方案\n\n"
            "💡 若老師沒有立即回應，\n"
            "請稍等約 1 分鐘後查看結果 ✨"
        )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif user_msg in ["星運VIP", "VIP", "vip", "升級VIP", "星運 VIP"]:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_token_shop_flex()]
            ))
        return

    else:
        guide_msgs = [
            "親愛的，有什麼心事想跟老師說嗎？🌙\n\n請從下方選單選擇服務，老師隨時為您解讀 ✨\n\n輸入「說明」查看所有功能",
            "老師在這裡陪著您 💫\n\n請點選下方選單，或輸入以下指令開始：\n🌟 一週運勢\n🔮 占卜服務\n📖 專屬天書",
            "星辰正在等待您的問題 🌟\n\n請從選單選擇您需要的服務\n或輸入「說明」查看完整功能列表 ✨",
        ]
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=random.choice(guide_msgs))]
            ))
        return


# ══════════════════════════════════════════
#  Postback 事件處理
# ══════════════════════════════════════════

@handler.add(PostbackEvent)
def handle_postback(event):
    line_user_id = event.source.user_id
    data = event.postback.data
    user = get_or_create_user(line_user_id)
    zodiac = get_zodiac(user.get("birth_date")) if user.get("birth_date") else None

    if data == "bind_birth":
        selected_date = event.postback.params.get("date")
        if not selected_date:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="⚠️ 日期選取失敗，請重試 🙏")]
                ))
            return
        is_locked = user.get("birthdate_locked", False)
        if is_locked:
            if user.get("tokens", 0) < 1:
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="🔒 改綁生辰需消耗 1 顆代幣，但您目前代幣不足 💎")]
                    ))
                return
            use_tokens(line_user_id, 1, "改綁生辰")
        zodiac_new = get_zodiac(selected_date) or "未知"
        supabase.table("users").update({
            "birth_date": selected_date,
            "birthdate_locked": True
        }).eq("line_user_id", line_user_id).execute()
        reply_text = (
            f"✅ 生辰綁定成功！\n\n"
            f"🎂 生辰：{selected_date}\n"
            f"⭐ 星座：{zodiac_new}\n\n"
            f"🔒 生辰已鎖定，改綁需消耗 1 顆代幣\n\n"
            f"老師已記下您的星象資料，\n"
            f"往後的占卜解讀將更加精準 🌟"
        )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            ))
        return

    elif data == "cancel_reading":
        pending_state.pop(line_user_id, None)
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="已取消，隨時傳訊息給老師 🌙")]
            ))
        return

    elif data == "confirm_spiritual":
        fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
        if current_tokens < 2:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="💎 代幣不足，請先購買代幣 🌙\n\n輸入「購買代幣」查看方案")]
                ))
            return
        use_tokens(line_user_id, 2, "靈性占卜")
        pending_state[line_user_id] = {
            "mode": "spiritual",
            "step": "q1",
            "data": {"birth": user.get("birth_date") or "未知"}
        }
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=(
                    "🌌 靈性占卜開始\n\n"
                    "老師將透過 4 個問題，深度解讀您的靈性課題 ✨\n\n"
                    "━━━━━━━━━━━━━━━\n"
                    "🌙 第一題\n\n"
                    "最近最困擾您的事情是什麼？\n"
                    "（請用 1~2 句話描述）"
                ))]
            ))
        return

    elif data == "confirm_deep":
        fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
        if current_tokens < 2:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="💎 代幣不足，請先購買代幣 🌙\n\n輸入「購買代幣」查看方案")]
                ))
            return
        use_tokens(line_user_id, 2, "急救占卜")
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_type_select_flex(mode="deep")]
            ))
        return

    elif data in ["deep_tarot", "deep_bazi", "deep_iching"]:
        type_map = {"deep_tarot": "tarot", "deep_bazi": "bazi", "deep_iching": "iching"}
        reading_type = type_map[data]
        pending_state[line_user_id] = {"mode": "deep", "step": "question", "type": reading_type}
        type_labels = {"tarot": "塔羅牌", "bazi": "八字命理", "iching": "易經起卦"}
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=(
                    f"🆘 急救占卜｜{type_labels[reading_type]}\n\n"
                    f"老師已準備好為您深度解讀 🔮\n\n"
                    f"請直接描述您的困境或想問的問題：\n\n"
                    f"（感情、工作、人生抉擇...都可以）"
                ))]
            ))
        return

    elif data in ["daily_tarot", "daily_bazi", "daily_iching"]:
        type_map = {"daily_tarot": "tarot", "daily_bazi": "bazi", "daily_iching": "iching"}
        reading_type = type_map[data]
        pending_state[line_user_id] = {"mode": "daily", "step": "question", "type": reading_type}
        type_labels = {"tarot": "塔羅牌", "bazi": "八字命理", "iching": "易經起卦"}
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=(
                    f"🌙 今日運勢｜{type_labels[reading_type]}\n\n"
                    f"老師將為您解讀今日能量 ✨\n\n"
                    f"請告訴老師您今天最想了解的方向：\n\n"
                    f"（感情、工作、財運、整體運勢...）"
                ))]
            ))
        return

    elif data in ["weekly_tarot", "weekly_bazi", "weekly_iching"]:
        type_map = {"weekly_tarot": "tarot", "weekly_bazi": "bazi", "weekly_iching": "iching"}
        reading_type = type_map[data]
        fresh = supabase.table("users").select("tokens, free_readings_used").eq("line_user_id", line_user_id).execute()
        fd = fresh.data[0] if fresh.data else {}
        current_tokens = fd.get("tokens") or 0
        used = fd.get("free_readings_used") or 0
        free_remaining = max(0, FREE_READING_LIMIT - used)
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_confirm_weekly_flex(reading_type, current_tokens, free_remaining)]
            ))
        return

    elif data.startswith("confirm_weekly_"):
        reading_type = data.replace("confirm_weekly_", "")
        fresh = supabase.table("users").select("tokens, free_readings_used").eq("line_user_id", line_user_id).execute()
        fd = fresh.data[0] if fresh.data else {}
        current_tokens = fd.get("tokens") or 0
        used = fd.get("free_readings_used") or 0
        free_remaining = max(0, FREE_READING_LIMIT - used)

        if free_remaining > 0:
            increment_free_reading(line_user_id, user)
            cost_note = "（使用免費額度）"
        elif current_tokens >= 1:
            use_tokens(line_user_id, 1, "一週運勢")
            cost_note = "（消耗 1 顆代幣）"
        else:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=(
                        "💎 免費額度已用完，且代幣不足\n\n"
                        "輸入「購買代幣」補充代幣 🌙"
                    ))]
                ))
            return

        type_labels = {"tarot": "🃏 塔羅", "bazi": "🀄 八字", "iching": "☯️ 易經"}
        label = type_labels.get(reading_type, "一週運勢")
        wait_msg = random.choice(WAITING_MSGS_WEEKLY)
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"{wait_msg}\n\n{cost_note}")]
            ))
        t = threading.Thread(
            target=_run_weekly_fortune_background,
            args=(line_user_id, reading_type, zodiac, user),
            daemon=True
        )
        t.start()
        return

    elif data.startswith("fortune_cat_"):
        category = data.replace("fortune_cat_", "")
        fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
        if current_tokens < 1:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="💎 代幣不足，請先購買代幣 🌙\n\n輸入「購買代幣」查看方案")]
                ))
            return
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[build_fortune_stick_question_flex(category)]
            ))
        return

    elif data.startswith("fortune_q_"):
        parts = data.replace("fortune_q_", "").split("_", 1)
        if len(parts) == 2:
            category = parts[0]
            try:
                q_idx = int(parts[1])
                questions = FORTUNE_STICK_CATEGORIES.get
(category, [])
                question = questions[q_idx] if q_idx < len(questions) else "您的問題"
            except (ValueError, IndexError):
                question = "您的問題"
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[build_fortune_stick_shake_flex(category, question)]
                ))
        return

    elif data.startswith("fortune_shake_"):
        payload = data.replace("fortune_shake_", "")
        sep_idx = payload.find("_")
        if sep_idx == -1:
            return
        category = payload[:sep_idx]
        question = payload[sep_idx + 1:]

        fresh = supabase.table("users").select("tokens").eq("line_user_id", line_user_id).execute()
        current_tokens = fresh.data[0].get("tokens", 0) if fresh.data else 0
        if current_tokens < 1:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="💎 代幣不足，請先購買代幣 🌙")]
                ))
            return

        use_tokens(line_user_id, 1, f"求籤問卜｜{category}")
        stick = random.choice(FORTUNE_STICKS)

        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=(
                    f"🎋 籤筒搖動中...\n\n"
                    f"老師正在為您解讀第 {stick['num']} 籤 🔮\n"
                    f"請稍候約 15 秒 🙏"
                ))]
            ))
        t = threading.Thread(
            target=_run_fortune_stick_background,
            args=(line_user_id, category, question, stick),
            daemon=True
        )
        t.start()
        return

    elif data.startswith("shichen_"):
        shichen = data.replace("shichen_", "")
        if line_user_id in pending_state:
            state = pending_state[line_user_id]
            if state.get("mode") == "ziwei" and state.get("step") == "shichen":
                state["data"]["shichen"] = shichen
                service_id = state.get("service_id")
                data_copy = state["data"].copy()
                pending_state.pop(line_user_id, None)
                wait_msg = random.choice(WAITING_MSGS_TIANBOOK)
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=wait_msg)]
                    ))
                t = threading.Thread(
                    target=_run_ziwei_background,
                    args=(line_user_id, data_copy, service_id),
                    daemon=True
                )
                t.start()
                return
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="⚠️ 狀態已過期，請重新開始 🙏")]
            ))
        return

    elif data.startswith("follow_up_"):
        service_type = data.replace("follow_up_", "")
        svc = get_active_service(line_user_id, service_type)
        if not svc:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="⚠️ 追問次數已用完，或找不到有效服務 🙏")]
                ))
            return
        service_labels = {
            "double_chart": "💑 雙人合盤",
            "year_fortune":  "📅 流年運勢",
            "ziwei":         "⭐ 紫微斗數",
        }
        label = service_labels.get(service_type, "占卜")
        pending_state[line_user_id] = {
            "mode": "follow_up",
            "step": "question",
            "service_type": service_type,
            "service_id": svc["service_id"],
            "follow_up_num": (svc.get("follow_up_count") or 0) + 1
        }
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=(
                    f"{label}｜追問\n\n"
                    f"請直接輸入您想深入了解的問題 🌙"
                ))]
            ))
        return

    else:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="老師在這裡 🌙\n請從選單選擇服務，或輸入「說明」查看功能 ✨")]
            ))
        return


# ══════════════════════════════════════════
#  APScheduler 排程
# ══════════════════════════════════════════

scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(
    do_daily_push, "cron",
    hour=8, minute=0,
    id="daily_push",
    replace_existing=True
)
scheduler.start()


# ══════════════════════════════════════════
#  啟動
# ══════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

