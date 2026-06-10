import hashlib
import base64
import datetime
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID", "U011578308")
PAYUNI_HASH_KEY    = os.environ.get("PAYUNI_HASH_KEY", "bweawvqubQiapGNfRTQa1ETvU1SOzDS8")
PAYUNI_HASH_IV     = os.environ.get("PAYUNI_HASH_IV",  "6DJBnqZ8VP5XW8Z7")

PAYUNI_API_URL = "https://api.payuni.com.tw/api/pay"

print(f"[PayUni 初始化] MerchantID={PAYUNI_MERCHANT_ID}")
print(f"[PayUni 初始化] HashKey 長度={len(PAYUNI_HASH_KEY)}, 前4碼={PAYUNI_HASH_KEY[:4]}")
print(f"[PayUni 初始化] HashIV  長度={len(PAYUNI_HASH_IV)},  前4碼={PAYUNI_HASH_IV[:4]}")


def _aes_encrypt(data: dict) -> str:
    plain  = "&".join(f"{k}={v}" for k, v in data.items())
    key    = PAYUNI_HASH_KEY.encode("utf-8")
    iv     = PAYUNI_HASH_IV.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(plain.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def _aes_decrypt(encrypt_info: str) -> dict:
    key    = PAYUNI_HASH_KEY.encode("utf-8")
    iv     = PAYUNI_HASH_IV.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    raw    = unpad(cipher.decrypt(base64.b64decode(encrypt_info)), AES.block_size)
    result = {}
    for part in raw.decode("utf-8").split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k] = v
    return result


def _generate_hash_code(encrypt_info: str) -> str:
    # ★ 修正：加入 EncryptInfo= 前綴
    raw = f"HashKey={PAYUNI_HASH_KEY}&EncryptInfo={encrypt_info}&HashIV={PAYUNI_HASH_IV}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def create_payment(user_id: str, amount: int, order_id: str,
                   product_name: str, confirm_url: str):

    render_url = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
    notify_url = f"{render_url}/pay/notify"

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

    print(f"[PayUni create_payment] 原始參數: {params}")

    encrypt_info = _aes_encrypt(params)
    hash_code    = _generate_hash_code(encrypt_info)

    print(f"[PayUni create_payment] MerchantNo={PAYUNI_MERCHANT_ID}")
    print(f"[PayUni create_payment] EncryptInfo={encrypt_info}")
    print(f"[PayUni create_payment] HashCode={hash_code}")

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
    received     = form_data.get("HashCode", "")
    encrypt_info = form_data.get("EncryptInfo", "")
    expected     = _generate_hash_code(encrypt_info)
    print(f"[PayUni verify_notify] received={received[:20]}, expected={expected[:20]}")
    return received.upper() == expected.upper()


def get_notify_data(form_data: dict) -> dict:
    encrypt_info = form_data.get("EncryptInfo", "")
    result = _aes_decrypt(encrypt_info)
    print(f"[PayUni get_notify_data] 解密結果: {result}")
    return result


def is_payment_success(data: dict) -> bool:
    status = data.get("Status")
    amt    = data.get("Amt", 0)
    print(f"[PayUni is_payment_success] Status={status}, Amt={amt}")
    return (
        status == "SUCCESS" and
        int(amt) > 0
    )


def get_order_id_from_notify(form_data: dict) -> str:
    data = get_notify_data(form_data)
    return data.get("MerchantOrderNo", "")
