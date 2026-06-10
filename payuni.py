import hashlib
import base64
import json
import datetime
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID", "U011578308")
PAYUNI_HASH_KEY    = os.environ.get("PAYUNI_HASH_KEY", "bweawvqubQiapGNfRTQa1ETvU1SOzDS8")
PAYUNI_HASH_IV     = os.environ.get("PAYUNI_HASH_IV",  "6DJBnqZ8VP5XW8Z7")

PAYUNI_API_URL = "https://api.payuni.com.tw/api/pay"


def _aes_encrypt(data: dict) -> str:
    """
    AES-256-CBC 加密
    1. dict → URL query string（key=value&key=value）
    2. PKCS7 padding
    3. Base64 encode → 回傳 EncryptInfo
    """
    plain = "&".join(f"{k}={v}" for k, v in data.items())
    key   = PAYUNI_HASH_KEY.encode("utf-8")   # 32 bytes
    iv    = PAYUNI_HASH_IV.encode("utf-8")    # 16 bytes
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(plain.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def _aes_decrypt(encrypt_info: str) -> dict:
    """
    AES-256-CBC 解密（用於解析 Notify 回傳的 EncryptInfo）
    """
    key  = PAYUNI_HASH_KEY.encode("utf-8")
    iv   = PAYUNI_HASH_IV.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    raw  = unpad(cipher.decrypt(base64.b64decode(encrypt_info)), AES.block_size)
    # 解出來是 key=value&key=value 格式
    result = {}
    for part in raw.decode("utf-8").split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k] = v
    return result


def _generate_hash_code(encrypt_info: str) -> str:
    """
    HashCode = SHA256(HashKey + EncryptInfo + HashIV) → 大寫
    """
    raw = f"HashKey={PAYUNI_HASH_KEY}&{encrypt_info}&HashIV={PAYUNI_HASH_IV}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def create_payment(user_id: str, amount: int, order_id: str,
                   product_name: str, confirm_url: str):
    """
    產生 PayUni 付款表單 HTML（POST 自動跳轉）
    回傳 (html_str, order_id)
    """
    render_url = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
    notify_url = f"{render_url}/pay/notify"

    # ① 組成要加密的參數
    params = {
        "MerchantOrderNo": order_id[:30],
        "Amt":             str(amount),
        "ItemDesc":        product_name[:50],
        "NotifyURL":       notify_url,
        "ReturnURL":       confirm_url,
        "ClientBackURL":   confirm_url,
        "EmailModify":     "0",
        "RespondType":     "JSON",
        "TimeStamp":       str(int(datetime.datetime.now().timestamp())),
    }

    # ② AES 加密 → EncryptInfo
    encrypt_info = _aes_encrypt(params)

    # ③ SHA256 簽章 → HashCode
    hash_code = _generate_hash_code(encrypt_info)

    # ④ 組成 POST 表單（只需三個欄位）
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>前往付款...</title>
</head>
<body onload="document.forms[0].submit()"
      style="font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;">
  <form method="POST" action="{PAYUNI_API_URL}">
    <input type="hidden" name="MerchantNo"   value="{PAYUNI_MERCHANT_ID}">
    <input type="hidden" name="EncryptInfo"  value="{encrypt_info}">
    <input type="hidden" name="HashCode"     value="{hash_code}">
  </form>
  <p style="color:#6B4FA0;">⏳ 正在跳轉至付款頁面，請稍候...</p>
</body>
</html>"""

    return html, order_id[:30]


def verify_notify(form_data: dict) -> bool:
    """
    驗證 PayUni Notify 的 HashCode
    """
    received     = form_data.get("HashCode", "")
    encrypt_info = form_data.get("EncryptInfo", "")
    expected     = _generate_hash_code(encrypt_info)
    return received.upper() == expected.upper()


def get_notify_data(form_data: dict) -> dict:
    """
    解密 Notify 的 EncryptInfo，回傳明文 dict
    """
    encrypt_info = form_data.get("EncryptInfo", "")
    return _aes_decrypt(encrypt_info)


def is_payment_success(data: dict) -> bool:
    """
    判斷付款是否成功（傳入解密後的 dict）
    Status = SUCCESS 且 Amt > 0
    """
    return (
        data.get("Status") == "SUCCESS" and
        int(data.get("Amt", 0)) > 0
    )


def get_order_id_from_notify(form_data: dict) -> str:
    """
    從 Notify 取得訂單編號（先解密再取值）
    """
    data = get_notify_data(form_data)
    return data.get("MerchantOrderNo", "")
