import re
from modules.logger import app_logger
from modules.config_manager import ConfigManager

_LABEL_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

def _validate_label(label: str) -> str:
    if not _LABEL_RE.match(label):
        raise ValueError(f"Expert label contains invalid characters: {label!r}")
    return label

# Validate once at import time, not on every request
_EXPERT_LABEL = _validate_label("image-expert")

_MAX_MESSAGES = 10
_MAX_PARTS_PER_MSG = 20

# Hard cap before running the regex so a huge string can't cause backtracking issues
_MAX_URL_LEN = 10_000_000  # 10 MB

_DEFAULT_MAX_B64_BYTES = 2_097_152  # 2 MB

_DATA_URI_RE = re.compile(
    r'^data:image/[a-zA-Z0-9.+\-]{1,32};base64,[A-Za-z0-9+/=]+$'
)
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _get_config() -> dict:
    return ConfigManager().get("image_router", {})


def _check_image_part(part: dict) -> bool:
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

    if url_value.startswith("data:"):
        if len(url_value) > _MAX_URL_LEN:
            app_logger.warning(
                f"image_router: data-URI excede el límite de {_MAX_URL_LEN} bytes, rechazado."
            )
            return False

        if not _DATA_URI_RE.match(url_value):
            app_logger.warning(
                "image_router: data-URI no coincide con el formato image/base64 esperado, skipping."
            )
            return False

        b64_part = url_value.split(",", 1)[-1]
        cfg = _get_config()
        max_b64 = cfg.get("max_b64_bytes", _DEFAULT_MAX_B64_BYTES)

        if len(b64_part) > max_b64:
            if cfg.get("reject_oversized_b64", True):
                app_logger.warning(
                    f"image_router: payload base64 de {len(b64_part)} bytes supera el límite "
                    f"de {max_b64} bytes, imagen rechazada."
                )
                return False
            else:
                app_logger.warning(
                    f"image_router: payload base64 de {len(b64_part)} bytes "
                    f"(límite {max_b64}). Puede sobrecargar el modelo de visión."
                )

        return True

    if url_value.startswith(_ALLOWED_URL_SCHEMES):
        cfg = _get_config()
        if not cfg.get("allow_external_urls", False):
            app_logger.warning(
                f"image_router: URL externa bloqueada (allow_external_urls=false): {url_value[:80]!r}"
            )
            return False
        app_logger.warning(
            f"image_router: URL de imagen externa aceptada ({url_value[:80]}). "
            "Asegúrate de que el modelo de visión no la resuelve sin autorización."
        )
        return True

    app_logger.warning(
        f"image_router: esquema de URL no reconocido, rechazado: {url_value[:80]!r}"
    )
    return False


def override_route(messages: list) -> str | None:
    if not isinstance(messages, list):
        return None

    for msg in messages[-_MAX_MESSAGES:]:
        if not isinstance(msg, dict):
            continue
        
        # 1. Comprobación de formato Ollama: presencia de campo 'images'
        images_field = msg.get("images")
        if isinstance(images_field, list) and images_field:
            app_logger.info(
                f"image_router: imágenes detectadas en campo 'images' (Ollama), forzando enrutamiento a '{_EXPERT_LABEL}'."
            )
            return _EXPERT_LABEL

        # 2. Comprobación de formato OpenAI: content es una lista con partes de imagen
        content = msg.get("content")
        if isinstance(content, list):
            for part in content[:_MAX_PARTS_PER_MSG]:
                if _check_image_part(part):
                    app_logger.info(
                        f"image_router: imagen detectada en parte de contenido (OpenAI), forzando enrutamiento a '{_EXPERT_LABEL}'."
                    )
                    return _EXPERT_LABEL

    return None
