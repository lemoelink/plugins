import os
from modules.logger import app_logger
from modules.config_manager import ConfigManager

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
        # Extraer campos de perfil
        name = profile.get("name", "").strip()
        preferences = profile.get("preferences", "").strip()
        custom_instructions = profile.get("custom_instructions", "").strip()

        # Construir bloque de contexto de usuario
        context_parts = ["System Context (User Profile):"]
        if name:
            context_parts.append(f"- User Name: {name}")
        if preferences:
            context_parts.append(f"- User Preferences: {preferences}")
        if custom_instructions:
            context_parts.append(f"- Custom Instructions: {custom_instructions}")

        if len(context_parts) > 1:
            user_context = "\n".join(context_parts)

            system_message = {
                "role": "system",
                "content": user_context
            }

            # Insertar al inicio de la lista conversacional
            messages.insert(0, system_message)
            app_logger.info(f"user_profile: Inyectadas preferencias de usuario ({name if name else 'Anónimo'}) en la peticion.")
    except Exception as e:
        app_logger.error(f"user_profile: Error al inyectar perfil de usuario: {e}")

    # Retornamos None para que el router de expertos de LEMoE elija el modelo adecuado de forma habitual
    return None
