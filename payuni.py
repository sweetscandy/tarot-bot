import hashlib
import base64
import datetime
import os
import urllib.parse
import binascii
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID", "U011578308")
PAYUNI_HASH_KEY    = os.environ.get("PAYUNI_HASH_KEY", "bweawvqubQiapGNfRTQa1ETvU1SOzDS8")
PAYUNI_HASH_IV     = os.environ.get("PAYUNI_HASH_IV",  "6DJBnqZ8VP5XW8Z7")

PAYUNI_API_URL = "https://api.payuni.com.tw/api/upp"

print(f"[PayUni 初始化] MerchantID={PAYUNI_MERCHANT_ID}")


def _aes_encrypt(data: dict) -> str:
    plain = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}"
        for k, v in data.items()
    )
    print(f"[PayUni _aes_encrypt] 明文(encoded): {plain}")
    key    = PAYUNI_HASH_KEY.encode("utf-8")
    iv     = PAYUNI_HASH_IV.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(plain.encode("utf-8"), AES.block_size))
    # 送出時用 Base64
    return base64.b64encode(encrypted).decode("utf-8")


def _aes_decrypt(encrypt_info: str) -> dict:
    """
    PayUni 回傳的 EncryptInfo 可能是 Hex 或 Base64，自動判斷。
    """
    try:
        key = PAYUNI_HASH_KEY.encode("utf-8")
        iv  = PAYUNI_HASH_IV.encode("utf-8")

        # 嘗試判斷是 Hex 還是 Base64
        stripped = encrypt_info.strip()
        try:
            # 如果全是 hex 字元，優先用 hex 解碼
            raw_bytes = binascii.unhexlify(stripped)
            print(f"[PayUni _aes_decrypt] 使用 Hex 解碼")
        except Exception:
            # 否則用 Base64
            raw_bytes = base64.b64decode(stripped)
            print(f"[PayUni _aes_decrypt] 使用 Base64 解碼")

        cipher = AES.new(key, AES.MODE_CBC, iv)
        raw    = unpad(cipher.decrypt(raw_bytes), AES.block_size)

        result = {}
        for part in raw.decode("utf-8").split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                result[k] = urllib.parse.unquote(v)
        print(f"[PayUni _aes_decrypt] 解密成功: {result}")
        return result
    except Exception as e:
        print(f"[PayUni _aes_decrypt] 解密失敗: {e}")
        return {}


def _generate_hash_info(encrypt_info: str) -> str:
    raw = f"HashKey={PAYUNI_HASH_KEY}&EncryptInfo={encrypt_info}&HashIV={PAYUNI_HASH_IV}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def create_payment(user_id: str, amount: int, order_id: str,
                   product_name: str, confirm_url: str):

    render_url = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
    notify_url = f"{render_url}/pay/notify"

    safe_desc    = product_name.replace("・", "-").replace("　", " ")[:50]
    mer_trade_no = order_id[:25]

    params = {
        "MerID":       PAYUNI_MERCHANT_ID,
        "MerTradeNo":  mer_trade_no,
        "TradeAmt":    str(amount),
        "ProdDesc":    safe_desc,
        "ReturnURL":   confirm_url,
        "NotifyURL":   notify_url,
        "BackURL":     confirm_url,
        "Timestamp":   str(int(datetime.datetime.now().timestamp())),
        "RespondType": "JSON",
    }

    print(f"[PayUni create_payment] 原始參數: {params}")

    encrypt_info = _aes_encrypt(params)
    hash_info    = _generate_hash_info(encrypt_info)

    print(f"[PayUni create_payment] EncryptInfo={encrypt_info[:50]}...")
    print(f"[PayUni create_payment] HashInfo={hash_info}")

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
    <input type="hidden" name="MerID"       value="{PAYUNI_MERCHANT_ID}">
    <input type="hidden" name="Version"     value="2.0">
    <input type="hidden" name="EncryptInfo" value="{encrypt_info}">
    <input type="hidden" name="HashInfo"    value="{hash_info}">
  </form>
  <p style="color:#6B4FA0;">⏳ 正在跳轉至付款頁面，請稍候...</p>
</body>
</html>"""

    return html, mer_trade_no


def verify_notify(form_data: dict) -> bool:
    received     = form_data.get("HashInfo", "")
    encrypt_info = form_data.get("EncryptInfo", "")
    if not encrypt_info:
        print(f"[PayUni verify_notify] EncryptInfo 為空，驗簽失敗")
        return False
    expected = _generate_hash_info(encrypt_info)
    ok = received.upper() == expected.upper()
    print(f"[PayUni verify_notify] received={received[:20]}, expected={expected[:20]}, ok={ok}")
    return ok


def get_notify_data(form_data: dict) -> dict:
    encrypt_info = form_data.get("EncryptInfo", "")
    result = _aes_decrypt(encrypt_info)
    print(f"[PayUni get_notify_data] 解密結果: {result}")
    return result


def get_return_data(form_data: dict) -> dict:
    """
    ReturnURL 回傳：Status 在外層，EncryptInfo 解密後有完整資料。
    """
    outer_status = form_data.get("Status", "")
    encrypt_info = form_data.get("EncryptInfo", "")

    if encrypt_info:
        inner = _aes_decrypt(encrypt_info)
    else:
        inner = {}

    # 外層 Status 優先
    if outer_status:
        inner["Status"] = outer_status

    print(f"[PayUni get_return_data] 合併結果: {inner}")
    return inner


def is_payment_success(data: dict) -> bool:
    status       = data.get("Status", "")
    trade_status = data.get("TradeStatus", "")
    amt          = data.get("TradeAmt", 0)
    print(f"[PayUni is_payment_success] Status={status}, TradeStatus={trade_status}, TradeAmt={amt}")
    return status == "SUCCESS" and str(trade_status) == "1"


def get_order_id_from_notify(form_data: dict) -> str:
    data = get_notify_data(form_data)
    return data.get("MerTradeNo", "")
