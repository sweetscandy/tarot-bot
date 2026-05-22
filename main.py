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
from ecpay import create_payment as ecpay_create, verify_notify, is_payment_success
import os, random, datetime, pytz, threading, uuid, time
import requests

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

# ══ 背景延遲秒數設定 ══
SLEEP_SECONDS = {
    "tarot":        (8, 12),
    "bazi":         (10, 15),
    "iching":       (8, 12),
    "deep":         (20, 30),
    "spiritual":    (20, 30),
    "weekly":       (10, 15),
    "tianbook":     (25, 35),
    "love":         (8, 12),
    "career":       (20, 28),
    "wealth":       (20, 28),
    "fortune_stick":(12, 15),
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
            time.sleep(random.uniform(*SLEEP_SECONDS["deep"]))
        else:
            time.sleep(random.uniform(*SLEEP_SECONDS.get(reading_type, (8, 12))))

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
        time.sleep(random.uniform(*SLEEP_SECONDS["weekly"]))

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
        time.sleep(random.uniform(*SLEEP_SECONDS["spiritual"]))

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
        time.sleep(random.uniform(*SLEEP_SECONDS["fortune_stick"]))

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
#  人生迷航決策指南 AI 核心
# ══════════════════════════════════════════

def _run_love_reading_background(line_user_id, situation, question_num, service_id):
    try:
        time.sleep(random.uniform(*SLEEP_SECONDS["love"]))

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


def _run_career_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(*SLEEP_SECONDS["career"]))

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


def _run_wealth_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(*SLEEP_SECONDS["wealth"]))

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
#  單次服務 AI 解析（背景執行）
# ══════════════════════════════════════════

def _run_double_chart_background(line_user_id, data, service_id):
    try:
        time.sleep(random.uniform(*SLEEP_SECONDS["tianbook"]))

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
        time.sleep(random.uniform(*SLEEP_SECONDS["tianbook"]))

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
        time.sleep(random.uniform(*SLEEP_SECONDS["tianbook"]))

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
        time.sleep(random.uniform(*SLEEP_SECONDS["tianbook"]))

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
#  Flex Message 工廠
# ══════════════════════════════════════════

def build_token_flex(user):
    tokens = user.get("tokens", 0)
    plan = user.get("plan", "free")
    sub_type = user.get("subscription_type", "free")
    plan_label = "✨ VIP 會員" if plan == "vip" else ("🌙 月費訂閱" if sub_type == "monthly" else "免費方案")
    ref_code = user.get("referral_code", "------")

    return FlexMessage(
        alt_text="我的代幣",
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "💎 我的星運帳戶", "weight": "bold", "size": "xl", "color": "#ffffff"},
                    {"type": "text", "text": plan_label, "size": "sm", "color": "#ffffffaa"}
                ],
                "backgroundColor": "#6B4FA0",
                "paddingAll": "20px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "代幣餘額", "size": "sm", "color": "#888888", "flex": 1},
                            {"type": "text", "text": f"💎 {tokens} 顆", "size": "xl", "weight": "bold", "color": "#6B4FA0", "flex": 2, "align": "end"}
                        ]
                    },
                    {"type": "separator"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "推薦碼", "size": "sm", "color": "#888888", "flex": 1},
                            {"type": "text", "text": ref_code, "size": "md", "weight": "bold", "color": "#333333", "flex": 2, "align": "end"}
                        ]
                    },
                    {"type": "separator"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "💡 代幣用途", "size": "sm", "weight": "bold", "color": "#6B4FA0"},
                            {"type": "text", "text": "• 一般占卜：1 顆", "size": "xs", "color": "#555555", "margin": "sm"},
                            {"type": "text", "text": "• 靈性/急救占卜：2 顆", "size": "xs", "color": "#555555"},
                            {"type": "text", "text": "• 一週運勢：1 顆", "size": "xs", "color": "#555555"},
                            {"type": "text", "text": "• 求籤問卜：1 顆", "size": "xs", "color": "#555555"},
                        ]
                    }
                ],
                "paddingAll": "20px"
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "💳 購買代幣", "text": "購買代幣"},
                        "style": "primary",
                        "color": "#6B4FA0"
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "👥 推薦好友", "text": "推薦好友"},
                        "style": "secondary"
                    }
                ],
                "paddingAll": "15px"
            }
        })
    )


def build_token_shop_flex():
    return FlexMessage(
        alt_text="購買代幣",
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "✨ 星運代幣商店", "weight": "bold", "size": "xl", "color": "#ffffff"},
                    {"type": "text", "text": "選擇適合您的方案", "size": "sm", "color": "#ffffffaa"}
                ],
                "backgroundColor": "#6B4FA0",
                "paddingAll": "20px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "✨ 星塵入門包", "weight": "bold", "size": "md", "color": "#6B4FA0"},
                            {"type": "text", "text": "10 顆代幣｜NT$ 99", "size": "sm", "color": "#555555"},
                            {
                                "type": "button",
                                "action": {"type": "message", "label": "立即購買", "text": "購買星塵入門包"},
                                "style": "primary",
                                "color": "#6B4FA0",
                                "margin": "sm",
                                "height": "sm"
                            }
                        ],
                        "backgroundColor": "#f5f0ff",
                        "paddingAll": "15px",
                        "cornerRadius": "10px"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "🌙 月光超值包", "weight": "bold", "size": "md", "color": "#6B4FA0"},
                            {"type": "text", "text": "30 顆代幣｜NT$ 249", "size": "sm", "color": "#555555"},
                            {"type": "text", "text": "🔥 最受歡迎", "size": "xs", "color": "#e74c3c", "weight": "bold"},
                            {
                                "type": "button",
                                "action": {"type": "message", "label": "立即購買", "text": "購買月光超值包"},
                                "style": "primary",
                                "color": "#6B4FA0",
                                "margin": "sm",
                                "height": "sm"
                            }
                        ],
                        "backgroundColor": "#f5f0ff",
                        "paddingAll": "15px",
                        "cornerRadius": "10px"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "🌌 星河豪華包", "weight": "bold", "size": "md", "color": "#6B4FA0"},
                            {"type": "text", "text": "80 顆代幣｜NT$ 599", "size": "sm", "color": "#555555"},
                            {"type": "text", "text": "💎 超值優惠", "size": "xs", "color": "#8e44ad", "weight": "bold"},
                            {
                                "type": "button",
                                "action": {"type": "message", "label": "立即購買", "text": "購買星河豪華包"},
                                "style": "primary",
                                "color": "#6B4FA0",
                                "margin": "sm",
                                "height": "sm"
                            }
                        ],
                        "backgroundColor": "#f5f0ff",
                        "paddingAll": "15px",
                        "cornerRadius": "10px"
                    }
                ],
                "paddingAll": "20px"
            }
        })
    )


