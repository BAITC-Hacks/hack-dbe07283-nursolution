"""Единый формат ошибок HTTP без отражения тела запроса и секретов."""
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

def error_response(status_code: int, code: str, message: str, *, fields=None, headers=None):
    """Один формат ошибок без отражения тела запроса или текста исключения."""
    return JSONResponse(status_code=status_code, headers=headers, content={
        "error": {"code": code, "message": message, "fields": fields or []}})


def install_error_handlers(application: FastAPI):
    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        messages = {
            "missing": "Обязательное поле не заполнено.",
            "extra_forbidden": "Неизвестное поле запроса.",
            "string_type": "Ожидается строка.",
            "string_too_short": "Строка не должна быть пустой.",
            "string_too_long": "Строка слишком длинная (максимум 200 символов).",
            "string_pattern_mismatch": "Дата должна иметь формат YYYY-MM-DD.",
            "float_type": "Ожидается JSON-число, а не строка или логическое значение.",
            "finite_number": "Число должно быть конечным.",
            "greater_than_equal": "Значение должно быть неотрицательным.",
            "greater_than": "Значение должно быть больше нуля.",
            "json_invalid": "Некорректный JSON.",
        }
        fields = []
        for item in exc.errors():
            location = item["loc"]
            name = ".".join(str(part) for part in location if part != "body") or "body"
            message = ("Несуществующая дата мероприятия." if name == "date" and item["type"] == "value_error"
                       else messages.get(item["type"], "Некорректное значение поля."))
            fields.append({"field": name, "message": message, "type": item["type"]})
        return error_response(422, "validation_error", "Проверьте параметры запроса.", fields=fields)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        messages = {404: "Эндпоинт не найден.", 405: "Метод запроса не поддерживается."}
        return error_response(exc.status_code, "http_error", messages.get(exc.status_code, "Ошибка HTTP-запроса."),
                              headers=exc.headers)

    @application.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logger.error("Ошибка обработки %s %s (%s)", request.method, request.url.path, type(exc).__name__)
        return error_response(500, "internal_error", "Не удалось обработать запрос. Повторите попытку позже.")

