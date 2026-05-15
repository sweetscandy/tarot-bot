import hashlib
import urllib.parse
import uuid
import datetime
import httpx
import os

ECPAY_MERCHANT_ID = os.environ.get("ECPAY_MERCHANT_ID", "3500485")
ECPAY_HASH_KEY = os.environ.get("ECPAY_HASH_KEY")
ECPAY_HASH_IV = os.environ.get("ECPAY_HASH_IV")
ECPAY_BASE_URL = "https://payment.ecpay.com.tw"  # 正式環境

def generate_check_mac_value(params: dict) -> str:
    """產生綠界檢查碼 CheckMacValue"""
    # 1. 按照參數名稱英文字母排序
    sorted_params = sorted(params.items(), key=lambda x: x[0].lower())
    # 2. 組合字串
    param_str = "&".join([f"{k}={v}" for k, v in sorted_params])
    raw_str = f"HashKey={ECPAY_HASH_KEY}&{param_str}&HashIV={ECPAY_HASH_IV}"
    # 3. URL encode（小寫）
    encoded = urllib.parse.quote_plus(raw_str).lower()
    # 4. 特殊字元還原（綠界規定）
    encoded = encoded.replace("%2d", "-").replace("%5f", "_") \
                     .replace("%2e", ".").replace("%21", "!") \
                     .replace("%2a", "*").replace("%28", "(") \
                     .replace("%29", ")")
    # 5. SHA256 雜湊並轉大寫
    check_mac = hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()
    return check_mac


def create_payment(user_id: str, amount: int, order_id: str,
                   product_name: str, confirm_url: str) -> str:
    """
    產生綠界付款表單 HTML（POST 自動跳轉）
    回傳一個 HTML 字串，讓 Flask route 直接 return
    """
    tz = datetime.timezone(datetime.timedelta(hours=8))
    trade_date = datetime.datetime.now(tz).strftime("%Y/%m/%d %H:%M:%S")

    params = {
        "MerchantID": ECPAY_MERCHANT_ID,
        "MerchantTradeNo": order_id[:20],          # 最多20碼
        "MerchantTradeDate": trade_date,
        "PaymentType": "aio",
        "TotalAmount": str(amount),
        "TradeDesc": "星運導航訂閱",               # ✅ 修正：直接傳中文，不預先 quote
        "ItemName": product_name,
        "ReturnURL": confirm_url.replace("/pay/confirm", "/pay/notify"),  # 後端通知
        "OrderResultURL": confirm_url,              # 前端跳轉
        "ChoosePayment": "Credit",
        "EncryptType": "1",
    }
    params["CheckMacValue"] = generate_check_mac_value(params)

    # 產生自動提交的 HTML 表單
    inputs = "\n".join(
        [f'<input type="hidden" name="{k}" value="{v}">' for k, v in params.items()]
    )
    html = f"""
    <html>
    <body onload="document.forms[0].submit()">
      <form method="POST" action="{ECPAY_BASE_URL}/Cashier/AioCheckOut/V5">
        {inputs}
        <p>正在跳轉至綠界付款頁面，請稍候...</p>
      </form>
    </body>
    </html>
    """
    return html, order_id[:20]


def verify_notify(form_data: dict) -> bool:
    """
    驗證綠界後端通知的 CheckMacValue
    form_data 是 request.form 轉成的 dict
    """
    received_mac = form_data.get("CheckMacValue", "")
    params = {k: v for k, v in form_data.items() if k != "CheckMacValue"}
    expected_mac = generate_check_mac_value(params)
    return received_mac.upper() == expected_mac.upper()


def is_payment_success(form_data: dict) -> bool:
    """判斷綠界通知是否為付款成功"""
    return (
        form_data.get("RtnCode") == "1" and
        form_data.get("RtnMsg") in ["交易成功", "Succeeded"]
    )
