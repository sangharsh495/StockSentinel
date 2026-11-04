"""
Notifications API — register FCM tokens for push notifications.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.api.watchlist import _check_device
from app.database import execute

router = APIRouter()


class DeviceRegistration(BaseModel):
    device_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{8,100}$")
    # Firebase tokens are ~160-250 URL-safe characters; nothing else is stored.
    fcm_token: str = Field(..., min_length=20, max_length=4096, pattern=r"^[A-Za-z0-9_:\-]+$")
    platform: Literal["android"] = "android"


@router.post("/register-device")
async def register_device(device: DeviceRegistration):
    """Register or update a device's FCM token."""
    await execute(
        """
        INSERT INTO fcm_tokens (device_id, fcm_token, platform, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (device_id)
        DO UPDATE SET fcm_token = $2, platform = $3, updated_at = NOW()
        """,
        device.device_id,
        device.fcm_token,
        device.platform,
    )

    return {"status": "registered", "device_id": device.device_id}


@router.delete("/unregister-device/{device_id}")
async def unregister_device(device_id: str):
    """Remove a device's FCM token."""
    _check_device(device_id)
    await execute("DELETE FROM fcm_tokens WHERE device_id = $1", device_id)
    return {"status": "unregistered", "device_id": device_id}
