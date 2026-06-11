import hashlib
import os
import time
import urllib.parse
import base64

from Crypto.Cipher import AES


# ══════════════════════════════════════════
# PAYUNi 基本設定
# ══════════════════════════════════════════
# ⚠️ 請務必在 Render Environment 設定：
# PAYUNI_MERCHANT_ID
# PAYUNI_HASH_KEY
# PAYUNI_HASH_IV
# RENDER_URL

PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID", "")
PAYUNI_HASH_KEY = os.environ.get("PAYUNI_HASH_KEY", "")
PAYUNI_HASH_IV = os.environ.get("PAYUNI_HASH_IV", "")

# UPP 跳轉付款正式環境
PAYUNI_API_URL = "https://api.payuni.com.tw/api/upp"

# 如需測試環境，改用這行：
# PAYUNI_API_URL = "https://sandbox-api.payuni.com.tw/api/upp"


print(
    f"[PayUni 初始化] "
    f"MerchantID={PAYUNI_MERCHANT_ID}, AES_MODE=AES-256-GCM, API={PAYUNI_API_URL}"
)


def _check_config():
    """
    檢查必要環境變數是否存在。
    PAYUNi AES-256-GCM 規格：
    - HashKey / AesKey 通常為 32 bytes
    - HashIV / AesIV 通常為 16 bytes
    """
    missing = []

    if not PAYUNI_MERCHANT_ID:
        missing.append("PAYUNI_MERCHANT_ID")
    if not PAYUNI_HASH_KEY:
        missing.append("PAYUNI_HASH_KEY")
    if not PAYUNI_HASH_IV:
        missing.append("PAYUNI_HASH_IV")

    if missing:
        raise RuntimeError(f"PAYUNi 環境變數缺少：{', '.join(missing)}")

    key_len = len(PAYUNI_HASH_KEY.strip().encode("utf-8"))
    iv_len = len(PAYUNI_HASH_IV.strip().encode("utf-8"))

    if key_len != 32:
        raise RuntimeError(f"PAYUNi HashKey 長度錯誤：目前 {key_len} bytes，應為 32 bytes")

    if iv_len != 16:
        raise RuntimeError(f"PAYUNi HashIV 長度錯誤：目前 {iv_len} bytes，應為 16 bytes")


# ══════════════════════════════════════════
# AES-GCM 加密 / 解密
# ══════════════════════════════════════════

def _aes_encrypt(data: dict) -> str:
    """
    PAYUNi EncryptInfo 加密。

    對應 PHP 範例：

    $encrypted = openssl_encrypt(
        http_build_query($data),
        "aes-256-gcm",
        trim($merKey),
        0,
        trim($merIV),
        $tag
    );

    return trim(bin2hex($encrypted . ":::" . base64_encode($tag)));

    注意：
    PHP openssl_encrypt options=0 時，$encrypted 是 Base64 字串，
    不是 raw binary ciphertext。
    """
    _check_config()

    # 對應 PHP http_build_query($data)
    plain = urllib.parse.urlencode(data)

    print(f"[PayUni _aes_encrypt] 明文(http_build_query): {plain}")

    key = PAYUNI_HASH_KEY.strip().encode("utf-8")
    iv = PAYUNI_HASH_IV.strip().encode("utf-8")

    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    encrypted_raw, tag = cipher.encrypt_and_digest(plain.encode("utf-8"))

    # ✅ 模擬 PHP openssl_encrypt options=0 的回傳：
    # PHP 會回傳 base64 字串，所以這裡也要先 base64 encode ciphertext
    encrypted_b64 = base64.b64encode(encrypted_raw)
    tag_b64 = base64.b64encode(tag)

    payload = encrypted_b64 + b":::" + tag_b64
    encrypt_info = payload.hex()

    print(f"[PayUni _aes_encrypt] GCM encrypted raw length={len(encrypted_raw)}")
    print(f"[PayUni _aes_encrypt] encrypted_b64={encrypted_b64.decode('utf-8')[:80]}...")
    print(f"[PayUni _aes_encrypt] tag_b64={tag_b64.decode('utf-8')}")
    print(f"[PayUni _aes_encrypt] Hex EncryptInfo: {encrypt_info[:80]}...")

    return encrypt_info


