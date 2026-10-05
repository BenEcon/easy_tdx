"""Web API error handling."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from easy_tdx.exceptions import TdxConnectionError


class ApiErrorResponse(BaseModel):
    """标准错误响应格式。"""

    error: str
    detail: str = ""


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器到 FastAPI app。"""

    @app.exception_handler(TdxConnectionError)
    async def tdx_connection_error_handler(
        request: Request, exc: TdxConnectionError
    ) -> JSONResponse:
        del request  # unused but required by FastAPI signature
        return JSONResponse(
            status_code=503,
            content=ApiErrorResponse(error="TDX connection error", detail=str(exc)).model_dump(),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        del request  # unused but required by FastAPI signature
        return JSONResponse(
            status_code=400,
            content=ApiErrorResponse(error="Bad request", detail=str(exc)).model_dump(),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        del request  # unused but required by FastAPI signature
        return JSONResponse(
            status_code=500,
            content=ApiErrorResponse(error="Internal server error", detail=str(exc)).model_dump(),
        )
