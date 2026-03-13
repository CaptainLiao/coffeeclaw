from typing import Any, Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class SuccessResponse(BaseModel, Generic[DataT]):
    status: str = "success"
    data: DataT


class ErrorResponse(BaseModel):
    status: str = "error"
    code: str
    message: str
    details: Any | None = None


class HealthResponse(BaseModel):
    status: str
    db: bool
    redis: bool
