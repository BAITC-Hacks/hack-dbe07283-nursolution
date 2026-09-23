"""Совместимая точка входа: uvicorn api:app."""
from app.api.application import app, create_app

__all__ = ["app", "create_app"]
