import hashlib
import urllib.parse
import uuid
import datetime
import os

PAYUNI_MERCHANT_ID = os.environ.get("PAYUNI_MERCHANT_ID", "U011578308")
PAYUNI_HASH_KEY    = os.environ.get("PAYUNI_HASH_KEY", "bweawvqubQiapGNfRTQa1ETvU1SOzDS8")
PAYUNI_HASH_IV     = os.environ.get("PAYUNI_HASH_IV",  "6DJBnqZ8VP5XW8Z7")

PAYUNI_API_URL = "https://api.payuni.com.tw/api/pay"


def _generate_hash(params: dict) -> str:
    """
    PayUni 簽章規則：
    1. 將所有參數（不含 HashKey/HashIV）按 key 字母排序
    2. 組成 key=value& 字串
    3. 前後加上 HashKey= 與 &HashIV=
    4. SHA256 → 大寫
    """
    sorted_items = sorted(params.items(), key=lambda x: x[0].lower())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    raw = f"HashKey={PAYUNI_HASH_KEY}&{param_str}&HashIV={PAYUNI_HASH_IV}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def create_payment(user_id: str, amount: int, order_id: str,
                   product_name: str, confirm_url: str):
    """
    產生 PayUni 統一金流付款表單 HTML（POST 自動跳轉）
    支援：信用卡、ATM、超商代碼、LINE Pay
    回傳 (html_str, order_id)
    """
    render_url = os.environ.get("RENDER_URL", "https://tarot-bot-qqgg.onrender.com")
    notify_url = f"{render_url}/pay/notify"
    return_url  = confirm_url   # 付款完成後跳回前端

    params = {
        "MerchantNo":    PAYUNI_MERCHANT_ID,
        "RespondType":   "JSON",
        "TimeStamp":     str(int(datetime.datetime.now().timestamp())),
        "MerchantOrderNo": order_id[:30],
        "Amt":           str(amount),
        "ItemDesc":      product_name[:50],
        "NotifyURL":     notify_url,
        "ReturnURL":     return_url,
        "ClientBackURL": return_url,
        "EmailModify":   "0",
    }

    params["CheckCode"] = _generate_hash(params)

    inputs = "\n".join(
        f'<input type="hidden" name="{k}" value="{v}">'
        for k, v in params.items()
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>前往付款...</title>
</head>
<body onload="document.forms[0].submit()" 
      style="font-family:sans-serif;text-align:center;padding:50px;background:#F8F4FF;">
  <form method="POST" action="{PAYUNI_API_URL}">
    {inputs}
  </form>
  <p style="color:#6B4FA0;">⏳ 正在跳轉至付款頁面，請稍候...</p>
</body>
</html>"""

    return html, order_id[:30]


def verify_notify(form_data: dict) -> bool:
    """
    驗證 PayUni 後端通知的 CheckCode
    """
    received = form_data.get("CheckCode", "")
    params = {k: v for k, v in form_data.items() if k != "CheckCode"}
    expected = _generate_hash(params)
    return received.upper() == expected.upper()


def is_payment_success(form_data: dict) -> bool:
    """
    判斷 PayUni 通知是否付款成功
    Status = SUCCESS 且 Amt > 0
    """
    return (
        form_data.get("Status") == "SUCCESS" and
        int(form_data.get("Amt", 0)) > 0
    )


def get_order_id_from_notify(form_data: dict) -> str:
    """從通知取得訂單編號"""
    return form_data.get("MerchantOrderNo", "")
