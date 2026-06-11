import hashlib
import base64
import datetime
import os
import time
import uuid
import urllib.parse
import binascii
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# 1. 環境設定 (由於您的商店已通過審核，這裡預設為正式環境)
PAYUNI_ENV = os.environ.get("PAYUNI_ENV", "production").lower()

if PAYUNI_ENV == "sandbox":
    PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID", "您的測試商店代號")
    PAYUNI_HASH_KEY    = os.environ.get("PAYUNI_HASH_KEY", "您的測試HashKey")
    PAYUNI_HASH_IV     = os.environ.get("PAYUNI_HASH_IV",  "您的測試IVKey")
    PAYUNI_API_URL     = "https://sandbox-api.payuni.com.tw/api/upp"
    print("[PayUni] 目前處於 🧪 測試環境 (Sandbox)")
else:
    # 正式環境 (已通過審核：U011578308)
    PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID", "U011578308")
    PAYUNI_HASH_KEY    = os.environ.get("PAYUNI_HASH_KEY", "bweawvqubQiapGNfRTQa1ETvU1SOzDS8")
    PAYUNI_HASH_IV     = os.environ.get("PAYUNI_HASH_IV",  "6DJBnqZ8VP5XW8Z7") # 修正了 IV Key 的打字錯誤
    PAYUNI_API_URL     = "https://api.payuni.com.tw/api/upp"
    print("[PayUni] 目前處於 🔴 正式環境 (Production)")

PAYUNI_AES_TYPE = os.environ.get("PAYUNI_AES_TYPE", "base64").lower()


def _generate_trade_no() -> str:
    ts       = str(int(time.time()))
    rand     = uuid.uuid4().hex[:4].upper()
    trade_no = ts + rand
    print(f"[PayUni] 產生 MerTradeNo: {trade_no} (長度={len(trade_no)})")
    return trade_no


def _aes_encrypt(data: dict) -> str:
    # ⚠️ 關鍵修正 1：將參數依照 Key 進行字典排序
    # ⚠️ 關鍵修正 2：直接使用原始字串，不進行 urllib.parse.quote (Urlencode)
    plain = "&".join(f"{k}={v}" for k, v in sorted(data.items()))
    print(f"[PayUni _aes_encrypt] 排序後明文: {plain}")
    
    key       = PAYUNI_HASH_KEY.encode("utf-8")
    iv        = PAYUNI_HASH_IV.encode("utf-8")
    cipher    = AES.new(key, AES.MODE_CBC, iv)
    
    # 採用 UTF-8 編碼明文並進行 PKCS7 Padding
    encrypted = cipher.encrypt(pad(plain.encode("utf-8"), AES.block_size))

    if PAYUNI_AES_TYPE == "hex":
        result = encrypted.hex()
    else:
        # ⚠️ 關鍵修正 3：使用標準 Base64 編碼，PAYUNi UPP 官方標準規範
        result = base64.b64encode(encrypted).decode("utf-8")

    return result


def _aes_decrypt(encrypt_info: str) -> dict:
    try:
        key      = PAYUNI_HASH_KEY.encode("utf-8")
        iv       = PAYUNI_HASH_IV.encode("utf-8")
        stripped = encrypt_info.strip()

        if PAYUNI_AES_TYPE == "hex":
            try:
                raw_bytes = binascii.unhexlify(stripped)
            except Exception:
                raw_bytes = base64.b64decode(stripped)
        else:
            try:
                # 嘗試標準 Base64 解碼
                raw_bytes = base64.b64decode(stripped)
            except Exception:
                # 容錯：嘗試 URLSafe Base64 解碼
                raw_bytes = base64.urlsafe_b64decode(stripped + "==")

        if len(raw_bytes) % 16 != 0:
            print(f"[PayUni _aes_decrypt] 密文長度 {len(raw_bytes)} 非 16 的倍數，跳過解密")
            return {}

        cipher = AES.new(key, AES.MODE_CBC, iv)
        raw    = unpad(cipher.decrypt(raw_bytes), AES.block_size)

        result = {}
        # 解密後分割參數
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

    # 限制商品名稱長度
    safe_desc    = product_name.replace("・", "-").replace("　", " ")[:50]
    mer_trade_no = _generate_trade_no()

    # ⚠️ 關鍵修正 4：UPP 整合式支付頁的 Version 應為 "1.0"
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
        "Version":     "1.0"
    }

    print(f"[PayUni create_payment] 原始參數: {params}")

    encrypt_info = _aes_encrypt(params)
    hash_info    = _generate_hash_info(encrypt_info)

    # 產生自動提交的 HTML 表單
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>轉接中...</title>
</head>
<body onload="document.forms['payuni_form'].submit();">
  <div style="text-align: center; margin-top: 100px; font-family: sans-serif; color: #6B4FA0;">
    <h2>正在安全導向至 PAYUNi 付款頁面...</h2>
    <p>請稍候，系統正在為您建立安全連線。</p>
    
    <form id="payuni_form" method="POST" action="{PAYUNI_API_URL}">
      <input type="hidden" name="MerID"       value="{PAYUNI_MERCHANT_ID}">
      <input type="hidden" name="Version"     value="1.0">
      <input type="hidden" name="EncryptInfo" value="{encrypt_info}">
      <input type="hidden" name="HashInfo"    value="{hash_info}">
      <noscript>
        <button type="submit" style="padding: 10px 20px; background: #6B4FA0; color: white; border: none; border-radius: 5px;">手動前往付款</button>
      </noscript>
    </form>
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
