import datetime
import os
from modules.logger import app_logger
from modules.config_manager import ConfigManager

# Formato por defecto para la inyección de la fecha y hora
DEFAULT_FORMAT = "%A, %B %d, %Y, %H:%M:%S"

def _get_format() -> str:
    """Carga el formato de fecha personalizado desde ConfigManager o usa el por defecto."""
    cfg = ConfigManager().get("system_time", {})
    return cfg.get("format", DEFAULT_FORMAT)

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
