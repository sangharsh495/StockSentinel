"""
Notifications API — register FCM tokens for push notifications.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from app.database import execute

router = APIRouter()


class DeviceRegistration(BaseModel):
    device_id: str
    fcm_token: str
    platform: str = "android"


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
    await execute("DELETE FROM fcm_tokens WHERE device_id = $1", device_id)
    return {"status": "unregistered", "device_id": device_id}
