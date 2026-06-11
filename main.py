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
    {"num": 52, "grade": "中平籤", "poem": "欲速則不達其功，穩紮穩打方為上 abuse，步步為營守正道，終有一日見光明"},
    {"num": 60, "grade": "小吉籤", "poem": "潮起潮落皆有時, 人生起伏是常事, 保持初心不忘本, 終將迎來好時節"},
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
- 你的名字是「星運導航老師」，不是 AI，不是 ChatGPT，不是 any 語言模型
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
#  付款開通共用函式 (⚠️ 關鍵修正區)
# ══════════════════════════════════════════

def _activate_payment(mer_trade_no):
    """
    ⚠️ 關鍵修正：
    PAYUNi 回傳的 order_id 其實是我們產生的 mer_trade_no (時間戳記隨機碼)，
    因此我們必須先用 mer_trade_no 查出資料庫紀錄，再取得真正的 UUID order_id 來進行開通。
    """
    if not mer_trade_no:
        return
    try:
        print(f"[_activate_payment] 開始開通，收到 mer_trade_no: {mer_trade_no}")
        
        # 1. 先用 mer_trade_no 查詢 payments 表 (代幣包)
        result = supabase.table("payments").select("*").eq("mer_trade_no", mer_trade_no).execute()
        if result.data:
            payment = result.data[0]
            actual_order_id = payment["order_id"] # 取得真正的 UUID order_id
            if payment.get("status") == "confirmed":
                print(f"[_activate_payment] 訂單 {actual_order_id} 已經是 confirmed 狀態，跳過。")
                return
            _activate_subscription(actual_order_id, payment)
            return
            
        # 2. 如果 payments 查不到，再用 mer_trade_no 查詢 orders 表 (單項服務)
        result2 = supabase.table("orders").select("*").eq("mer_trade_no", mer_trade_no).execute()
        if result2.data:
            order = result2.data[0]
            actual_order_id = order["order_id"] # 取得真正的 UUID order_id
            if order.get("status") == "paid":
                print(f"[_activate_payment] 訂單 {actual_order_id} 已經是 paid 狀態，跳過。")
                return
            _activate_single_service(actual_order_id, order)
            return
            
        print(f"[_activate_payment] ⚠️ 警告：在資料庫中找不到對應 mer_trade_no: {mer_trade_no} 的訂單！")
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

        # ⚠️ 關鍵修正：將 {{q2}} 修正為 {q2}，確保變數能正確代入
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

        # ⚠️ 關鍵修正：將 "of" 修正為 "的"，使 AI 中文語氣更自然
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
#  LINE Webhook 接收與事件處理器 (⚠️ 核心功能補全)
# ══════════════════════════════════════════

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK", 200


