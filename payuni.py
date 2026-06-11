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
    return base64.b64encode(encrypted).decode("utf-8")


def _aes_decrypt(encrypt_info: str) -> dict:
    try:
        key = PAYUNI_HASH_KEY.encode("utf-8")
        iv  = PAYUNI_HASH_IV.encode("utf-8")

        stripped = encrypt_info.strip()

        # 嘗試 Hex 解碼
        try:
            raw_bytes = binascii.unhexlify(stripped)
            print(f"[PayUni _aes_decrypt] 第一層 Hex 解碼成功，長度={len(raw_bytes)}")

            # 檢查是否還有第二層 Base64
            try:
                inner = raw_bytes.decode("utf-8")
                raw_bytes = base64.b64decode(inner)
                print(f"[PayUni _aes_decrypt] 第二層 Base64 解碼成功，長度={len(raw_bytes)}")
            except Exception:
                print(f"[PayUni _aes_decrypt] 無第二層，直接用 Hex 結果")

        except Exception:
            raw_bytes = base64.b64decode(stripped)
            print(f"[PayUni _aes_decrypt] 使用 Base64 解碼，長度={len(raw_bytes)}")

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
  <title>前往付款</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, sans-serif;
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
      box-shadow: 0 4px 20px rgba(107,79,160,0.15);
      max-width: 360px;
      width: 100%;
    }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h2 {{ color: #6B4FA0; font-size: 20px; margin-bottom: 8px; }}
    .sub {{ color: #888; font-size: 14px; margin-bottom: 28px; }}
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
    .btn:active {{ background: #4A3080; }}
    .safe {{ color: #aaa; font-size: 12px; margin-top: 16px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">💳</div>
    <h2>前往 PAYUNi 付款</h2>
    <p class="sub">請點下方按鈕完成付款<br>將跳轉至安全付款頁面</p>
    <form method="POST" action="{PAYUNI_API_URL}">
      <input type="hidden" name="MerID"       value="{PAYUNI_MERCHANT_ID}">
      <input type="hidden" name="Version"     value="2.0">
      <input type="hidden" name="EncryptInfo" value="{encrypt_info}">
      <input type="hidden" name="HashInfo"    value="{hash_info}">
      <button type="submit" class="btn">前往付款 →</button>
    </form>
    <p class="safe">🔒 由 PAYUNi 提供安全加密付款</p>
  </div>
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
    outer_status = form_data.get("Status", "")
    encrypt_info = form_data.get("EncryptInfo", "")

    if encrypt_info:
        inner = _aes_decrypt(encrypt_info)
    else:
        inner = {}

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