def build_tianbook_flex():
    return FlexMessage(
        alt_text="天書服務",
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "📖 天書深度服務", "weight": "bold", "size": "xl", "color": "#ffffff"},
                    {"type": "text", "text": "專業命理深度解析", "size": "sm", "color": "#ffffffaa"}
                ],
                "backgroundColor": "#2C3E7A",
                "paddingAll": "20px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "💑 雙人合盤", "weight": "bold", "size": "sm"},
                                    {"type": "text", "text": "NT$ 299", "size": "xs", "color": "#888888"},
                                    {
                                        "type": "button",
                                        "action": {"type": "message", "label": "選擇", "text": "購買雙人合盤"},
                                        "style": "primary", "color": "#2C3E7A",
                                        "height": "sm", "margin": "sm"
                                    }
                                ],
                                "backgroundColor": "#eef0ff",
                                "paddingAll": "12px",
                                "cornerRadius": "8px",
                                "flex": 1
                            },
                            {"type": "separator", "margin": "sm"},
                            {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "📅 流年運勢", "weight": "bold", "size": "sm"},
                                    {"type": "text", "text": "NT$ 299", "size": "xs", "color": "#888888"},
                                    {
                                        "type": "button",
                                        "action": {"type": "message", "label": "選擇", "text": "購買流年運勢"},
                                        "style": "primary", "color": "#2C3E7A",
                                        "height": "sm", "margin": "sm"
                                    }
                                ],
                                "backgroundColor": "#eef0ff",
                                "paddingAll": "12px",
                                "cornerRadius": "8px",
                                "flex": 1
                            }
                        ],
                        "spacing": "sm"
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "⭐ 紫微斗數", "weight": "bold", "size": "sm"},
                                    {"type": "text", "text": "NT$ 399", "size": "xs", "color": "#888888"},
                                    {
                                        "type": "button",
                                        "action": {"type": "message", "label": "選擇", "text": "購買紫微斗數"},
                                        "style": "primary", "color": "#2C3E7A",
                                        "height": "sm", "margin": "sm"
                                    }
                                ],
                                "backgroundColor": "#eef0ff",
                                "paddingAll": "12px",
                                "cornerRadius": "8px",
                                "flex": 1
                            },
                            {"type": "separator", "margin": "sm"},
                            {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "💔 復合分析", "weight": "bold", "size": "sm"},
                                    {"type": "text", "text": "NT$ 499", "size": "xs", "color": "#888888"},
                                    {
                                        "type": "button",
                                        "action": {"type": "message", "label": "選擇", "text": "購買復合分析"},
                                        "style": "primary", "color": "#2C3E7A",
                                        "height": "sm", "margin": "sm"
                                    }
                                ],
                                "backgroundColor": "#eef0ff",
                                "paddingAll": "12px",
                                "cornerRadius": "8px",
                                "flex": 1
                            }
                        ],
                        "spacing": "sm"
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "💼 職場運勢", "weight": "bold", "size": "sm"},
                                    {"type": "text", "text": "NT$ 299", "size": "xs", "color": "#888888"},
                                    {
                                        "type": "button",
                                        "action": {"type": "message", "label": "選擇", "text": "購買職場運勢"},
                                        "style": "primary", "color": "#2C3E7A",
                                        "height": "sm", "margin": "sm"
                                    }
                                ],
                                "backgroundColor": "#eef0ff",
                                "paddingAll": "12px",
                                "cornerRadius": "8px",
                                "flex": 1
                            },
                            {"type": "separator", "margin": "sm"},
                            {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "💰 財運分析", "weight": "bold", "size": "sm"},
                                    {"type": "text", "text": "NT$ 299", "size": "xs", "color": "#888888"},
                                    {
                                        "type": "button",
                                        "action": {"type": "message", "label": "選擇", "text": "購買財運分析"},
                                        "style": "primary", "color": "#2C3E7A",
                                        "height": "sm", "margin": "sm"
                                    }
                                ],
                                "backgroundColor": "#eef0ff",
                                "paddingAll": "12px",
                                "cornerRadius": "8px",
                                "flex": 1
                            }
                        ],
                        "spacing": "sm"
                    }
                ],
                "paddingAll": "15px"
            }
        })
    )


def build_settings_flex(user):
    birth = user.get("birth_date", None)
    birth_display = birth if birth else "尚未設定"
    locked = user.get("birthdate_locked", False)
    daily_push = user.get("daily_push", True)
    push_label = "🔔 每日推播：開啟" if daily_push else "🔕 每日推播：關閉"
    push_action_text = "關閉每日推播" if daily_push else "開啟每日推播"

    return FlexMessage(
        alt_text="設定",
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "⚙️ 個人設定", "weight": "bold", "size": "xl", "color": "#ffffff"}
                ],
                "backgroundColor": "#4A4A8A",
                "paddingAll": "20px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "🎂 生日", "size": "sm", "color": "#888888", "flex": 1},
                            {"type": "text", "text": birth_display, "size": "sm", "weight": "bold", "color": "#333333", "flex": 2, "align": "end"}
                        ]
                    },
                    {"type": "separator"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "🔒 生日鎖定", "size": "sm", "color": "#888888", "flex": 1},
                            {"type": "text", "text": "已鎖定" if locked else "未鎖定", "size": "sm", "weight": "bold", "color": "#e74c3c" if locked else "#27ae60", "flex": 2, "align": "end"}
                        ]
                    },
                    {"type": "separator"},
                    {
                        "type": "button",
                        "action": {"type": "message", "label": push_label, "text": push_action_text},
                        "style": "secondary"
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "✏️ 修改生日", "text": "修改生日"},
                        "style": "secondary"
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "📋 查看紀錄", "text": "查看紀錄"},
                        "style": "secondary"
                    }
                ],
                "paddingAll": "20px"
            }
        })
    )


def build_date_picker_flex(prompt_text, action_text_prefix):
    return FlexMessage(
        alt_text=prompt_text,
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": prompt_text, "wrap": True, "weight": "bold", "size": "md"},
                    {"type": "text", "text": "請選擇日期或直接輸入", "size": "sm", "color": "#888888"},
                    {
                        "type": "button",
                        "action": {
                            "type": "datetimepicker",
                            "label": "📅 選擇日期",
                            "data": f"action={action_text_prefix}",
                            "mode": "date",
                            "initial": "1990-01-01",
                            "min": "1920-01-01",
                            "max": "2010-12-31"
                        },
                        "style": "primary",
                        "color": "#6B4FA0"
                    }
                ],
                "paddingAll": "20px"
            }
        })
    )


def build_history_flex(logs):
    if not logs:
        return None
    items = []
    for log in logs[:5]:
        cat = log.get("category", "占卜")
        card = log.get("card_name", "")
        reading_preview = (log.get("reading", "")[:40] + "...") if log.get("reading") else ""
        created = log.get("created_at", "")[:10] if log.get("created_at") else ""
        items.append({
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"🔮 {cat}", "weight": "bold", "size": "sm", "color": "#6B4FA0"},
                {"type": "text", "text": card, "size": "xs", "color": "#888888"},
                {"type": "text", "text": reading_preview, "size": "xs", "color": "#555555", "wrap": True},
                {"type": "text", "text": created, "size": "xs", "color": "#aaaaaa", "align": "end"}
            ],
            "paddingAll": "10px",
            "backgroundColor": "#f9f5ff",
            "cornerRadius": "8px",
            "margin": "sm"
        })

    return FlexMessage(
        alt_text="占卜紀錄",
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "📋 最近占卜紀錄", "weight": "bold", "size": "xl", "color": "#ffffff"}
                ],
                "backgroundColor": "#6B4FA0",
                "paddingAll": "20px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": items,
                "paddingAll": "15px"
            }
        })
    )


def build_daily_flex(zodiac, reading_text, is_birthday=False):
    title = f"🎂 生日快樂！{zodiac}的星運祝福" if is_birthday else f"🌟 {zodiac} 今日星運"
    return FlexMessage(
        alt_text=title,
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": title, "weight": "bold", "size": "lg", "color": "#ffffff", "wrap": True}
                ],
                "backgroundColor": "#6B4FA0" if not is_birthday else "#c0392b",
                "paddingAll": "20px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": reading_text, "wrap": True, "size": "sm", "color": "#333333"}
                ],
                "paddingAll": "20px"
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "🔮 今日占卜", "text": "塔羅占卜"},
                        "style": "primary",
                        "color": "#6B4FA0"
                    }
                ],
                "paddingAll": "15px"
            }
        })
    )