def _aes_decrypt(encrypt_info: str) -> dict:
    """
    PAYUNi EncryptInfo 解密。

    對應 PHP 範例：

    list($encryptData, $tag) = explode(":::", hex2bin($encryptStr), 2);

    return openssl_decrypt(
        $encryptData,
        "aes-256-gcm",
        trim($merKey),
        0,
        trim($merIV),
        base64_decode($tag)
    );

    注意：
    PHP openssl_decrypt options=0 時，$encryptData 是 Base64 字串。
    因此 Python 這邊要先 base64 decode ciphertext。
    """
    try:
        _check_config()

        if not encrypt_info:
            print("[PayUni _aes_decrypt] EncryptInfo 為空")
            return {}

        key = PAYUNI_HASH_KEY.strip().encode("utf-8")
        iv = PAYUNI_HASH_IV.strip().encode("utf-8")

        payload = bytes.fromhex(encrypt_info.strip())

        print(f"[PayUni _aes_decrypt] Hex 解碼成功，payload length={len(payload)}")

        if b":::" not in payload:
            print("[PayUni _aes_decrypt] payload 缺少 ::: 分隔符")
            print(f"[PayUni _aes_decrypt] payload raw preview={payload[:100]}")
            return {}

        encrypt_data_b64, tag_b64 = payload.split(b":::", 1)

        encrypted_raw = base64.b64decode(encrypt_data_b64)
        tag = base64.b64decode(tag_b64)

        print(
            f"[PayUni _aes_decrypt] "
            f"encrypt_data_b64={encrypt_data_b64.decode('utf-8', errors='ignore')[:80]}..."
        )
        print(f"[PayUni _aes_decrypt] encrypted raw length={len(encrypted_raw)}")
        print(f"[PayUni _aes_decrypt] tag_b64={tag_b64.decode('utf-8', errors='ignore')}")

        cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
        raw = cipher.decrypt_and_verify(encrypted_raw, tag)

        decoded = raw.decode("utf-8")

        print(f"[PayUni _aes_decrypt] 解密明文: {decoded}")

        result = {}
        for k, v in urllib.parse.parse_qsl(decoded, keep_blank_values=True):
            result[k] = v

        print(f"[PayUni _aes_decrypt] 解密成功: {result}")

        return result

    except Exception as e:
        print(f"[PayUni _aes_decrypt] 解密失敗: {e}")
        return {}


# ══════════════════════════════════════════
# HashInfo
# ══════════════════════════════════════════

def _generate_hash_info(encrypt_info: str) -> str:
    """
    產生 PAYUNi HashInfo。

    對應 PHP 範例：

    strtoupper(hash("sha256", "$merKey$encryptStr$merIV"));
    """
    _check_config()

    raw = f"{PAYUNI_HASH_KEY.strip()}{encrypt_info}{PAYUNI_HASH_IV.strip()}"
    hash_info = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()

    print(f"[PayUni _generate_hash_info] HashInfo={hash_info}")

    return hash_info


# ══════════════════════════════════════════
# 建立付款表單
# ══════════════════════════════════════════

