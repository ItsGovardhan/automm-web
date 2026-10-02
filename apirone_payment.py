"""
apirone_payment.py — Apirone LTC helpers (address, deposit check, payout)

.env:
    APIRONE_ACCOUNT=apr-xxxxxxxxxxxxxxxx
    APIRONE_TRANSFER_KEY=xxxxxxxxxxxxxxxx     (payout / refund ke liye)
"""

import os
import io
import asyncio
from decimal import Decimal, ROUND_UP

import aiohttp
import qrcode
from dotenv import load_dotenv

load_dotenv()

APIRONE_ACCOUNT      = os.getenv("APIRONE_ACCOUNT")
APIRONE_TRANSFER_KEY = os.getenv("APIRONE_TRANSFER_KEY")
APIRONE_BASE         = "https://apirone.com/api/v2"
LITOSHI              = Decimal("100000000")   # 1 LTC = 100,000,000 litoshi
POLL_SECONDS         = 30


class ApironeRejected(RuntimeError):
    """Apirone ne request clearly reject ki (4xx). Paisa nahi gaya, retry safe hai."""


# ── helpers ────────────────────────────────────────────────
def ltc_to_litoshi(ltc: Decimal) -> int:
    return int((ltc * LITOSHI).quantize(Decimal("1")))


def litoshi_to_ltc(litoshi: int) -> Decimal:
    return (Decimal(str(litoshi)) / LITOSHI).quantize(Decimal("0.00000001"))


async def ltc_price_usd() -> float:
    url = "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            return float((await r.json())["litecoin"]["usd"])


def usd_to_ltc(usd, price) -> Decimal:
    """USD -> LTC, round UP taaki kam na pade."""
    return (Decimal(str(usd)) / Decimal(str(price))).quantize(
        Decimal("0.00000001"), rounding=ROUND_UP
    )


def valid_ltc_addr(addr: str) -> bool:
    if not addr:
        return False
    if addr.startswith(("L", "M")) and 26 <= len(addr) <= 34:
        return True
    if addr.startswith("ltc1") and len(addr) >= 26:
        return True
    return False


def make_qr(address: str, amount: Decimal) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(f"litecoin:{address}?amount={amount}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf.read()


# ── Apirone API ────────────────────────────────────────────
async def apirone_generate_address() -> str:
    """Naya unique LTC deposit address."""
    url = f"{APIRONE_BASE}/accounts/{APIRONE_ACCOUNT}/addresses"
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json={"currency": "ltc"},
                          timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status not in (200, 201):
                raise RuntimeError(f"Apirone address gen failed {r.status}: {await r.text()}")
            return (await r.json())["address"]


async def apirone_address_balance(address: str, strict: bool = False) -> dict:
    """{'available': confirmed litoshi, 'total': confirmed+unconfirmed litoshi}
    strict=True: API error pe exception uthata hai (zero return nahi karta)."""
    url = f"{APIRONE_BASE}/accounts/{APIRONE_ACCOUNT}/addresses/{address}/balance"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                return await r.json()
            if strict:
                raise RuntimeError(f"Apirone balance check failed {r.status}")
            return {"available": 0, "total": 0}


async def apirone_address_history(address: str) -> list:
    url = f"{APIRONE_BASE}/accounts/{APIRONE_ACCOUNT}/addresses/{address}/history?limit=5&offset=0"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            return (await r.json()).get("txs", []) if r.status == 200 else []


async def get_latest_txid(address: str) -> str:
    try:
        txs = await apirone_address_history(address)
        if txs:
            return txs[0].get("txid", "unknown")
    except Exception:
        pass
    return "unknown"


async def apirone_send_ltc(to_address: str, amount_ltc: Decimal) -> str:
    """LTC bhejta hai (network fee amount me se kat-ti hai). TXID return karta hai.
    4xx -> ApironeRejected (safe to retry). Baaki errors -> RuntimeError/timeout (status unclear)."""
    payload = {
        "currency": "ltc",
        "transfer-key": APIRONE_TRANSFER_KEY,
        "destinations": [{"address": to_address, "amount": str(ltc_to_litoshi(amount_ltc))}],
        "fee": "normal",
        "subtract-fee-from-amount": True,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{APIRONE_BASE}/accounts/{APIRONE_ACCOUNT}/transfer",
                          json=payload, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status not in (200, 201):
                body = await r.text()
                if 400 <= r.status < 500:
                    raise ApironeRejected(f"Apirone send rejected {r.status}: {body}")
                raise RuntimeError(f"Apirone send failed {r.status}: {body}")
            try:
                data = await r.json()
                txs = data.get("txs", [])
                return txs[0] if txs else str(data.get("id", "submitted"))
            except Exception:
                return "submitted"


# ── deposit check ──────────────────────────────────────────
async def check_deposit_once(address: str, expected_ltc: Decimal):
    """Ek baar check karta hai. Return (state, txid, received_ltc)
       state: 'none' | 'pending' | 'underpaid' | 'confirmed'
    API error pe exception uthata hai (caller skip kare, expire na kare)."""
    bal = await apirone_address_balance(address, strict=True)
    total = int(bal.get("total", 0) or 0)
    avail = int(bal.get("available", 0) or 0)
    if avail > 0:
        received = litoshi_to_ltc(avail)
        txid = await get_latest_txid(address)
        if received < expected_ltc - Decimal("0.00001"):
            return ("underpaid", txid, received)
        return ("confirmed", txid, received)
    if total > 0:
        return ("pending", await get_latest_txid(address), litoshi_to_ltc(total))
    return ("none", None, Decimal("0"))


async def watch_deposit(address: str, expected_ltc: Decimal, timeout_min: int = 60):
    """Async generator (bot style): pending / underpaid / confirmed / timeout yield karta hai."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_min * 60
    seen = set()
    while loop.time() < deadline:
        await asyncio.sleep(POLL_SECONDS)
        try:
            state, txid, received = await check_deposit_once(address, expected_ltc)
        except Exception:
            continue
        key = f"{state}_{received}"
        if state == "none" or key in seen:
            continue
        seen.add(key)
        yield (state, txid, received)
        if state == "confirmed":
            return
    yield ("timeout", None, Decimal("0"))
