"""ASGI entry point: ``uvicorn app.api.main:app``. Requires the environment (see config)."""

from app.api.app import create_app_from_settings
from app.core.config import get_settings

app = create_app_from_settings(get_settings())
