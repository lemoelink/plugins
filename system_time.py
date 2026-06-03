import re
import datetime
import os
from modules.logger import app_logger
from modules.config_manager import ConfigManager

# Formato por defecto para la inyección de la fecha y hora
DEFAULT_FORMAT = "%A, %B %d, %Y, %H:%M:%S"

# Seguridad: límite de longitud y caracteres prohibidos en el formato personalizado
_MAX_FORMAT_LEN = 100
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0a-\x1f\x7f]')  # control excepto \t


def _get_format() -> str:
    """Carga el formato de fecha personalizado desde ConfigManager o usa el por defecto.

    Valida que el formato no supere la longitud máxima permitida y no contenga
    caracteres de control que pudieran malformar el mensaje de sistema del LLM.
    """
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
    """
    Hook de LEMoE ejecutado antes del enrutamiento.
    Inyecta un mensaje del sistema al principio de la conversación conteniendo
    la fecha y hora local del sistema para que el modelo sea consciente del tiempo actual.
    """
    if not isinstance(messages, list):
        return None

    try:
        # Obtener fecha y hora local actual
        now = datetime.datetime.now()
        time_format = _get_format()
        formatted_time = now.strftime(time_format)

        # Crear el mensaje de contexto del sistema
        system_message = {
            "role": "system",
            "content": f"System Context: The current local date and time is {formatted_time}."
        }

        # Insertar al inicio de la lista de mensajes conversacionales
        messages.insert(0, system_message)
        app_logger.info(f"system_time: Inyectada fecha y hora actual del sistema ({formatted_time}) en la peticion.")
    except Exception as e:
        app_logger.error(f"system_time: Error al inyectar la fecha y hora en el contexto: {e}")

    # Retornamos None para no forzar ningún experto y permitir el enrutamiento semántico habitual
    return None