@handler.add(FollowEvent)
def handle_follow(event):
    """處理新用戶加入好友事件"""
    try:
        user_id = event.source.user_id
        get_or_create_user(user_id)
        
        welcome_text = (
            "🔮 歡迎來到「口袋裡的心靈星運導航」！\n\n"
            "我是您的專屬星運導航老師 🌙\n"
            "在這裡，我將透過塔羅、八字、易經與紫微，為您在感情、職場與人生轉折處指引方向。\n\n"
            "🎁 老師已送您 1 顆【心靈代幣】作為見面禮！\n"
            "您可以點擊下方選單的「今日運勢」或「一週運勢」開始體驗 🌟\n\n"
            "💡 若您有好友推薦碼，請直接輸入推薦碼（例如：REF_XXXXXX），雙方皆可獲得代幣獎勵喔！"
        )
        push_text(user_id, welcome_text)
    except Exception as e:
        print(f"[FollowEvent 錯誤] {e}")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理使用者傳送的文字訊息"""
    try:
        user_id = event.source.user_id
        text = event.message.text.strip()
        user = get_or_create_user(user_id)
        
        # 1. 處理推薦碼綁定
        if text.upper().startswith("REF_"):
            if user.get("referred_by"):
                push_text(user_id, "⚠️ 您已經綁定過推薦人囉！")
                return
            process_referral(user_id, text)
            return

        # 2. 處理狀態機 (pending_state)
        if user_id in pending_state:
            state = pending_state[user_id]
            mode = state["mode"]
            
            # 💑 雙人合盤狀態機
            if mode == "double_chart":
                if state["step"] == "birth1":
                    birth1 = parse_birth_input(text)
                    if not birth1:
                        push_text(user_id, "⚠️ 格式不正確，請重新輸入甲方生日（例如：1995-01-01）：")
                        return
                    state["data"]["birth1"] = birth1
                    state["step"] = "birth2"
                    push_text(user_id, "📅 收到甲方生日！\n\n接下來請輸入乙方（對方）的出生日期：")
                    return
                elif state["step"] == "birth2":
                    birth2 = parse_birth_input(text)
                    if not birth2:
                        push_text(user_id, "⚠️ 格式不正確，請重新輸入乙方生日（例如：1995-01-01）：")
                        return
                    state["data"]["birth2"] = birth2
                    push_text(user_id, random.choice(WAITING_MSGS_TIANBOOK))
                    
                    t = threading.Thread(
                        target=_run_double_chart_background,
                        args=(user_id, state["data"], state["service_id"]),
                        daemon=True
                    )
                    t.start()
                    pending_state.pop(user_id, None)
                    return

            # 📅 流年運勢狀態機
            elif mode == "year_fortune":
                if state["step"] == "birth":
                    birth = parse_birth_input(text)
                    if not birth:
                        push_text(user_id, "⚠️ 格式不正確，請重新輸入您的生日（例如：1995-01-01）：")
                        return
                    state["data"]["birth"] = birth
                    push_text(user_id, random.choice(WAITING_MSGS_TIANBOOK))
                    
                    t = threading.Thread(
                        target=_run_year_fortune_background,
                        args=(user_id, state["data"], state["service_id"]),
                        daemon=True
                    )
                    t.start()
                    pending_state.pop(user_id, None)
                    return

            # ⭐ 紫微斗數狀態機
            elif mode == "ziwei":
                if state["step"] == "birth":
                    birth = parse_birth_input(text)
                    if not birth:
                        push_text(user_id, "⚠️ 格式不正確，請重新輸入您的生日（例如：1995-01-01）：")
                        return
                    state["data"]["birth"] = birth
                    state["step"] = "shichen"
                    push_flex(user_id, build_shichen_flex())
                    return

            # 💔 復合分析狀態機
            elif mode == "love_reading":
                if state["step"] == "question":
                    q_num = state["question_num"]
                    push_text(user_id, random.choice(WAITING_MSGS_LOVE))
                    
                    t = threading.Thread(
                        target=_run_love_reading_background,
                        args=(user_id, text, q_num, state["service_id"]),
                        daemon=True
                    )
                    t.start()
                    
                    if q_num < FOLLOW_UP_LIMITS["love_reading"]:
                        state["question_num"] += 1
                    else:
                        pending_state.pop(user_id, None)
                    return

            # 💼 職場運勢狀態機
            elif mode == "career":
                if state["step"] == "birth":
                    birth = parse_birth_input(text)
                    if not birth:
                        push_text(user_id, "⚠️ 格式不正確，請重新輸入您的生日（例如：1995-01-01）：")
                        return
                    state["data"]["birth"] = birth
                    state["step"] = "question"
                    push_text(user_id, "📝 收到您的生日！\n\n請直接輸入您目前在職場上遇到的困惑或問題：")
                    return
                elif state["step"] == "question":
                    state["data"]["question"] = text
                    push_text(user_id, random.choice(WAITING_MSGS_CAREER))
                    
                    t = threading.Thread(
                        target=_run_career_background,
                        args=(user_id, state["data"], state["service_id"]),
                        daemon=True
                    )
                    t.start()
                    pending_state.pop(user_id, None)
                    return

            # 💰 財運分析狀態機
            elif mode == "wealth":
                if state["step"] == "birth":
                    birth = parse_birth_input(text)
                    if not birth:
                        push_text(user_id, "⚠️ 格式不正確，請重新輸入您的生日（例如：1995-01-01）：")
                        return
                    state["data"]["birth"] = birth
                    state["step"] = "question"
                    push_text(user_id, "📝 收到您的生日！\n\n請直接輸入您目前在財富或投資上的困惑：")
                    return
                elif state["step"] == "question":
                    state["data"]["question"] = text
                    push_text(user_id, random.choice(WAITING_MSGS_WEALTH))
                    
                    t = threading.Thread(
                        target=_run_wealth_background,
                        args=(user_id, state["data"], state["service_id"]),
                        daemon=True
                    )
                    t.start()
                    pending_state.pop(user_id, None)
                    return

            # 🌌 靈性占卜狀態機
            elif mode == "spiritual":
                q_step = state["step"]
                if q_step == "birth":
                    birth = parse_birth_input(text)
                    if not birth:
                        push_text(user_id, "⚠️ 格式不正確，請重新輸入您的生日（例如：1995-01-01）：")
                        return
                    state["data"]["birth"] = birth
                    state["step"] = "q1"
                    push_text(user_id, "📝 1/4：最近最困擾您、讓您感到心累的事是什麼呢？")
                    return
                elif q_step == "q1":
                    state["data"]["q1"] = text
                    state["step"] = "q2"
                    push_text(user_id, "📝 2/4：您最希望在靈魂或心靈的哪個方面得到指引？")
                    return
                elif q_step == "q2":
                    state["data"]["q2"] = text
                    state["step"] = "q3"
                    push_text(user_id, "📝 3/4：您目前的心情狀態，可以用幾個形容詞來描述嗎？")
                    return
                elif q_step == "q3":
                    state["data"]["q3"] = text
                    state["step"] = "q4"
                    push_text(user_id, "📝 4/4：您對未來最美好的期望或願景是什麼？")
                    return
                elif q_step == "q4":
                    state["data"]["q4"] = text
                    push_text(user_id, random.choice(WAITING_MSGS_SPIRITUAL))
                    
                    zodiac = get_zodiac(state["data"]["birth"])
                    t = threading.Thread(
                        target=_run_spiritual_background,
                        args=(user_id, state["data"], zodiac),
                        daemon=True
                    )
                    t.start()
                    pending_state.pop(user_id, None)
                    return

            # 🔮 急救占卜文字輸入狀態機 (塔羅/八字/易經)
            elif mode.startswith("deep_reading_"):
                reading_type = mode.split("_")[2]
                push_text(user_id, random.choice(WAITING_MSGS_DEEP))
                
                birth = user.get("birth_date")
                zodiac = get_zodiac(birth) if birth else None
                do_reading_async(user_id, text, reading_type, True, zodiac, user)
                pending_state.pop(user_id, None)
                return

        # 3. 處理一般文字指令
        if text == "今日運勢" or text == "每日運勢":
            push_flex(user_id, build_type_select_flex("daily"))
            return
        elif text == "一週運勢" or text == "每週運勢":
            push_flex(user_id, build_weekly_type_select_flex())
            return
        elif text == "占卜服務":
            push_flex(user_id, build_divination_service_flex())
            return
        elif text == "人生迷航決策指南" or text == "人生迷航":
            push_flex(user_id, build_life_navigation_flex())
            return
        elif text == "求籤問卜" or text == "求籤":
            push_flex(user_id, build_fortune_stick_category_flex())
            return
        elif text == "我的代幣" or text == "代幣":
            used = user.get("free_readings_used") or 0
            push_flex(user_id, build_token_flex(user["tokens"], used, user.get("subscription_type", "free")))
            return
        elif text == "購買代幣":
            push_flex(user_id, build_token_shop_flex())
            return
        elif text == "專屬天書" or text == "天書":
            push_flex(user_id, build_tianbook_flex())
            return
        elif text == "我的設定" or text == "設定":
            push_flex(user_id, build_settings_flex(user))
            return
        elif text == "簽到":
            success, res = do_checkin(user_id)
            if not success:
                push_text(user_id, "🌟 親愛的，您今天已經簽到過囉！明天再來找老師吧 ✨")
            else:
                days = res["days"]
                reward_msg = "\n🎉 恭喜！您本週已連續簽到 7 天，獲得 1 顆代幣獎勵！💎" if res["reward"] else ""
                push_text(user_id, f"📅 簽到成功！\n\n本週已累計簽到 {days} 天 🌟{reward_msg}\n老師祝您今天一切順心 ✨")
            return
        elif text == "我的推薦碼":
            ref_code = user.get("referral_code", "")
            push_text(user_id, 
                f"📤 您的專屬推薦碼為：\n`{ref_code}`\n\n"
                f"分享推薦碼給好友，當好友加入並輸入您的推薦碼時：\n"
                f"👥 推薦滿 3 人或 5 人，您將獲得 1 顆代幣獎勵！💎\n"
                f"目前已成功推薦：{user.get('referral_count', 0)} 人 ✨"
            )
            return

        # 4. 處理購買單項服務指令
        elif text in ["購買double_chart", "購買雙人合盤"]:
            order_id = create_order(user_id, "double_chart", 1500)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"💑 老師已為您準備好「雙人合盤解析」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，請回到此處開始占卜 ✨")
            return
        elif text in ["購買year_fortune", "購買流年運勢"]:
            order_id = create_order(user_id, "year_fortune", 1000)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"📅 老師已為您準備好「流年運勢報告」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，請回到此處開始占卜 ✨")
            return
        elif text in ["購買ziwei", "購買紫微斗數"]:
            order_id = create_order(user_id, "ziwei", 2000)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"⭐ 老師已為您準備好「紫微斗數命盤」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，請回到此處開始占卜 ✨")
            return
        elif text in ["購買love_reading", "購買復合分析"]:
            order_id = create_order(user_id, "love_reading", 150)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"💔 老師已為您準備好「復合分析」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，請回到此處開始占卜 ✨")
            return
        elif text in ["購買career", "購買職場運勢"]:
            order_id = create_order(user_id, "career", 800)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"💼 老師已為您準備好「職場運勢」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，請回到此處開始占卜 ✨")
            return
        elif text in ["購買wealth", "購買財運分析"]:
            order_id = create_order(user_id, "wealth", 500)
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"💰 老師已為您準備好「財運分析」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，請回到此處開始占卜 ✨")
            return

        # 5. 處理代幣包購買
        elif text == "購買星塵入門包":
            order_id = create_order(user_id, "token_pack_3", 500)
            supabase.table("payments").insert({
                "order_id": order_id,
                "user_id": user_id,
                "amount": 500,
                "package_type": "星塵入門包",
                "tokens_to_add": 3,
                "status": "pending"
            }).execute()
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"✨ 老師已為您準備好「星塵入門包」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，代幣會自動入帳喔 💎")
            return
        elif text == "購買月光超值包":
            order_id = create_order(user_id, "token_pack_8", 1200)
            supabase.table("payments").insert({
                "order_id": order_id,
                "user_id": user_id,
                "amount": 1200,
                "package_type": "月光超值包",
                "tokens_to_add": 8,
                "status": "pending"
            }).execute()
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"🌙 老師已為您準備好「月光超值包」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，代幣會自動入帳喔 💎")
            return
        elif text == "購買星河豪華包":
            order_id = create_order(user_id, "token_pack_15", 2000)
            supabase.table("payments").insert({
                "order_id": order_id,
                "user_id": user_id,
                "amount": 2000,
                "package_type": "星河豪華包",
                "tokens_to_add": 15,
                "status": "pending"
            }).execute()
            pay_url = f"{RENDER_URL}/pay/go/{order_id}"
            push_text(user_id, f"🌌 老師已為您準備好「星河豪華包」付款通道：\n\n🔗 點此前往安全付款 → {pay_url}\n\n付款完成後，代幣會自動入帳喔 💎")
            return

        # 6. 處理代幣占卜指令
        elif text == "靈性占卜":
            push_flex(user_id, build_confirm_token_flex("spiritual", 2, user["tokens"]))
            return
        elif text == "急救占卜":
            push_flex(user_id, build_confirm_token_flex("deep", 2, user["tokens"]))
            return

        # 7. 處理管理員指令
        elif text.startswith("補充代幣") and user_id == ADMIN_USER_ID:
            parts = text.split()
            if len(parts) == 3:
                target_uid = parts[1]
                amount = int(parts[2])
                new_bal = add_tokens(target_uid, amount, "管理員手動補充")
                push_text(user_id, f"✅ 已成功為用戶 {target_uid} 補充 {amount} 顆代幣。目前餘額：{new_bal} 顆。")
                push_text(target_uid, f"🎁 老師為您手動補充了 {amount} 顆代幣！目前餘額：{new_bal} 顆 💎")
            return

        # 8. 處理追問
        for svc_type in ["double_chart", "year_fortune", "ziwei", "career", "wealth"]:
            svc = get_active_service(user_id, svc_type)
            if svc:
                follow_up_num = (svc.get("follow_up_count") or 0) + 1
                push_text(user_id, f"💬 收到您的追問！老師正在為您仔細推演中，請稍候約 5 分鐘 🔮")
                
                if svc_type == "career":
                    t = threading.Thread(
                        target=_run_career_background,
                        args=(user_id, {"birth": user.get("birth_date", "未知"), "question": text, "follow_up_num": follow_up_num}, svc["service_id"]),
                        daemon=True
                    )
                elif svc_type == "wealth":
                    t = threading.Thread(
                        target=_run_wealth_background,
                        args=(user_id, {"birth": user.get("birth_date", "未知"), "question": text, "follow_up_num": follow_up_num}, svc["service_id"]),
                        daemon=True
                    )
                else:
                    t = threading.Thread(
                        target=_run_follow_up_background,
                        args=(user_id, svc_type, text, svc["service_id"], follow_up_num),
                        daemon=True
                    )
                t.start()
                return

        # 9. 預設兜底
        has_quota, quota_msg = check_free_reading_quota(user_id, user)
        if has_quota:
            push_text(user_id, 
                "親愛的，星象已接收到您的呼喚 ✨\n\n"
                "💡 老師建議您：\n"
                "👉 輸入「今日運勢」來看看今天的能量指引\n"
                "👉 輸入「占卜服務」探索更深層的心靈解答 🔮\n"
                "👉 直接點選下方選單開始體驗喔 🌙"
            )
        else:
            push_text(user_id, quota_msg)

    except Exception as e:
        print(f"[handle_message 錯誤] {e}")


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 LINE Postback 互動事件"""
    try:
        user_id = event.source.user_id
        data = event.postback.data
        user = get_or_create_user(user_id)

        # 1. 處理生日綁定
        if data == "bind_birth":
            selected_date = event.postback.params.get("date")
            if not selected_date:
                return
            is_rebound = bool(user.get("birth_date") and user.get("birthdate_locked"))
            if is_rebound:
                if user["tokens"] < 1:
                    push_text(user_id, "⚠️ 您的代幣餘額不足 1 顆，無法改綁生日喔！請輸入「購買代幣」進行補充 💎")
                    return
                use_tokens(user_id, 1, "改綁生日消耗")
            
            supabase.table("users").update({
                "birth_date": selected_date,
                "birthdate_locked": True
            }).eq("line_user_id", user_id).execute()
            
            zodiac = get_zodiac(selected_date)
            push_text(user_id, f"🎉 生日綁定成功！\n\n🎂 生日：{selected_date}\n⭐ 星座：{zodiac}\n\n老師已將您的專屬星盤記錄下來囉 ✨")
            return

        # 2. 處理取消
        elif data == "cancel_reading":
            push_text(user_id, "🔮 已取消本次操作。老師隨時在這裡等候您的召喚 ✨")
            return

        # 3. 處理靈性占卜確認
        elif data == "confirm_spiritual":
            if not use_tokens(user_id, 2, "靈性占卜消耗"):
                push_text(user_id, "⚠️ 您的代幣餘額不足 2 顆，無法開始靈性占卜喔！請輸入「購買代幣」進行補充 💎")
                return
            pending_state[user_id] = {
                "mode": "spiritual",
                "step": "birth",
                "data": {}
            }
            push_text(user_id, "🌌 靈性占卜已啟動！\n\n請輸入您的出生日期（西元國曆）：\n範例：1995-01-01")
            return

        # 4. 處理急救占卜確認
        elif data == "confirm_deep":
            if user["tokens"] < 2:
                push_text(user_id, "⚠️ 您的代幣餘額不足 2 顆，無法開始急救占卜喔！請輸入「購買代幣」進行補充 💎")
                return
            push_flex(user_id, build_type_select_flex("deep"))
            return

        # 5. 處理急救占卜類型選擇
        elif data in ["deep_tarot", "deep_bazi", "deep_iching"]:
            reading_type = data.split("_")[1]
            if not use_tokens(user_id, 2, f"急救占卜-{reading_type}消耗"):
                push_text(user_id, "⚠️ 您的代幣餘額不足 2 顆，無法開始急救占卜喔！")
                return
            
            if reading_type == "bazi" and not user.get("birth_date"):
                push_text(user_id, "⚠️ 由於您尚未綁定生日，請先輸入您的出生日期（西元國曆，例如：1995-01-01）：")
                pending_state[user_id] = {
                    "mode": "career",
                    "step": "birth",
                    "service_id": None,
                    "follow_up_num": 1,
                    "data": {}
                }
                return

            pending_state[user_id] = {
                "mode": f"deep_reading_{reading_type}",
                "step": "question"
            }
            push_text(user_id, "🆘 急救占卜啟動！\n\n請直接輸入您目前最卡關、最想問的問題：")
            return

        # 6. 處理每日運勢類型選擇
        elif data in ["daily_tarot", "daily_bazi", "daily_iching"]:
            reading_type = data.split("_")[1]
            has_quota, quota_msg = check_free_reading_quota(user_id, user)
            if not has_quota:
                push_text(user_id, quota_msg)
                return

            if reading_type == "bazi" and not user.get("birth_date"):
                push_flex(user_id, build_date_picker_flex(is_rebound=False))
                return

            push_text(user_id, random.choice(
                WAITING_MSGS_TAROT if reading_type == "tarot" else
                (WAITING_MSGS_BAZI if reading_type == "bazi" else WAITING_MSGS_ICHING)
            ))
            birth = user.get("birth_date")
            zodiac = get_zodiac(birth) if birth else None
            do_reading_async(user_id, "今日整體運勢與指引", reading_type, False, zodiac, user)
            return

        # 7. 處理一週運勢類型選擇
        elif data in ["weekly_tarot", "weekly_bazi", "weekly_iching"]:
            reading_type = data.split("_")[1]
            used = user.get("free_readings_used") or 0
            free_remaining = max(0, FREE_READING_LIMIT - used)
            push_flex(user_id, build_confirm_weekly_flex(reading_type, user["tokens"], free_remaining))
            return

        # 8. 確認一週運勢解讀
        elif data.startswith("confirm_weekly_"):
            reading_type = data.split("_")[2]
            used = user.get("free_readings_used") or 0
            free_remaining = max(0, FREE_READING_LIMIT - used)

            if free_remaining <= 0 and user["tokens"] < 1:
                push_text(user_id, "⚠️ 您的免費額度與代幣皆不足，無法開始解讀一週運勢喔！請輸入「購買代幣」進行補充 💎")
                return

            if reading_type == "bazi" and not user.get("birth_date"):
                push_flex(user_id, build_date_picker_flex(is_rebound=False))
                return

            if free_remaining <= 0:
                use_tokens(user_id, 1, f"一週運勢-{reading_type}消耗")

            push_text(user_id, random.choice(WAITING_MSGS_WEEKLY))
            birth = user.get("birth_date")
            zodiac = get_zodiac(birth) if birth else None

            t = threading.Thread(
                target=_run_weekly_fortune_background,
                args=(user_id, reading_type, zodiac, user),
                daemon=True
            )
            t.start()
            return

        # 9. 求籤問卜：選擇類別
        elif data.startswith("fortune_cat_"):
            category = data.split("_")[2]
            push_flex(user_id, build_fortune_stick_question_flex(category))
            return

        # 10. 求籤問卜：選擇問題
        elif data.startswith("fortune_q_"):
            parts = data.split("_")
            category = parts[2]
            q_idx = int(parts[3])
            question = FORTUNE_STICK_CATEGORIES[category][q_idx]
            push_flex(user_id, build_fortune_stick_shake_flex(category, question))
            return

        # 11. 求籤問卜：搖動籤筒
        elif data.startswith("fortune_shake_"):
            parts = data.split("_")
            category = parts[2]
            question = parts[3]

            if not use_tokens(user_id, 1, "求籤問卜消耗"):
                push_text(user_id, "⚠️ 您的代幣餘額不足 1 顆，無法開始求籤喔！請輸入「購買代幣」進行補充 💎")
                return

            stick = random.choice(FORTUNE_STICKS)
            push_text(user_id, "🎋 正在為您搖動籤筒，請誠心等候神明指引約 15 秒...")
            
            t = threading.Thread(
                target=_run_fortune_stick_background,
                args=(user_id, category, question, stick),
                daemon=True
            )
            t.start()
            return

        # 12. 紫微斗數：選擇時辰
        elif data.startswith("shichen_"):
            shichen = data.split("_")[1]
            if user_id in pending_state and pending_state[user_id]["mode"] == "ziwei":
                state = pending_state[user_id]
                state["data"]["shichen"] = shichen
                push_text(user_id, random.choice(WAITING_MSGS_TIANBOOK))
                
                t = threading.Thread(
                    target=_run_ziwei_background,
                    args=(user_id, state["data"], state["service_id"]),
                    daemon=True
                )
                t.start()
                pending_state.pop(user_id, None)
            return

    except Exception as e:
        print(f"[handle_postback 錯誤] {e}")


# ══════════════════════════════════════════
#  排程器啟動與伺服器入口
# ══════════════════════════════════════════

scheduler = BackgroundScheduler()
# 每天早上 08:00 自動執行每日推播與生日推播 (台北時間)
scheduler.add_job(do_daily_push, 'cron', hour=8, minute=0, timezone='Asia/Taipei')
scheduler.start()

if __name__ == "__main__":
    # 本地測試使用，Render 部署時會由 Gunicorn 自動啟動 app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
