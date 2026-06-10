import hashlib
import base64
import datetime
import os
import urllib.parse
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# ====================== 環境變數 ======================
PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID")
PAYUNI_HASH_KEY    = os.environ.get("PAYUNI_HASH_KEY")
PAYUNI_HASH_IV     = os.environ.get("PAYUNI_HASH_IV")

PAYUNI_API_URL = "https://api.payuni.com.tw/api/pay"

print(f"[PayUni] 初始化完成 MerchantID={PAYUNI_MERCHANT_ID}")


# ====================== AES 加密 ======================
def _aes_encrypt(data: dict) -> str:
    """將 dict 轉成 URL encoded 字串後 AES 加密"""
    plain = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}" 
        for k, v in data.items()
    )
    print(f"[PayUni] 加密明文: {plain}")

    key = PAYUNI_HASH_KEY.encode("utf-8")
    iv = PAYUNI_HASH_IV.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(plain.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def _aes_decrypt(encrypt_info: str) -> dict:
    """解密 Payuni 回傳的 EncryptInfo"""
    key = PAYUNI_HASH_KEY.encode("utf-8")
    iv = PAYUNI_HASH_IV.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    raw = unpad(cipher.decrypt(base64.b64decode(encrypt_info)), AES.block_size)

    result = {}
    for part in raw.decode("utf-8").split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k] = urllib.parse.unquote(v)
    return result


# ====================== HashCode ======================
def _generate_hash_code(encrypt_info: str) -> str:
    raw = f"HashKey={PAYUNI_HASH_KEY}&EncryptInfo={encrypt_info}&HashIV={PAYUNI_HASH_IV}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


# ====================== 建立付款 ======================
def create_payment(user_id: str, amount: int, order_id: str,
                   product_name: str, confirm_url: str):

    render_url = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
    notify_url = f"{render_url}/pay/notify"

    # Payuni 正確參數名稱
    params = {
        "MerchantNo":       PAYUNI_MERCHANT_ID,
        "MerchantOrderNo":  order_id[:30],
        "Amt":              str(amount),
        "ItemDesc":         product_name[:50],
        "ReturnURL":        confirm_url,
        "NotifyURL":        notify_url,
        "BackURL":          confirm_url,
        "Timestamp":        str(int(datetime.datetime.now().timestamp())),
        "RespondType":      "JSON",
    }

    print(f"[PayUni] 建立付款參數: {params}")

    encrypt_info = _aes_encrypt(params)
    hash_code    = _generate_hash_code(encrypt_info)

    print(f"[PayUni] EncryptInfo={encrypt_info[:60]}...")
    print(f"[PayUni] HashCode={hash_code}")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>前往付款...</title>
</head>
<body onload="document.forms[0].submit()"
      style="font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;">
  <form method="POST" action="{PAYUNI_API_URL}">
    <input type="hidden" name="MerchantNo"  value="{PAYUNI_MERCHANT_ID}">
    <input type="hidden" name="EncryptInfo" value="{encrypt_info}">
    <input type="hidden" name="HashCode"    value="{hash_code}">
  </form>
  <p style="color:#6B4FA0;">⏳ 正在跳轉至付款頁面，請稍候...</p>
</body>
</html>"""

    return html, order_id[:30]


# ====================== 通知驗證 ======================
def verify_notify(form_data: dict) -> bool:
    received     = form_data.get("HashCode", "")
    encrypt_info = form_data.get("EncryptInfo", "")
    expected     = _generate_hash_code(encrypt_info)
    print(f"[PayUni] verify_notify received={received[:20]} expected={expected[:20]}")
    return received.upper() == expected.upper()


def get_notify_data(form_data: dict) -> dict:
    encrypt_info = form_data.get("EncryptInfo", "")
    result = _aes_decrypt(encrypt_info)
    print(f"[PayUni] 解密結果: {result}")
    return result


def is_payment_success(data: dict) -> bool:
    status = data.get("Status")
    amt    = data.get("TradeAmt", 0)
    print(f"[PayUni] is_payment_success Status={status}, TradeAmt={amt}")
    return status == "SUCCESS" and int(amt) > 0


def get_order_id_from_notify(form_data: dict) -> str:
    data = get_notify_data(form_data)
    return data.get("MerchantOrderNo", "")
