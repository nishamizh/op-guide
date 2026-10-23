class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class LiveAdapterNotConfigured(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("live_adapter_unavailable", message, status_code=409)
