import re
import datetime
from modules.logger import app_logger
from modules.config_manager import ConfigManager

DEFAULT_FORMAT = "%A, %B %d, %Y, %H:%M:%S"

_MAX_FORMAT_LEN = 100
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0a-\x1f\x7f]')


def _get_format() -> str:
    cfg = ConfigManager().get("system_time", {})
    fmt = cfg.get("format", DEFAULT_FORMAT)

    if not isinstance(fmt, str) or len(fmt) > _MAX_FORMAT_LEN:
        app_logger.warning(
            f"system_time: formato de fecha inválido o demasiado largo "
            f"({len(fmt) if isinstance(fmt, str) else type(fmt).__name__} chars), "
            f"usando formato por defecto."
        )
        return DEFAULT_FORMAT

    if _CONTROL_CHARS_RE.search(fmt):
        app_logger.warning(
            "system_time: formato de fecha contiene caracteres de control, "
            "usando formato por defecto."
        )
        return DEFAULT_FORMAT

    return fmt


def override_route(messages: list) -> str | None:
    if not isinstance(messages, list):
        return None

    try:
        now = datetime.datetime.now()
        formatted_time = now.strftime(_get_format())

        messages.insert(0, {
            "role": "system",
            "content": f"System Context: The current local date and time is {formatted_time}."
        })
        app_logger.info(f"system_time: inyectada fecha y hora ({formatted_time}) en la peticion.")
    except Exception as e:
        app_logger.error(f"system_time: error al inyectar la fecha en el contexto: {e}")

    return None