def build_confirm_card(title, body_text, confirm_text, cancel_text="取消"):
    return FlexMessage(
        alt_text=title,
        contents=FlexContainer.from_dict({
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": title, "weight": "bold", "size": "lg", "wrap": True, "color": "#6B4FA0"},
                    {"type": "text", "text": body_text, "size": "sm", "wrap": True, "color": "#555555"}
                ],
                "paddingAll": "20px"
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "action": {"type": "message", "label": cancel_text, "text": cancel_text},
                        "style": "secondary",
                        "flex": 1
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": confirm_text, "text": confirm_text},
                        "style": "primary",
                        "color": "#6B4FA0",
                        "flex": 1
                    }
                ],
                "paddingAll": "15px"
            }
        })
    )
# ══════════════════════════════════════════
#  每日推播
# ══════════════════════════════════════════

def do_daily_push():
    try:
        tz = pytz.timezone("Asia/Taipei")
        today = datetime.datetime.now(tz)
        today_str = today.strftime("%m-%d")

        users = supabase.table("users").select("*").eq("daily_push", True).execute()
        if not users.data:
            return

        for user in users.data:
            line_user_id = user.get("line_user_id")
            birth = user.get("birth_date")
            zodiac = get_zodiac(birth) if birth else None
            if not zodiac:
                continue

            is_birthday = False
            if birth:
                birth_mmdd = birth[5:]
                if birth_mmdd == today_str:
                    is_birthday = True

            try:
                if is_birthday:
                    user_prompt = f"""今天是使用者的生日！星座：{zodiac}
請給出約150字的生日星運祝福，包含：
- 溫暖的生日祝福
- 今年整體運勢提示
- 一句特別的生日鼓勵
語氣溫柔有詩意，充滿祝福能量。"""
                else:
                    user_prompt = f"""使用者星座：{zodiac}
請給出約100字的今日星運提示，包含：
- 今日整體能量
- 一個具體的開運小建議
- 一句溫柔的鼓勵
語氣溫柔有詩意，像老師給學生的早安叮嚀。"""

                chat_completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    model="llama-3.3-70b-versatile",
                )
                reading_text = chat_completion.choices[0].message.content
                flex_msg = build_daily_flex(zodiac, reading_text, is_birthday)
                push_flex(line_user_id, flex_msg)

            except Exception as e:
                print(f"[每日推播單用戶錯誤] {line_user_id}: {e}")

    except Exception as e:
        print(f"[每日推播錯誤] {e}")


# ══════════════════════════════════════════
#  每日推播排程執行緒
# ══════════════════════════════════════════

def _daily_push_scheduler():
    tz = pytz.timezone("Asia/Taipei")
    while True:
        try:
            now = datetime.datetime.now(tz)
            target = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now >= target:
                target += datetime.timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            print(f"[排程] 下次推播於 {target.strftime('%Y-%m-%d %H:%M')}，等待 {int(wait_seconds)} 秒")
            time.sleep(wait_seconds)
            do_daily_push()
        except Exception as e:
            print(f"[排程錯誤] {e}")
            time.sleep(60)

_scheduler_thread = threading.Thread(target=_daily_push_scheduler, daemon=True)
_scheduler_thread.start()


# ══════════════════════════════════════════
#  Webhook 路由
# ══════════════════════════════════════════

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


# ══════════════════════════════════════════
#  金流路由
# ══════════════════════════════════════════

@app.route("/pay/go/<order_id>")
def pay_go(order_id):
    from flask import redirect
    result = supabase.table("orders").select("*").eq("order_id", order_id).execute()
    if not result.data:
        result2 = supabase.table("payments").select("*").eq("order_id", order_id).execute()
        if not result2.data:
            return "找不到訂單", 404
        payment = result2.data[0]
        amount = payment.get("amount", 0)
        product_type = payment.get("package_type", "代幣方案")
    else:
        order = result.data[0]
        amount = order.get("amount", 0)
        product_type = order.get("product_type", "占卜服務")

    pay_url = ecpay_create(
        order_id=order_id,
        amount=amount,
        item_name=product_type,
        return_url=f"{RENDER_URL}/pay/notify",
        client_back_url=f"{RENDER_URL}/pay/confirm/{order_id}"
    )
    return redirect(pay_url)


@app.route("/pay/notify", methods=["POST"])
def pay_notify():
    data = request.form.to_dict()
    if not verify_notify(data):
        return "0|ErrorMessage"
    if is_payment_success(data):
        order_id = data.get("MerchantTradeNo")
        _activate_payment(order_id)
    return "1|OK"


@app.route("/pay/confirm/<order_id>")
def pay_confirm(order_id):
    _activate_payment(order_id)
    return """
    <html><body style="text-align:center;font-family:sans-serif;padding:40px;">
    <h2>✅ 付款成功！</h2>
    <p>感謝您的購買，請返回 LINE 查看您的代幣或服務 🔮</p>
    <p style="color:#888;font-size:14px;">您可以關閉此頁面</p>
    </body></html>
    """


@app.route("/")
def index():
    return "星運導航 Bot 運行中 🔮"
# ══════════════════════════════════════════
#  LINE Webhook 主處理
# ══════════════════════════════════════════

@handler.add(FollowEvent)
def handle_follow(event):
    line_user_id = event.source.user_id
    ref_code = None
    try:
        params = event.source.__dict__
        ref_code = params.get("ref_code")
    except Exception:
        pass

    user = get_or_create_user(line_user_id)
    if ref_code:
        process_referral(line_user_id, ref_code)

    welcome_text = (
        "🌟 歡迎來到【口袋裡的心靈星運導航】！\n\n"
        "我是您的專屬命理老師，擅長：\n"
        "🃏 塔羅占卜\n"
        "🀄 八字命理\n"
        "☯️ 易經卦象\n"
        "🌌 靈性解讀\n"
        "⭐ 紫微斗數\n\n"
        "💎 新朋友贈送 1 顆代幣，立即開始占卜吧！\n\n"
        "輸入「塔羅占卜」、「八字運勢」或「易經問卜」開始 🔮"
    )
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_text)]
            )
        )