def create_payment(user_id: str, amount: int, order_id: str,
                   product_name: str, confirm_url: str):
    """
    建立 PAYUNi UPP 跳轉付款 HTML 表單。

    重點：
    - MerTradeNo 直接使用 order_id
    - PAYUNi 回傳時，MerTradeNo 就能直接對應 Supabase orders/payments 的 order_id
    - EncryptInfo 使用 AES-256-GCM
    - EncryptInfo 格式為 hex(base64(ciphertext) + ":::" + base64(tag))
    - HashInfo 使用 SHA256(HashKey + EncryptInfo + HashIV)
    """
    _check_config()

    render_url = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
    notify_url = f"{render_url}/pay/notify"

    # 商品名稱簡化，避免特殊字元造成 PAYUNi 判讀問題
    safe_desc = (
        product_name
        .replace("・", "-")
        .replace("　", " ")
        .replace("｜", "-")
        .strip()
    )[:50]

    # 直接使用系統 order_id
    # PAYUNi 常見限制：MerTradeNo 長度 25 以內，格式 [A-Za-z0-9_-]
    # 你的 order_id 是 uuid 前 20 碼，符合規格
    mer_trade_no = order_id

    params = {
        "MerID": PAYUNI_MERCHANT_ID,
        "MerTradeNo": mer_trade_no,
        "TradeAmt": str(int(amount)),
        "ProdDesc": safe_desc,
        "ReturnURL": confirm_url,
        "NotifyURL": notify_url,
        "BackURL": confirm_url,
        "Timestamp": str(int(time.time())),
        "RespondType": "JSON",
    }

    print(f"[PayUni create_payment] user_id={user_id}")
    print(f"[PayUni create_payment] order_id={order_id}")
    print(f"[PayUni create_payment] MerTradeNo={mer_trade_no}")
    print(f"[PayUni create_payment] 原始參數: {params}")

    encrypt_info = _aes_encrypt(params)
    hash_info = _generate_hash_info(encrypt_info)

    print(f"[PayUni create_payment] EncryptInfo={encrypt_info[:80]}...")
    print(f"[PayUni create_payment] HashInfo={hash_info}")

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>前往付款</title>
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #F8F4FF;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 20px;
    }}

    .card {{
      background: white;
      border-radius: 16px;
      padding: 40px 32px;
      text-align: center;
      box-shadow: 0 4px 20px rgba(107, 79, 160, 0.15);
      max-width: 360px;
      width: 100%;
    }}

    .icon {{
      font-size: 48px;
      margin-bottom: 16px;
    }}

    h2 {{
      color: #6B4FA0;
      font-size: 20px;
      margin-bottom: 8px;
    }}

    .amount {{
      font-size: 26px;
      font-weight: bold;
      color: #6B4FA0;
      margin: 14px 0;
    }}

    .sub {{
      color: #888;
      font-size: 14px;
      line-height: 1.6;
      margin-bottom: 28px;
    }}

    .btn {{
      display: block;
      width: 100%;
      padding: 16px;
      background: #6B4FA0;
      color: white;
      font-size: 17px;
      font-weight: bold;
      border: none;
      border-radius: 12px;
      cursor: pointer;
      letter-spacing: 1px;
    }}

    .btn:active {{
      background: #4A3080;
    }}

    .safe {{
      color: #aaa;
      font-size: 12px;
      margin-top: 16px;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">💳</div>

    <h2>前往 PAYUNi 付款</h2>

    <div class="amount">NT$ {int(amount):,}</div>

    <p class="sub">
      請點下方按鈕完成付款<br>
      將跳轉至 PAYUNi 安全付款頁面
    </p>

    <form method="POST" action="{PAYUNI_API_URL}">
      <input type="hidden" name="MerID" value="{PAYUNI_MERCHANT_ID}">
      <input type="hidden" name="Version" value="1.0">
      <input type="hidden" name="EncryptInfo" value="{encrypt_info}">
      <input type="hidden" name="HashInfo" value="{hash_info}">

      <button type="submit" class="btn">前往付款 →</button>
    </form>

    <p class="safe">
      🔒 由 PAYUNi 提供安全加密付款<br>
      若付款頁未開啟，請返回 LINE 重新點擊連結
    </p>
  </div>
</body>
</html>"""

    return html, mer_trade_no


# ══════════════════════════════════════════
# 通知驗證與資料解析
# ══════════════════════════════════════════

def verify_notify(form_data: dict) -> bool:
    """
    驗證 PAYUNi 背景通知 HashInfo。
    """
    received = form_data.get("HashInfo", "")
    encrypt_info = form_data.get("EncryptInfo", "")

    if not encrypt_info:
        print("[PayUni verify_notify] EncryptInfo 為空，驗簽失敗")
        return False

    if not received:
        print("[PayUni verify_notify] HashInfo 為空，驗簽失敗")
        return False

    expected = _generate_hash_info(encrypt_info)
    ok = received.upper() == expected.upper()

    print(f"[PayUni verify_notify] received={received[:20]}...")
    print(f"[PayUni verify_notify] expected={expected[:20]}...")
    print(f"[PayUni verify_notify] ok={ok}")

    return ok


def get_notify_data(form_data: dict) -> dict:
    """
    取得 PAYUNi 背景通知解密資料。
    """
    encrypt_info = form_data.get("EncryptInfo", "")
    result = _aes_decrypt(encrypt_info)

    print(f"[PayUni get_notify_data] 解密結果: {result}")

    return result


def get_return_data(form_data: dict) -> dict:
    """
    取得 PAYUNi 前景返回資料。

    有些失敗狀態會直接帶 Status 在外層，
    所以這裡會把外層 Status 合併進解密結果。
    """
    outer_status = form_data.get("Status", "")
    encrypt_info = form_data.get("EncryptInfo", "")

    if encrypt_info:
        inner = _aes_decrypt(encrypt_info)
    else:
        inner = {}

    if outer_status:
        inner["Status"] = outer_status

    # 外層欄位也保留，方便 debug
    for key in ["MerID", "Version", "HashInfo"]:
        if key in form_data and key not in inner:
            inner[key] = form_data.get(key)

    print(f"[PayUni get_return_data] 合併結果: {inner}")

    return inner


def is_payment_success(data: dict) -> bool:
    """
    判斷 PAYUNi 付款是否成功。
    """
    status = data.get("Status", "")
    trade_status = data.get("TradeStatus", "")
    trade_amt = data.get("TradeAmt", "")

    print(
        f"[PayUni is_payment_success] "
        f"Status={status}, TradeStatus={trade_status}, TradeAmt={trade_amt}"
    )

    return status == "SUCCESS" and str(trade_status) == "1"


def get_order_id_from_notify(form_data: dict) -> str:
    """
    從 PAYUNi 通知資料取得訂單編號。
    因為 create_payment 已經讓 MerTradeNo = order_id，
    所以這裡回傳 MerTradeNo 就是你的系統 order_id。
    """
    data = get_notify_data(form_data)
    order_id = data.get("MerTradeNo", "")

    print(f"[PayUni get_order_id_from_notify] order_id={order_id}")

    return order_id
