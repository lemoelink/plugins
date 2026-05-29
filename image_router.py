import re
from modules.logger import app_logger

_EXPERT_LABEL = "image-expert"
_LABEL_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

_MAX_MESSAGES = 10
_MAX_PARTS_PER_MSG = 20
_WARN_B64_BYTES = 524288

_DATA_URI_RE = re.compile(
    r'^data:image/[a-zA-Z0-9.+\-]{1,32};base64,[A-Za-z0-9+/=]+$'
)
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _validate_label(label: str) -> str:
    if not _LABEL_RE.match(label):
        raise ValueError(f"Expert label contains invalid characters: {label!r}")
    return label


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
        if not _DATA_URI_RE.match(url_value):
            app_logger.warning("image_router: data-URI does not match expected image/base64 format, skipping.")
            return False
        b64_part = url_value.split(",", 1)[-1]
        if len(b64_part) > _WARN_B64_BYTES:
            app_logger.warning(
                f"image_router: base64 payload is {len(b64_part)} bytes "
                f"(threshold {_WARN_B64_BYTES}). This may overload the vision model."
            )
        return True

    if url_value.startswith(_ALLOWED_URL_SCHEMES):
        app_logger.warning(
            f"image_router: external image URL detected ({url_value[:80]}). "
            "Ensure the vision model does not resolve external URLs without authorization."
        )
        return True

    app_logger.warning(f"image_router: image URL has unrecognized scheme, skipping: {url_value[:80]!r}")
    return False


def override_route(messages: list) -> str:
    if not isinstance(messages, list):
        return None

    label = _validate_label(_EXPERT_LABEL)

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
                app_logger.info(f"image_router: image detected, forcing route to '{label}'.")
                return label

    return None