@handler.add(PostbackEvent)
def handle_postback(event):
    line_user_id = event.source.user_id
    data = event.postback.data
    params = dict(p.split("=") for p in data.split("&") if "=" in p)
    action = params.get("action", "")

    if action in ["set_birth", "set_birth1", "set_birth2", "set_birth_ziwei"]:
        date_str = event.postback.params.get("date", "")
        if not date_str:
            return
        user = get_or_create_user(line_user_id)

        if action == "set_birth":
            locked = user.get("birthdate_locked", False)
            if locked:
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="🔒 您的生日已鎖定，無法再次修改喔 🌙")]
                        )
                    )
                return
            supabase.table("users").update({
                "birth_date": date_str,
                "birthdate_locked": True
            }).eq("line_user_id", line_user_id).execute()
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"✅ 生日已設定為 {date_str}，並已鎖定 🔒\n\n星座：{get_zodiac(date_str) or '未知'} ✨")]
                    )
                )

        elif action == "set_birth1":
            state = pending_state.get(line_user_id, {})
            if state.get("mode") == "double_chart" and state.get("step") == "birth1":
                state["data"]["birth1"] = date_str
                state["step"] = "birth2"
                pending_state[line_user_id] = state
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(
                                text=f"✅ 甲方生日：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n"
                                     f"請輸入乙方（對方）的出生日期\n\n"
                                     f"格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日"
                            )]
                        )
                    )

        elif action == "set_birth2":
            state = pending_state.get(line_user_id, {})
            if state.get("mode") == "double_chart" and state.get("step") == "birth2":
                state["data"]["birth2"] = date_str
                state["step"] = "confirm"
                pending_state[line_user_id] = state
                birth1 = state["data"].get("birth1", "未知")
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[build_confirm_card(
                                "💑 確認雙人合盤資料",
                                f"甲方：{birth1}（{get_zodiac(birth1) or '未知'}）\n乙方：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n確認開始解析？",
                                "confirm_double_chart",
                                "取消"
                            )]
                        )
                    )

        elif action == "set_birth_ziwei":
            state = pending_state.get(line_user_id, {})
            if state.get("mode") == "ziwei" and state.get("step") == "birth":
                state["data"]["birth"] = date_str
                state["step"] = "shichen"
                pending_state[line_user_id] = state
                shichen_buttons = "\n".join([f"{i+1}. {s}" for i, s in enumerate(SHICHEN_LIST)])
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(
                                text=f"✅ 生日：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n"
                                     f"請選擇出生時辰（輸入數字）：\n\n{shichen_buttons}"
                            )]
                        )
                    )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    line_user_id = event.source.user_id
    user_msg = event.message.text.strip()
    reply_token = event.reply_token

    def reply(messages):
        if not isinstance(messages, list):
            messages = [messages]
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=messages)
            )

    # ── 管理員指令 ──
    if line_user_id == ADMIN_USER_ID:
        if user_msg.startswith("補代幣 "):
            parts = user_msg.split()
            if len(parts) == 3:
                target_id, amount_str = parts[1], parts[2]
                try:
                    amount = int(amount_str)
                    new_total = add_tokens(target_id, amount, reason="管理員補充")
                    reply(TextMessage(text=f"✅ 已為 {target_id} 補充 {amount} 顆代幣\n目前餘額：{new_total} 顆"))
                except ValueError:
                    reply(TextMessage(text="❌ 格式錯誤，請用：補代幣 [USER_ID] [數量]"))
            return

        if user_msg.startswith("查用戶 "):
            parts = user_msg.split()
            if len(parts) == 2:
                target_id = parts[1]
                result = supabase.table("users").select("*").eq("line_user_id", target_id).execute()
                if result.data:
                    u = result.data[0]
                    reply(TextMessage(text=(
                        f"👤 用戶資料\n"
                        f"ID：{u.get('line_user_id')}\n"
                        f"代幣：{u.get('tokens', 0)}\n"
                        f"方案：{u.get('plan', 'free')}\n"
                        f"生日：{u.get('birth_date', '未設定')}\n"
                        f"推播：{'開啟' if u.get('daily_push') else '關閉'}\n"
                        f"推薦碼：{u.get('referral_code', '無')}\n"
                        f"推薦人數：{u.get('referral_count', 0)}"
                    )))
                else:
                    reply(TextMessage(text="❌ 找不到此用戶"))
            return

    user = get_or_create_user(line_user_id)
    tokens = user.get("tokens", 0)
    birth = user.get("birth_date")
    zodiac = get_zodiac(birth) if birth else None
    state = pending_state.get(line_user_id, {})

    # ══════════════════════════════════════
    #  pending_state 狀態機處理
    # ══════════════════════════════════════

    if state:
        mode = state.get("mode")

        # ── 取消指令 ──
        if user_msg in ["取消", "離開", "結束"]:
            pending_state.pop(line_user_id, None)
            reply(TextMessage(text="✅ 已取消目前流程，有需要隨時告訴老師 🌙"))
            return

        # ────────────────────────────────
        #  靈性占卜流程
        # ────────────────────────────────
        if mode == "spiritual":
            step = state.get("step")

            if step == "birth":
                date_str = parse_birth_input(user_msg)
                if not date_str:
                    reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20 或 1990年5月20日"))
                    return
                state["data"]["birth"] = date_str
                state["step"] = "q1"
                pending_state[line_user_id] = state
                reply(TextMessage(text="✅ 收到！\n\n🌌 第一題：\n最近最困擾您的事情是什麼？\n\n請用一兩句話描述 🌙"))
                return

            elif step == "q1":
                state["data"]["q1"] = user_msg
                state["step"] = "q2"
                pending_state[line_user_id] = state
                reply(TextMessage(text="💫 第二題：\n您希望在哪個方面得到指引？\n\n（感情、事業、財運、家庭、人生方向...）"))
                return

            elif step == "q2":
                state["data"]["q2"] = user_msg
                state["step"] = "q3"
                pending_state[line_user_id] = state
                reply(TextMessage(text="🌙 第三題：\n您目前的心情狀態如何？\n\n（平靜、焦慮、迷茫、期待...）"))
                return

            elif step == "q3":
                state["data"]["q3"] = user_msg
                state["step"] = "q4"
                pending_state[line_user_id] = state
                reply(TextMessage(text="✨ 最後一題：\n您對未來最大的期望是什麼？"))
                return

            elif step == "q4":
                state["data"]["q4"] = user_msg
                pending_state.pop(line_user_id, None)

                if not use_tokens(line_user_id, 2, "靈性占卜"):
                    reply(TextMessage(text="💎 代幣不足，靈性占卜需要 2 顆代幣\n\n輸入「購買代幣」補充 🌙"))
                    return

                waiting_msg = random.choice(WAITING_MSGS_SPIRITUAL)
                reply(TextMessage(text=waiting_msg))

                t = threading.Thread(
                    target=_run_spiritual_background,
                    args=(line_user_id, state["data"], zodiac),
                    daemon=True
                )
                t.start()
                return

        # ────────────────────────────────
        #  急救占卜流程
        # ────────────────────────────────
        elif mode == "deep":
            step = state.get("step")

            if step == "choose_type":
                if user_msg in ["塔羅牌", "八字命理", "易經卦象"]:
                    type_map = {"塔羅牌": "tarot", "八字命理": "bazi", "易經卦象": "iching"}
                    state["reading_type"] = type_map[user_msg]
                    state["step"] = "question"
                    pending_state[line_user_id] = state
                    reply(TextMessage(text=f"✅ 選擇【{user_msg}】\n\n🆘 請描述您目前最困擾、最急迫的問題：\n\n老師將為您進行深度解讀 🔮"))
                    return
                else:
                    reply(TextMessage(text="請輸入：塔羅牌、八字命理 或 易經卦象"))
                    return

            elif step == "question":
                state["question"] = user_msg
                state["step"] = "deep_pending_confirm"
                pending_state[line_user_id] = state
                reading_type = state.get("reading_type", "tarot")
                type_labels = {"tarot": "塔羅牌", "bazi": "八字命理", "iching": "易經卦象"}
                type_label = type_labels.get(reading_type, "占卜")
                reply(build_confirm_card(
                    "🆘 確認急救占卜",
                    f"占卜方式：{type_label}\n問題：{user_msg}\n\n費用：2 顆代幣\n目前代幣：{tokens} 顆",
                    "confirm_deep",
                    "取消"
                ))
                return

            elif step == "deep_pending_confirm":
                if user_msg == "confirm_deep":
                    reading_type = state.get("reading_type", "tarot")
                    question = state.get("question", "")
                    pending_state.pop(line_user_id, None)

                    if not use_tokens(line_user_id, 2, "急救占卜"):
                        reply(TextMessage(text="💎 代幣不足，急救占卜需要 2 顆代幣\n\n輸入「購買代幣」補充 🌙"))
                        return

                    waiting_msg = random.choice(WAITING_MSGS_DEEP)
                    reply(TextMessage(text=waiting_msg))

                    t = threading.Thread(
                        target=_run_reading_background,
                        args=(line_user_id, question, reading_type, True, zodiac, user),
                        daemon=True
                    )
                    t.start()
                    return
                else:
                    reply(TextMessage(text="請點選「confirm_deep」確認，或輸入「取消」放棄"))
                    return

        # ────────────────────────────────
        #  求籤問卜流程
        # ────────────────────────────────
        elif mode == "fortune_stick":
            step = state.get("step")

            if step == "choose_category":
                categories = list(FORTUNE_STICK_CATEGORIES.keys())
                if user_msg in categories:
                    state["category"] = user_msg
                    state["step"] = "choose_question"
                    pending_state[line_user_id] = state
                    questions = FORTUNE_STICK_CATEGORIES[user_msg]
                    q_list = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions)])
                    reply(TextMessage(text=f"🎋 【{user_msg}】問題選擇：\n\n{q_list}\n\n請輸入數字 1-5 選擇問題，或直接輸入您的問題"))
                    return
                else:
                    cat_list = "\n".join([f"• {c}" for c in categories])
                    reply(TextMessage(text=f"請選擇以下類別：\n\n{cat_list}"))
                    return

            elif step == "choose_question":
                category = state.get("category", "")
                questions = FORTUNE_STICK_CATEGORIES.get(category, [])
                if user_msg.isdigit() and 1 <= int(user_msg) <= len(questions):
                    question = questions[int(user_msg) - 1]
                else:
                    question = user_msg

                state["question"] = question
                state["step"] = "fortune_shake_confirm"
                pending_state[line_user_id] = state

                reply(build_confirm_card(
                    "🎋 確認求籤",
                    f"類別：{category}\n問題：{question}\n\n費用：1 顆代幣\n目前代幣：{tokens} 顆",
                    "fortune_shake_confirm",
                    "取消"
                ))
                return

            elif step == "fortune_shake_confirm":
                if user_msg == "fortune_shake_confirm":
                    category = state.get("category", "")
                    question = state.get("question", "")
                    pending_state.pop(line_user_id, None)

                    if not use_tokens(line_user_id, 1, "求籤問卜"):
                        reply(TextMessage(text="💎 代幣不足，求籤問卜需要 1 顆代幣\n\n輸入「購買代幣」補充 🌙"))
                        return

                    stick = random.choice(FORTUNE_STICK_POEMS)
                    reply(TextMessage(text=f"🎋 搖籤中...\n\n您抽到了第 {stick['num']} 籤 — {stick['grade']}！\n\n老師正在為您解籤，請稍候約 1 分鐘 🙏"))

                    t = threading.Thread(
                        target=_run_fortune_stick_background,
                        args=(line_user_id, category, question, stick),
                        daemon=True
                    )
                    t.start()
                    return
                else:
                    reply(TextMessage(text="請點選「fortune_shake_confirm」確認，或輸入「取消」放棄"))
                    return

        # ────────────────────────────────
        #  雙人合盤流程
        # ────────────────────────────────
        elif mode == "double_chart":
            step = state.get("step")
            service_id = state.get("service_id")

            if step == "birth1":
                date_str = parse_birth_input(user_msg)
                if not date_str:
                    reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20"))
                    return
                state["data"]["birth1"] = date_str
                state["step"] = "birth2"
                pending_state[line_user_id] = state
                reply(TextMessage(text=f"✅ 甲方生日：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n請輸入乙方（對方）的出生日期"))
                return

            elif step == "birth2":
                date_str = parse_birth_input(user_msg)
                if not date_str:
                    reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20"))
                    return
                state["data"]["birth2"] = date_str
                state["step"] = "confirm"
                pending_state[line_user_id] = state
                birth1 = state["data"].get("birth1", "未知")
                reply(build_confirm_card(
                    "💑 確認雙人合盤資料",
                    f"甲方：{birth1}（{get_zodiac(birth1) or '未知'}）\n乙方：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n確認開始解析？",
                    "confirm_double_chart",
                    "取消"
                ))
                return

            elif step == "confirm":
                if user_msg == "confirm_double_chart":
                    data = state.get("data", {})
                    pending_state.pop(line_user_id, None)
                    waiting_msg = random.choice(WAITING_MSGS_TIANBOOK)
                    reply(TextMessage(text=waiting_msg))
                    t = threading.Thread(
                        target=_run_double_chart_background,
                        args=(line_user_id, data, service_id),
                        daemon=True
                    )
                    t.start()
                    return
                else:
                    reply(TextMessage(text="請點選「confirm_double_chart」確認，或輸入「取消」放棄"))
                    return

            elif step == "follow_up":
                svc = get_active_service(line_user_id, "double_chart")
                if svc:
                    follow_up_num = (svc.get("follow_up_count") or 0) + 1
                    reply(TextMessage(text=f"💑 收到您的追問，老師正在深入解讀...\n\n請稍候 🔮"))
                    t = threading.Thread(
                        target=_run_follow_up_background,
                        args=(line_user_id, "double_chart", user_msg, svc["service_id"], follow_up_num),
                        daemon=True
                    )
                    t.start()
                    return

        # ────────────────────────────────
        #  流年運勢流程
        # ────────────────────────────────
        elif mode == "year_fortune":
            step = state.get("step")
            service_id = state.get("service_id")

            if step == "birth":
                date_str = parse_birth_input(user_msg)
                if not date_str:
                    reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20"))
                    return
                state["data"]["birth"] = date_str
                state["step"] = "confirm"
                pending_state[line_user_id] = state
                tz = pytz.timezone("Asia/Taipei")
                current_year = datetime.datetime.now(tz).year
                reply(build_confirm_card(
                    "📅 確認流年運勢",
                    f"生日：{date_str}（{get_zodiac(date_str) or '未知'}）\n解析年份：{current_year} 年\n\n確認開始解析？",
                    "confirm_year_fortune",
                    "取消"
                ))
                return

            elif step == "confirm":
                if user_msg == "confirm_year_fortune":
                    data = state.get("data", {})
                    pending_state.pop(line_user_id, None)
                    waiting_msg = random.choice(WAITING_MSGS_TIANBOOK)
                    reply(TextMessage(text=waiting_msg))
                    t = threading.Thread(
                        target=_run_year_fortune_background,
                        args=(line_user_id, data, service_id),
                        daemon=True
                    )
                    t.start()
                    return
                else:
                    reply(TextMessage(text="請點選「confirm_year_fortune」確認，或輸入「取消」放棄"))
                    return

            elif step == "follow_up":
                svc = get_active_service(line_user_id, "year_fortune")
                if svc:
                    follow_up_num = (svc.get("follow_up_count") or 0) + 1
                    reply(TextMessage(text=f"📅 收到您的追問，老師正在深入解讀...\n\n請稍候 🔮"))
                    t = threading.Thread(
                        target=_run_follow_up_background,
                        args=(line_user_id, "year_fortune", user_msg, svc["service_id"], follow_up_num),
                        daemon=True
                    )
                    t.start()
                    return

        # ────────────────────────────────
        #  紫微斗數流程
        # ────────────────────────────────
        elif mode == "ziwei":
            step = state.get("step")
            service_id = state.get("service_id")

            if step == "birth":
                date_str = parse_birth_input(user_msg)
                if not date_str:
                    reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20"))
                    return
                state["data"]["birth"] = date_str
                state["step"] = "shichen"
                pending_state[line_user_id] = state
                shichen_buttons = "\n".join([f"{i+1}. {s}" for i, s in enumerate(SHICHEN_LIST)])
                reply(TextMessage(text=f"✅ 生日：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n請選擇出生時辰（輸入數字）：\n\n{shichen_buttons}"))
                return

            elif step == "shichen":
                if user_msg.isdigit() and 1 <= int(user_msg) <= len(SHICHEN_LIST):
                    shichen = SHICHEN_LIST[int(user_msg) - 1]
                else:
                    shichen = "不知道時辰"
                state["data"]["shichen"] = shichen
                state["step"] = "confirm"
                pending_state[line_user_id] = state
                birth = state["data"].get("birth", "未知")
                reply(build_confirm_card(
                    "⭐ 確認紫微斗數資料",
                    f"生日：{birth}（{get_zodiac(birth) or '未知'}）\n時辰：{shichen}\n\n確認開始排盤？",
                    "confirm_ziwei",
                    "取消"
                ))
                return

            elif step == "confirm":
                if user_msg == "confirm_ziwei":
                    data = state.get("data", {})
                    pending_state.pop(line_user_id, None)
                    waiting_msg = random.choice(WAITING_MSGS_TIANBOOK)
                    reply(TextMessage(text=waiting_msg))
                    t = threading.Thread(
                        target=_run_ziwei_background,
                        args=(line_user_id, data, service_id),
                        daemon=True
                    )
                    t.start()
                    return
                else:
                    reply(TextMessage(text="請點選「confirm_ziwei」確認，或輸入「取消」放棄"))
                    return

            elif step == "follow_up":
                svc = get_active_service(line_user_id, "ziwei")
                if svc:
                    follow_up_num = (svc.get("follow_up_count") or 0) + 1
                    reply(TextMessage(text=f"⭐ 收到您的追問，老師正在深入解讀...\n\n請稍候 🔮"))
                    t = threading.Thread(
                        target=_run_follow_up_background,
                        args=(line_user_id, "ziwei", user_msg, svc["service_id"], follow_up_num),
                        daemon=True
                    )
                    t.start()
                    return

        # ────────────────────────────────
        #  復合分析流程
        # ────────────────────────────────
        elif mode == "love_reading":
            step = state.get("step")
            service_id = state.get("service_id")
            question_num = state.get("question_num", 1)

            if step == "question":
                limit = FOLLOW_UP_LIMITS.get("love_reading", 5)
                if question_num > limit:
                    pending_state.pop(line_user_id, None)
                    reply(TextMessage(text="🌟 本次復合分析已完成，感謝您的信任 💎"))
                    return

                state["question_num"] = question_num + 1
                pending_state[line_user_id] = state

                waiting_msg = random.choice(WAITING_MSGS_LOVE)
                reply(TextMessage(text=waiting_msg))

                t = threading.Thread(
                    target=_run_love_reading_background,
                    args=(line_user_id, user_msg, question_num, service_id),
                    daemon=True
                )
                t.start()
                return

        # ────────────────────────────────
        #  職場運勢流程
        # ────────────────────────────────
        elif mode == "career":
            step = state.get("step")
            service_id = state.get("service_id")

            if step == "birth":
                date_str = parse_birth_input(user_msg)
                if not date_str:
                    reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20"))
                    return
                state["data"]["birth"] = date_str
                state["step"] = "question"
                pending_state[line_user_id] = state
                reply(TextMessage(text=f"✅ 生日：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n💼 請描述您目前的職場困惑或想了解的問題："))
                return

            elif step == "question":
                state["data"]["question"] = user_msg
                state["data"]["follow_up_num"] = state.get("follow_up_num", 1)
                pending_state.pop(line_user_id, None)

                waiting_msg = random.choice(WAITING_MSGS_CAREER)
                reply(TextMessage(text=waiting_msg))

                t = threading.Thread(
                    target=_run_career_background,
                    args=(line_user_id, state["data"], service_id),
                    daemon=True
                )
                t.start()
                return

            elif step == "follow_up":
                svc = get_active_service(line_user_id, "career")
                if svc:
                    data = state.get("data", {})
                    data["question"] = user_msg
                    data["follow_up_num"] = (svc.get("follow_up_count") or 0) + 1
                    pending_state.pop(line_user_id, None)
                    reply(TextMessage(text=f"💼 收到您的追問，老師正在深入解讀...\n\n請稍候 🔮"))
                    t = threading.Thread(
                        target=_run_career_background,
                        args=(line_user_id, data, svc["service_id"]),
                        daemon=True
                    )
                    t.start()
                    return

        # ────────────────────────────────
        #  財運分析流程
        # ────────────────────────────────
        elif mode == "wealth":
            step = state.get("step")
            service_id = state.get("service_id")

            if step == "birth":
                date_str = parse_birth_input(user_msg)
                if not date_str:
                    reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20"))
                    return
                state["data"]["birth"] = date_str
                state["step"] = "question"
                pending_state[line_user_id] = state
                reply(TextMessage(text=f"✅ 生日：{date_str}（{get_zodiac(date_str) or '未知'}）\n\n💰 請描述您目前的財運困惑或想了解的問題："))
                return

            elif step == "question":
                state["data"]["question"] = user_msg
                state["data"]["follow_up_num"] = state.get("follow_up_num", 1)
                pending_state.pop(line_user_id, None)

                waiting_msg = random.choice(WAITING_MSGS_WEALTH)
                reply(TextMessage(text=waiting_msg))

                t = threading.Thread(
                    target=_run_wealth_background,
                    args=(line_user_id, state["data"], service_id),
                    daemon=True
                )
                t.start()
                return

            elif step == "follow_up":
                svc = get_active_service(line_user_id, "wealth")
                if svc:
                    data = state.get("data", {})
                    data["question"] = user_msg
                    data["follow_up_num"] = (svc.get("follow_up_count") or 0) + 1
                    pending_state.pop(line_user_id, None)
                    reply(TextMessage(text=f"💰 收到您的追問，老師正在深入解讀...\n\n請稍候 🔮"))
                    t = threading.Thread(
                        target=_run_wealth_background,
                        args=(line_user_id, data, svc["service_id"]),
                        daemon=True
                    )
                    t.start()
                    return

        # ────────────────────────────────
        #  生日設定流程
        # ────────────────────────────────
        elif mode == "set_birth":
            date_str = parse_birth_input(user_msg)
            if not date_str:
                reply(TextMessage(text="⚠️ 日期格式不正確，請重新輸入\n\n範例：1990-05-20 或 1990年5月20日"))
                return
            locked = user.get("birthdate_locked", False)
            if locked:
                pending_state.pop(line_user_id, None)
                reply(TextMessage(text="🔒 您的生日已鎖定，無法再次修改喔 🌙"))
                return
            supabase.table("users").update({
                "birth_date": date_str,
                "birthdate_locked": True
            }).eq("line_user_id", line_user_id).execute()
            pending_state.pop(line_user_id, None)
            reply(TextMessage(text=f"✅ 生日已設定為 {date_str}，並已鎖定 🔒\n\n星座：{get_zodiac(date_str) or '未知'} ✨\n\n現在老師可以為您提供更精準的占卜解讀 🔮"))
            return

    # ══════════════════════════════════════
    #  一般指令處理
    # ══════════════════════════════════════

    if user_msg in ["一週運勢"]:
        if not birth:
            reply(TextMessage(text="🌟 要解讀一週運勢，老師需要知道您的生日\n\n請輸入您的出生日期：\n\n格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日"))
            pending_state[line_user_id] = {"mode": "set_birth", "step": "input"}
            return

        reply(TextMessage(text="🌟 請選擇一週運勢占卜方式：\n\n1. 塔羅牌\n2. 八字命理\n3. 易經卦象\n\n請輸入數字或名稱"))
        pending_state[line_user_id] = {"mode": "weekly_choose", "step": "choose"}
        return

    if state.get("mode") == "weekly_choose":
        type_map = {"1": "tarot", "2": "bazi", "3": "iching", "塔羅牌": "tarot", "八字命理": "bazi", "易經卦象": "iching"}
        reading_type = type_map.get(user_msg)
        if not reading_type:
            reply(TextMessage(text="請輸入 1、2 或 3 選擇占卜方式"))
            return

        pending_state.pop(line_user_id, None)

        ok, msg = check_free_reading_quota(line_user_id, user)
        if not ok:
            if tokens < 1:
                reply(TextMessage(text=msg))
                return
            if not use_tokens(line_user_id, 1, "一週運勢"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return
        else:
            if not use_tokens(line_user_id, 1, "一週運勢"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return

        waiting_msg = random.choice(WAITING_MSGS_WEEKLY)
        reply(TextMessage(text=waiting_msg))

        t = threading.Thread(
            target=_run_weekly_fortune_background,
            args=(line_user_id, reading_type, zodiac, user),
            daemon=True
        )
        t.start()
        return

    # ── 塔羅占卜 ──
    if user_msg in ["塔羅占卜", "塔羅", "抽牌"]:
        if not birth:
            pending_state[line_user_id] = {"mode": "set_birth", "step": "input"}
            reply(TextMessage(text="🃏 老師需要知道您的生日，才能為您精準解讀\n\n請輸入您的出生日期：\n\n格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日"))
            return
        ok, msg = check_free_reading_quota(line_user_id, user)
        if not ok:
            if tokens < 1:
                reply(TextMessage(text=msg))
                return
            if not use_tokens(line_user_id, 1, "塔羅占卜"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return
        else:
            if not use_tokens(line_user_id, 1, "塔羅占卜"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return
        waiting_msg = random.choice(WAITING_MSGS_TAROT)
        reply(TextMessage(text=waiting_msg))
        do_reading_async(line_user_id, "今日整體運勢", "tarot", False, zodiac, user)
        return

    # ── 八字運勢 ──
    if user_msg in ["八字運勢", "八字", "八字命理"]:
        if not birth:
            pending_state[line_user_id] = {"mode": "set_birth", "step": "input"}
            reply(TextMessage(text="🀄 八字命理需要您的生日才能推算\n\n請輸入您的出生日期：\n\n格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日"))
            return
        ok, msg = check_free_reading_quota(line_user_id, user)
        if not ok:
            if tokens < 1:
                reply(TextMessage(text=msg))
                return
            if not use_tokens(line_user_id, 1, "八字運勢"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return
        else:
            if not use_tokens(line_user_id, 1, "八字運勢"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return
        waiting_msg = random.choice(WAITING_MSGS_BAZI)
        reply(TextMessage(text=waiting_msg))
        do_reading_async(line_user_id, "近期運勢", "bazi", False, zodiac, user)
        return

    # ── 易經問卜 ──
    if user_msg in ["易經問卜", "易經", "卦象"]:
        ok, msg = check_free_reading_quota(line_user_id, user)
        if not ok:
            if tokens < 1:
                reply(TextMessage(text=msg))
                return
            if not use_tokens(line_user_id, 1, "易經問卜"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return
        else:
            if not use_tokens(line_user_id, 1, "易經問卜"):
                reply(TextMessage(text="💎 代幣不足\n\n輸入「購買代幣」補充 🌙"))
                return
        waiting_msg = random.choice(WAITING_MSGS_ICHING)
        reply(TextMessage(text=waiting_msg))
        do_reading_async(line_user_id, "近期困惑", "iching", False, zodiac, user)
        return

    # ── 靈性占卜 ──
    if user_msg in ["靈性占卜", "靈性解讀"]:
        if tokens < 2:
            reply(TextMessage(text="💎 靈性占卜需要 2 顆代幣\n\n輸入「購買代幣」補充 🌙"))
            return
        pending_state[line_user_id] = {"mode": "spiritual", "step": "birth", "data": {}}
        reply(TextMessage(text="🌌 靈性占卜啟動\n\n老師將透過一系列問題，為您進行深度靈性解讀\n\n首先，請輸入您的出生日期：\n\n格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日"))
        return

    # ── 急救占卜 ──
    if user_msg in ["急救占卜", "急救"]:
        if tokens < 2:
            reply(TextMessage(text="💎 急救占卜需要 2 顆代幣\n\n輸入「購買代幣」補充 🌙"))
            return
        pending_state[line_user_id] = {"mode": "deep", "step": "choose_type"}
        reply(TextMessage(text="🆘 急救占卜啟動\n\n請選擇占卜方式：\n\n• 塔羅牌\n• 八字命理\n• 易經卦象"))
        return

    # ── 求籤問卜 ──
    if user_msg in ["求籤問卜", "求籤", "問卜"]:
        if tokens < 1:
            reply(TextMessage(text="💎 求籤問卜需要 1 顆代幣\n\n輸入「購買代幣」補充 🌙"))
            return
        categories = list(FORTUNE_STICK_CATEGORIES.keys())
        cat_list = "\n".join([f"• {c}" for c in categories])
        pending_state[line_user_id] = {"mode": "fortune_stick", "step": "choose_category"}
        reply(TextMessage(text=f"🎋 求籤問卜\n\n請選擇問卜類別：\n\n{cat_list}"))
        return

    # ── 天書服務 ──
    if user_msg in ["天書", "深度服務", "天書服務"]:
        reply(build_tianbook_flex())
        return

    # ── 購買指令 ──
    purchase_map = {
        "購買雙人合盤":  ("double_chart", 299),
        "購買流年運勢":  ("year_fortune",  299),
        "購買紫微斗數":  ("ziwei",         399),
        "購買復合分析":  ("love_reading",  499),
        "購買職場運勢":  ("career",        299),
        "購買財運分析":  ("wealth",        299),
    }
    if user_msg in purchase_map:
        product_type, amount = purchase_map[user_msg]
        service_names = {
            "double_chart": "💑 雙人合盤解析",
            "year_fortune": "📅 流年運勢報告",
            "ziwei":        "⭐ 紫微斗數命盤",
            "love_reading": "💔 復合分析",
            "career":       "💼 職場運勢",
            "wealth":       "💰 財運分析",
        }
        label = service_names.get(product_type, product_type)
        order_id = create_order(line_user_id, product_type, amount)
        pay_url = f"{RENDER_URL}/pay/go/{order_id}"
        reply(TextMessage(text=(
            f"📦 {label}\n\n"
            f"💰 金額：NT$ {amount}\n\n"
            f"請點擊以下連結完成付款：\n{pay_url}\n\n"
            f"付款完成後老師將立即為您開通服務 🔮"
        )))
        return

    # ── 代幣商店 ──
    token_shop_map = {
        "購買星塵入門包": ("星塵入門包", 99,  10),
        "購買月光超值包": ("月光超值包", 249, 30),
        "購買星河豪華包": ("星河豪華包", 599, 80),
    }
    if user_msg in token_shop_map:
        pkg_name, amount, tokens_to_add = token_shop_map[user_msg]
        order_id = str(uuid.uuid4()).replace("-", "")[:20]
        supabase.table("payments").insert({
            "order_id":       order_id,
            "user_id":        line_user_id,
            "package_type":   pkg_name,
            "amount":         amount,
            "tokens_to_add":  tokens_to_add,
            "status":         "pending"
        }).execute()
        pay_url = f"{RENDER_URL}/pay/go/{order_id}"
        reply(TextMessage(text=(
            f"💎 {pkg_name}\n\n"
            f"代幣數量：{tokens_to_add} 顆\n"
            f"金額：NT$ {amount}\n\n"
            f"請點擊以下連結完成付款：\n{pay_url}\n\n"
            f"付款完成後代幣將立即入帳 ✨"
        )))
        return

    if user_msg in ["購買代幣", "代幣商店", "儲值"]:
        reply(build_token_shop_flex())
        return

    # ── 我的代幣 ──
    if user_msg in ["我的代幣", "代幣", "餘額"]:
        reply(build_token_flex(user))
        return

    # ── 設定 ──
    if user_msg in ["設定", "個人設定"]:
        reply(build_settings_flex(user))
        return

    # ── 修改生日 ──
    if user_msg in ["修改生日", "設定生日", "更新生日"]:
        locked = user.get("birthdate_locked", False)
        if locked:
            reply(TextMessage(text="🔒 您的生日已鎖定，無法再次修改\n\n如有特殊需求請聯繫客服 🌙"))
            return
        pending_state[line_user_id] = {"mode": "set_birth", "step": "input"}
        reply(TextMessage(text="✏️ 請輸入您的出生日期：\n\n格式範例：\n1990-05-20\n1990/05/20\n1990年5月20日\n\n⚠️ 設定後將鎖定，請確認正確"))
        return

    # ── 查看紀錄 ──
    if user_msg in ["查看紀錄", "占卜紀錄", "紀錄"]:
        logs = supabase.table("tarot_logs").select("*").eq("line_user_id", line_user_id).order("created_at", desc=True).limit(5).execute()
        if not logs.data:
            reply(TextMessage(text="📋 您還沒有任何占卜紀錄\n\n輸入「塔羅占卜」開始您的第一次占卜 🔮"))
            return
        flex_msg = build_history_flex(logs.data)
        if flex_msg:
            reply(flex_msg)
        else:
            reply(TextMessage(text="📋 暫時無法讀取紀錄，請稍後再試"))
        return

    # ── 每日推播開關 ──
    if user_msg in ["開啟每日推播", "關閉每日推播"]:
        new_val = user_msg == "開啟每日推播"
        supabase.table("users").update({"daily_push": new_val}).eq("line_user_id", line_user_id).execute()
        status = "開啟" if new_val else "關閉"
        reply(TextMessage(text=f"✅ 每日推播已{status} {'🔔' if new_val else '🔕'}\n\n{'每天早上 8 點老師會為您送上今日星運 🌟' if new_val else '您已關閉每日推播，隨時可以重新開啟 🌙'}"))
        return

    # ── 簽到 ──
    if user_msg in ["簽到", "每日簽到"]:
        success, result = do_checkin(line_user_id)
        if not success:
            reply(TextMessage(text="✅ 您今天已經簽到過了！\n\n明天再來簽到吧 🌙"))
        else:
            days = result["days"]
            reward = result["reward"]
            msg = f"✅ 簽到成功！\n\n本週已簽到：{days} 天"
            if reward:
                msg += "\n\n🎉 恭喜！本週連續簽到 7 天，獲得 1 顆代幣獎勵！"
            else:
                msg += f"\n\n💡 連續簽到 7 天可獲得 1 顆代幣獎勵 🌟"
            reply(TextMessage(text=msg))
        return

    # ── 推薦好友 ──
    if user_msg in ["推薦好友", "邀請好友"]:
        ref_code = user.get("referral_code", "------")
        ref_count = user.get("referral_count", 0)
        reply(TextMessage(text=(
            f"👥 推薦好友計畫\n\n"
            f"您的專屬推薦碼：{ref_code}\n"
            f"已推薦人數：{ref_count} 人\n\n"
            f"🎁 推薦獎勵：\n"
            f"• 推薦滿 3 人：獲得 1 顆代幣\n"
            f"• 推薦滿 5 人：再獲得 1 顆代幣\n\n"
            f"📤 分享您的推薦碼給好友，邀請他們加入星運導航！"
        )))
        return

    # ── 幫助選單 ──
    if user_msg in ["幫助", "說明", "help", "Help", "選單", "功能"]:
        reply(TextMessage(text=(
            "🔮 星運導航功能選單\n\n"
            "【占卜服務】\n"
            "• 塔羅占卜（1 顆代幣）\n"
            "• 八字運勢（1 顆代幣）\n"
            "• 易經問卜（1 顆代幣）\n"
            "• 一週運勢（1 顆代幣）\n"
            "• 靈性占卜（2 顆代幣）\n"
            "• 急救占卜（2 顆代幣）\n"
            "• 求籤問卜（1 顆代幣）\n\n"
            "【天書深度服務】\n"
            "• 天書（查看深度服務）\n\n"
            "【帳戶管理】\n"
            "• 我的代幣\n"
            "• 購買代幣\n"
            "• 設定\n"
            "• 查看紀錄\n"
            "• 簽到\n"
            "• 推薦好友"
        )))
        return

    # ── 追問判斷（天書服務）──
    for svc_type in ["double_chart", "year_fortune", "ziwei"]:
        svc = get_active_service(line_user_id, svc_type)
        if svc:
            follow_up_num = (svc.get("follow_up_count") or 0) + 1
            svc_labels = {
                "double_chart": "💑 雙人合盤",
                "year_fortune":  "📅 流年運勢",
                "ziwei":         "⭐ 紫微斗數",
            }
            label = svc_labels.get(svc_type, "占卜")
            reply(TextMessage(text=f"{label}｜收到您的追問，老師正在深入解讀...\n\n請稍候 🔮"))
            t = threading.Thread(
                target=_run_follow_up_background,
                args=(line_user_id, svc_type, user_msg, svc["service_id"], follow_up_num),
                daemon=True
            )
            t.start()
            return

    # ── 復合分析追問 ──
    love_svc = get_active_service(line_user_id, "love_reading")
    if love_svc:
        question_num = (love_svc.get("follow_up_count") or 0) + 1
        state_update = {
            "mode": "love_reading",
            "step": "question",
            "service_id": love_svc["service_id"],
            "question_num": question_num + 1
        }
        pending_state[line_user_id] = state_update
        waiting_msg = random.choice(WAITING_MSGS_LOVE)
        reply(TextMessage(text=waiting_msg))
        t = threading.Thread(
            target=_run_love_reading_background,
            args=(line_user_id, user_msg, question_num, love_svc["service_id"]),
            daemon=True
        )
        t.start()
        return

    # ── 職場/財運追問 ──
    for svc_type in ["career", "wealth"]:
        svc = get_active_service(line_user_id, svc_type)
        if svc:
            data = {"follow_up_num": (svc.get("follow_up_count") or 0) + 1, "question": user_msg}
            birth_data = supabase.table("services").select("*").eq("service_id", svc["service_id"]).execute()
            if birth_data.data:
                pass
            svc_labels = {"career": "💼 職場運勢", "wealth": "💰 財運分析"}
            label = svc_labels.get(svc_type, "占卜")
            reply(TextMessage(text=f"{label}｜收到您的追問，老師正在深入解讀...\n\n請稍候 🔮"))
            if svc_type == "career":
                t = threading.Thread(
                    target=_run_career_background,
                    args=(line_user_id, data, svc["service_id"]),
                    daemon=True
                )
            else:
                t = threading.Thread(
                    target=_run_wealth_background,
                    args=(line_user_id, data, svc["service_id"]),
                    daemon=True
                )
            t.start()
            return

    # ── AI 自由對話（偏題過濾）──
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content
        reply(TextMessage(text=response_text))
    except Exception as e:
        print(f"[AI 對話錯誤] {e}")
        reply(TextMessage(text="✨ 星辰訊號有些微干擾，請稍後再試 🙏"))


# ══════════════════════════════════════════
#  啟動
# ══════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
