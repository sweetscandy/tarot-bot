import hashlib
import hmac
import base64
import uuid
import time
import httpx
import os
import json

LINEPAY_CHANNEL_ID = os.environ.get("LINEPAY_CHANNEL_ID")
LINEPAY_CHANNEL_SECRET = os.environ.get("LINEPAY_CHANNEL_SECRET")
LINEPAY_BASE_URL = "https://sandbox-api-pay.line.me"  # 沙盒環境

def generate_signature(channel_secret, uri, body, nonce):
    """產生 LINE PAY 請求簽名"""
    text = channel_secret + uri + body + nonce
    signature = hmac.new(
        channel_secret.encode("utf-8"),
        text.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode("utf-8")

def get_headers(uri, body):
    """產生請求 Header"""
    nonce = str(uuid.uuid4())
    signature = generate_signature(LINEPAY_CHANNEL_SECRET, uri, body, nonce)
    return {
        "Content-Type": "application/json",
        "X-LINE-ChannelId": LINEPAY_CHANNEL_ID,
        "X-LINE-Authorization-Nonce": nonce,
        "X-LINE-Authorization": signature,
    }

async def create_payment(user_id: str, amount: int, order_id: str, product_name: str, confirm_url: str):
    """建立付款請求，回傳付款網址"""
    uri = "/v3/payments/request"
    payload = {
        "amount": amount,
        "currency": "TWD",
        "orderId": order_id,
        "packages": [
            {
                "id": "pkg_001",
                "amount": amount,
                "products": [
                    {
                        "name": product_name,
                        "quantity": 1,
                        "price": amount
                    }
                ]
            }
        ],
        "redirectUrls": {
            "confirmUrl": confirm_url,
            "cancelUrl": confirm_url.replace("/confirm", "/cancel")
        }
    }
    body = json.dumps(payload, separators=(",", ":"))
    headers = get_headers(uri, body)

    async with httpx.AsyncClient() as client:
        res = await client.post(
            LINEPAY_BASE_URL + uri,
            headers=headers,
            content=body
        )
    data = res.json()
    if data["returnCode"] == "0000":
        payment_url = data["info"]["paymentUrl"]["web"]
        transaction_id = data["info"]["transactionId"]
        return payment_url, transaction_id
    else:
        raise Exception(f"LINE PAY 建立付款失敗: {data}")

async def confirm_payment(transaction_id: str, amount: int):
    """確認付款完成"""
    uri = f"/v3/payments/{transaction_id}/confirm"
    payload = {
        "amount": amount,
        "currency": "TWD"
    }
    body = json.dumps(payload, separators=(",", ":"))
    headers = get_headers(uri, body)

    async with httpx.AsyncClient() as client:
        res = await client.post(
            LINEPAY_BASE_URL + uri,
            headers=headers,
            content=body
        )
    data = res.json()
    if data["returnCode"] == "0000":
        return True
    else:
        raise Exception(f"LINE PAY 確認付款失敗: {data}")
