"""
Firebase Cloud Messaging — server-side push notification sender.
"""

import logging
import json
import base64
import os
import tempfile
from app.database import fetch
from app.config import settings

logger = logging.getLogger(__name__)

_firebase_initialized = False


def _init_firebase():
    """Initialize Firebase Admin SDK."""
    global _firebase_initialized
    if _firebase_initialized:
        return True

    if not settings.FIREBASE_CREDENTIALS:
        logger.warning("FIREBASE_CREDENTIALS not set — push notifications disabled")
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials

        # Decode base64 credentials
        creds_json = base64.b64decode(settings.FIREBASE_CREDENTIALS).decode("utf-8")
        creds_dict = json.loads(creds_json)

        # Write to temp file (Firebase SDK needs a file)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(creds_dict, f)
            creds_path = f.name

        cred = credentials.Certificate(creds_path)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True

        # Clean up temp file
        os.unlink(creds_path)

        logger.info("Firebase Admin SDK initialized")
        return True

    except Exception as e:
        logger.error(f"Firebase initialization failed: {e}")
        return False


async def send_push_notification(title: str, body: str, data: dict = None):
    """Send push notification to all registered devices."""
    if not _init_firebase():
        return 0

    try:
        from firebase_admin import messaging

        # Get all FCM tokens
        tokens = await fetch("SELECT fcm_token FROM fcm_tokens")

        if not tokens:
            logger.info("No registered devices for push notifications")
            return 0

        sent = 0
        for token_row in tokens:
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=body,
                    ),
                    data=data or {},
                    token=token_row["fcm_token"],
                    android=messaging.AndroidConfig(
                        priority="high",
                        notification=messaging.AndroidNotification(
                            channel_id="stock_alerts",
                            icon="ic_notification",
                            color="#00E676",
                        ),
                    ),
                )
                messaging.send(message)
                sent += 1
            except Exception as e:
                logger.debug(f"Failed to send to token: {e}")

        logger.info(f"Push notifications sent: {sent}/{len(tokens)}")
        return sent

    except Exception as e:
        logger.error(f"Push notification error: {e}")
        return 0


async def send_dividend_alerts():
    """Send push alerts for dividends with ex-date tomorrow."""
    from app.database import fetch, execute

    dividends = await fetch(
        """
        SELECT d.symbol, d.company_name, d.amount, d.ex_date,
               s.current_price, s.market
        FROM dividends d
        LEFT JOIN stocks s ON d.stock_id = s.id
        WHERE d.ex_date = CURRENT_DATE + INTERVAL '1 day'
          AND d.notified = FALSE
        """
    )

    for div in dividends:
        currency = "₹" if div.get("market") == "IN" else "$"
        amount_str = f"{currency}{div['amount']}" if div.get("amount") else "TBD"

        title = f"💰 {div['symbol']} Ex-Dividend Tomorrow"
        body = f"{div.get('company_name', div['symbol'])} — {amount_str}/share"

        await send_push_notification(
            title=title,
            body=body,
            data={
                "type": "dividend",
                "symbol": div["symbol"],
                "amount": str(div.get("amount", "")),
            },
        )

        # Mark as notified
        await execute(
            "UPDATE dividends SET notified = TRUE WHERE symbol = $1 AND ex_date = $2",
            div["symbol"],
            div["ex_date"],
        )

    if dividends:
        logger.info(f"Sent {len(dividends)} dividend alerts")


async def send_ipo_alerts():
    """Send push alerts for IPOs opening tomorrow."""
    from app.database import fetch, execute

    ipos = await fetch(
        """
        SELECT company_name, market, price_band_low, price_band_high,
               lot_size, open_date
        FROM ipos
        WHERE open_date = CURRENT_DATE + INTERVAL '1 day'
          AND notified = FALSE
        """
    )

    for ipo in ipos:
        currency = "₹" if ipo.get("market") == "IN" else "$"
        price_str = ""
        if ipo.get("price_band_low") and ipo.get("price_band_high"):
            price_str = f" — {currency}{ipo['price_band_low']}-{currency}{ipo['price_band_high']}"

        title = f"🚀 {ipo['company_name']} IPO Opens Tomorrow"
        body = f"{ipo['company_name']}{price_str}"

        if ipo.get("lot_size"):
            body += f" | Lot: {ipo['lot_size']}"

        await send_push_notification(
            title=title,
            body=body,
            data={
                "type": "ipo",
                "company": ipo["company_name"],
                "market": ipo.get("market", ""),
            },
        )

        # Mark as notified
        await execute(
            "UPDATE ipos SET notified = TRUE WHERE company_name = $1 AND open_date = $2",
            ipo["company_name"],
            ipo["open_date"],
        )

    if ipos:
        logger.info(f"Sent {len(ipos)} IPO alerts")
