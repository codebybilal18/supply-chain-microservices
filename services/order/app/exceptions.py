"""Order Service domain exceptions."""

from fastapi import HTTPException, status


class OrderNotFoundError(HTTPException):
    def __init__(self, order_id: int) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order {order_id} not found.")


class InvalidOrderStateError(HTTPException):
    def __init__(self, order_id: int, current: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {action} order {order_id} in state '{current}'.",
        )


class StockValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class InventoryServiceError(HTTPException):
    def __init__(self, detail: str = "Inventory service unavailable.") -> None:
        super().__init__(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
