import re
from modules.logger import app_logger
from modules.config_manager import ConfigManager

# --- Constantes del router ---
_LABEL_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

# Validar el label UNA SOLA VEZ al cargar el módulo (no en cada petición)
def _validate_label(label: str) -> str:
    if not _LABEL_RE.match(label):
        raise ValueError(f"Expert label contains invalid characters: {label!r}")
    return label

_EXPERT_LABEL = _validate_label("image-expert")

# --- Límites de inspección ---
_MAX_MESSAGES = 10
_MAX_PARTS_PER_MSG = 20

# --- Límites de seguridad para payloads de imagen ---
# Límite pre-regex: rechaza la cadena antes de aplicar la regex (previene ReDoS)
_MAX_URL_LEN = 10_000_000  # 10 MB techo absoluto

# Límite para base64 inline: imágenes más grandes se rechazan (configurable en config.json)
# Subido a 2 MB según preferencia del usuario (antes era 512 KB = 524 288 bytes)
_DEFAULT_MAX_B64_BYTES = 2_097_152  # 2 MB

# --- Patrones de validación ---
_DATA_URI_RE = re.compile(
    r'^data:image/[a-zA-Z0-9.+\-]{1,32};base64,[A-Za-z0-9+/=]+$'
)
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _get_config() -> dict:
    """Carga la sección image_router desde ConfigManager."""
    return ConfigManager().get("image_router", {})


def _check_image_part(part: dict) -> bool:
    """Valida si un part del mensaje contiene una imagen aceptable.

    Aplica los siguientes controles de seguridad en orden:
      1. Tipo y estructura correctos.
      2. Límite de longitud pre-regex (evita ReDoS).
      3. Validación de data-URI con regex acotada.
      4. Rechazo de base64 oversized según política configurable.
      5. Bloqueo de URLs externas según política configurable.
    """
    if not isinstance(part, dict):
        return False
    if part.get("type") != "image_url":
        return False

    image_url_field = part.get("image_url")
    if not isinstance(image_url_field, dict):
        app_logger.warning("image_router: image_url field is not a dict, skipping.")
        return False

    url_value = image_url_field.get("url", "")
    if not url_value or not isinstance(url_value, str):
        app_logger.warning("image_router: image_url.url is empty or not a string, skipping.")
        return False

    # ── Rama data-URI ──────────────────────────────────────────────────────────
    if url_value.startswith("data:"):
        # [SEC] Límite pre-regex para evitar ReDoS en payloads maliciosamente largos
        if len(url_value) > _MAX_URL_LEN:
            app_logger.warning(
                f"image_router: data-URI excede el límite máximo de {_MAX_URL_LEN} bytes, rechazado."
            )
            return False

        if not _DATA_URI_RE.match(url_value):
            app_logger.warning(
                "image_router: data-URI no coincide con el formato esperado image/base64, skipping."
            )
            return False

        b64_part = url_value.split(",", 1)[-1]
        cfg = _get_config()
        max_b64 = cfg.get("max_b64_bytes", _DEFAULT_MAX_B64_BYTES)

        if len(b64_part) > max_b64:
            if cfg.get("reject_oversized_b64", True):
                app_logger.warning(
                    f"image_router: payload base64 de {len(b64_part)} bytes supera el límite "
                    f"de {max_b64} bytes. Imagen rechazada por política de seguridad."
                )
                return False
            else:
                app_logger.warning(
                    f"image_router: payload base64 de {len(b64_part)} bytes "
                    f"(límite {max_b64}). Puede sobrecargar el modelo de visión."
                )

        return True

    # ── Rama URL externa ───────────────────────────────────────────────────────
    if url_value.startswith(_ALLOWED_URL_SCHEMES):
        cfg = _get_config()
        if not cfg.get("allow_external_urls", False):
            # [SEC] Bloqueado por defecto — habilitar con allow_external_urls: true en config.json
            app_logger.warning(
                f"image_router: URL externa bloqueada por política de seguridad "
                f"(allow_external_urls=false): {url_value[:80]!r}"
            )
            return False
        app_logger.warning(
            f"image_router: URL de imagen externa aceptada ({url_value[:80]}). "
            "Asegúrate de que el modelo de visión no resuelve URLs externas sin autorización."
        )
        return True

    # ── Esquema desconocido ────────────────────────────────────────────────────
    app_logger.warning(
        f"image_router: URL de imagen con esquema no reconocido, rechazada: {url_value[:80]!r}"
    )
    return False


def override_route(messages: list) -> str | None:
    """
    Hook de LEMoE ejecutado antes del enrutamiento.
    Detecta si algún mensaje reciente contiene una imagen válida y, si es así,
    fuerza el enrutamiento al experto de visión.
    """
    if not isinstance(messages, list):
        return None

    inspection_window = messages[-_MAX_MESSAGES:]

    for msg in inspection_window:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        parts_window = content[:_MAX_PARTS_PER_MSG]
        for part in parts_window:
            if _check_image_part(part):
                app_logger.info(
                    f"image_router: imagen detectada, forzando enrutamiento a '{_EXPERT_LABEL}'."
                )
                return _EXPERT_LABEL

    return None
