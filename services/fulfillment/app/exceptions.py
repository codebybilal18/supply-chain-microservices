"""Fulfillment Service domain exceptions."""

from fastapi import HTTPException, status


class FulfillmentNotFoundError(HTTPException):
    def __init__(self, fulfillment_id: int) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fulfillment {fulfillment_id} not found.",
        )


class InvalidFulfillmentStateError(HTTPException):
    def __init__(self, fulfillment_id: int, current: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {action} fulfillment {fulfillment_id} in state '{current}'.",
        )


class OrderServiceError(HTTPException):
    def __init__(self, detail: str = "Order service unavailable.") -> None:
        super().__init__(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
