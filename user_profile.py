import re
import os
from modules.logger import app_logger
from modules.config_manager import ConfigManager

# Seguridad: límites máximos por campo del perfil de usuario
_MAX_LENGTHS = {
    "name": 100,
    "preferences": 500,
    "custom_instructions": 1000,
}

# Elimina caracteres de control que podrían inyectar líneas extra en el mensaje de sistema
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0a-\x0d\x0e-\x1f\x7f]')


def _sanitize_field(value: str, key: str) -> str:
    """Elimina caracteres de control y recorta el valor al límite máximo permitido.

    Protege contra prompt injection: un salto de línea embebido en un campo del
    perfil podría añadir instrucciones extra al mensaje de sistema del LLM.
    """
    if not isinstance(value, str):
        return ""
    value = _CONTROL_CHARS_RE.sub("", value).strip()
    limit = _MAX_LENGTHS.get(key, 500)
    if len(value) > limit:
        app_logger.warning(
            f"user_profile: campo '{key}' excede {limit} caracteres y será recortado."
        )
        value = value[:limit]
    return value


def _get_profile() -> dict:
    """Carga los datos del perfil de usuario desde el ConfigManager."""
    return ConfigManager().get("user_profile", {})


def override_route(messages: list) -> str | None:
    """
    Hook de LEMoE ejecutado antes del enrutamiento.
    Inyecta el perfil y preferencias del usuario (nombre, tono preferido, tecnología)
    como un mensaje de sistema inicial para que el experto personalice su respuesta.
    """
    if not isinstance(messages, list):
        return None

    profile = _get_profile()
    if not profile:
        # Si no hay perfil configurado, pasamos en silencio sin alterar la lista
        return None

    try:
        # Extraer y sanitizar campos de perfil
        name = _sanitize_field(profile.get("name", ""), "name")
        preferences = _sanitize_field(profile.get("preferences", ""), "preferences")
        custom_instructions = _sanitize_field(profile.get("custom_instructions", ""), "custom_instructions")

        # Salida temprana si no hay ningún campo con contenido útil
        if not any([name, preferences, custom_instructions]):
            return None

        # Construir bloque de contexto de usuario
        context_parts = ["System Context (User Profile):"]
        if name:
            context_parts.append(f"- User Name: {name}")
        if preferences:
            context_parts.append(f"- User Preferences: {preferences}")
        if custom_instructions:
            context_parts.append(f"- Custom Instructions: {custom_instructions}")

        user_context = "\n".join(context_parts)

        system_message = {
            "role": "system",
            "content": user_context
        }

        # Insertar al inicio de la lista conversacional
        messages.insert(0, system_message)
        display_name = repr(name) if name else "Anónimo"
        app_logger.info(
            f"user_profile: Inyectadas preferencias de usuario ({display_name}) en la peticion."
        )
    except Exception as e:
        app_logger.error(f"user_profile: Error al inyectar perfil de usuario: {e}")

    # Retornamos None para que el router de expertos de LEMoE elija el modelo adecuado de forma habitual
    return None
