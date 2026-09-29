"""Data access. Services call these functions instead of owning stock SQL."""

from .stock import apply_stock_delta

__all__ = ["apply_stock_delta"]
