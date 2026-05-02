"""
Domain-specific exception classes.

Raising an HTTPException subclass from the service layer keeps business
logic clean while still producing correct HTTP responses.  All error
detail strings are deliberately generic to avoid information leakage.
"""

from fastapi import HTTPException, status


class ProductNotFoundError(HTTPException):
    """Raised when a product ID or SKU lookup returns no result."""

    def __init__(self, product_id: int) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found.",
        )


class ProductNotFoundBySKUError(HTTPException):
    """Raised when a SKU lookup returns no result."""

    def __init__(self, sku: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with SKU '{sku}' not found.",
        )


class DuplicateSKUError(HTTPException):
    """Raised on INSERT when the SKU already exists (UNIQUE constraint)."""

    def __init__(self, sku: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A product with SKU '{sku}' already exists.",
        )


class InsufficientStockError(HTTPException):
    """Raised when a reservation request exceeds available stock."""

    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Insufficient stock for SKU '{sku}': "
                f"requested {requested}, available {available}."
            ),
        )


class StockReleaseError(HTTPException):
    """Raised when releasing more stock than was reserved."""

    def __init__(self, sku: str, requested: int, reserved: int) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot release {requested} units for SKU '{sku}': "
                f"only {reserved} units are reserved."
            ),
        )
