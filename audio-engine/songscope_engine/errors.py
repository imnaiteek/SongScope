class EngineError(Exception):
    """An error with a user-presentable message."""

    code = "engine_error"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class DecodeError(EngineError):
    code = "decode_failed"


class UnsupportedMediaError(EngineError):
    code = "unsupported_media"


class DurationLimitError(EngineError):
    code = "duration_limit"


class CancelledError(EngineError):
    code = "cancelled"
