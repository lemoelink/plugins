# LEMoE Plugins

Community and official plugins for [LEMoE](https://github.com/lemoelink/LeMoE) — Light Easy Mix Of Experts.

## What is a plugin

A plugin is a single Python file placed in the `plugins/` directory of your LEMoE installation. LEMoE loads it automatically at startup with no configuration required.

Plugins hook into the request lifecycle at three points:

| Hook | Signature | When it runs |
|---|---|---|
| `override_route` | `(messages: list) -> str \| None` | Before semantic routing. Return an expert label to force a route, or `None` to let the router decide. |
| `before_routing` | `(prompt: str) -> str` | After override check, before the embedding model runs. Modify or filter the prompt. |
| `after_generation` | `(response: str) -> str` | After the expert generates a response, before it is returned to the client. |

## Available plugins

| Plugin | Hook | Description |
|---|---|---|
| [image_router.py](./image_router.py) | `override_route` | Routes multimodal requests containing images to a configured vision expert (LLaVA, GPT-4o, etc.). |

## Installation

1. Copy the plugin file into the `plugins/` directory of your LEMoE installation.
2. Restart the server. LEMoE will load it automatically.

Plugin filenames must contain only letters, numbers, hyphens and underscores (`^[a-zA-Z0-9_-]+$`).

## Documentation

- [Plugin system documentation (EN)](https://lemoe.lemoelink.com/en/avanzado/plugins)
- [Plugin system documentation (ES)](https://lemoe.lemoelink.com/avanzado/plugins)
- [image_router plugin (EN)](https://lemoe.lemoelink.com/en/avanzado/plugin-image-router)
- [image_router plugin (ES)](https://lemoe.lemoelink.com/avanzado/plugin-image-router)
