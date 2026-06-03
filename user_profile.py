import re
from modules.logger import app_logger
from modules.config_manager import ConfigManager

# Max lengths per field. Keeps the system message from growing out of control
# and closes the obvious prompt injection via newlines in config values.
_MAX_LENGTHS = {
    "name": 100,
    "preferences": 500,
    "custom_instructions": 1000,
}

_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0a-\x0d\x0e-\x1f\x7f]')


def _sanitize_field(value: str, key: str) -> str:
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
    return ConfigManager().get("user_profile", {})


def override_route(messages: list) -> str | None:
    if not isinstance(messages, list):
        return None

    profile = _get_profile()
    if not profile:
        return None

    try:
        name = _sanitize_field(profile.get("name", ""), "name")
        preferences = _sanitize_field(profile.get("preferences", ""), "preferences")
        custom_instructions = _sanitize_field(profile.get("custom_instructions", ""), "custom_instructions")

        if not any([name, preferences, custom_instructions]):
            return None

        context_parts = ["System Context (User Profile):"]
        if name:
            context_parts.append(f"- User Name: {name}")
        if preferences:
            context_parts.append(f"- User Preferences: {preferences}")
        if custom_instructions:
            context_parts.append(f"- Custom Instructions: {custom_instructions}")

        messages.insert(0, {
            "role": "system",
            "content": "\n".join(context_parts)
        })

        display_name = repr(name) if name else "Anónimo"
        app_logger.info(
            f"user_profile: inyectadas preferencias de usuario ({display_name}) en la peticion."
        )
    except Exception as e:
        app_logger.error(f"user_profile: error al inyectar perfil de usuario: {e}")

    return None
