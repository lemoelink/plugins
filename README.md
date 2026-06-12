# l3mcore Plugins

Community and official plugins for [l3mcore](https://github.com/lemoelink/l3mcore) — Light Easy Mix Of Experts.

## What is a plugin

A plugin is a single Python file placed in the `plugins/` directory of your l3mcore installation. l3mcore loads it automatically at startup with no configuration required.

Plugins hook into the request lifecycle at four points:

| Hook | Signature | When it runs |
|---|---|---|
| `override_route` | `(messages: list) -> str \| None` | Before semantic routing. Return an expert label to force a route, or `None` to let the router decide. |
| `before_routing` | `(prompt: str) -> str` | After override check, before the embedding model runs. Modify or filter the prompt. |
| `before_expert` | `(messages: list, expert_config: dict) -> None` | After routing, immediately before dispatching to the expert backend. Mutate the message list in-place. |
| `after_generation` | `(response: str) -> str` | After the expert generates a response, before it is returned to the client. |

## Available plugins

| Plugin | Hook | Description |
|---|---|---|
| [system_time.py](./system_time.py) | `override_route` | Injects the current local date and time as a system message at the start of every conversation, so the model is always aware of when the request is happening. |
| [user_profile.py](./user_profile.py) | `override_route` | Injects user profile data (name, preferences, custom instructions) as a system message so experts can personalise their responses accordingly. |
| [image_router.py](./image_router.py) | `override_route` | Detects images in the message history (inline base64 data-URIs or external URLs) and forces routing to a configured vision expert (LLaVA, GPT-4o, etc.). |
| [routing_transparency.py](./routing_transparency.py) | `after_generation` | Appends a small footer to each response showing which expert was used and the router confidence score. Makes the MoE routing visible and trustworthy to end users. |
| [pii_masker.py](./pii_masker.py) | `before_expert` | Detects and masks Personally Identifiable Information (DNI, IBAN, credit cards, emails, phone numbers, IPs, GPS coordinates) before the request reaches an external API backend. Uses regex patterns by default; optionally integrates spaCy NER for person names. |
| [telemetry_dashboard.py](./telemetry_dashboard.py) | `after_generation` | Exposes a real-time web dashboard on port `8081` with per-expert metrics: requests, token usage (input/output), average latency, API cost estimation in USD, and global success rate. Data persists in `logs/telemetry.json` and is exportable as CSV. |

## Plugin details

### system_time

Reads the format string from `config.json` under the `system_time` key. If no format is defined, it falls back to `"%A, %B %d, %Y, %H:%M:%S"`.

```json
{
  "system_time": {
    "format": "%A, %B %d, %Y, %H:%M:%S"
  }
}
```

The format string is validated at runtime: it must be 100 characters or shorter and must not contain control characters. If the value from config fails either check, the default format is used instead and a warning is written to the log.

---

### user_profile

Reads profile data from `config.json` under the `user_profile` key.

```json
{
  "user_profile": {
    "name": "Alice",
    "preferences": "Concise answers, no jargon.",
    "custom_instructions": "Always respond in Spanish."
  }
}
```

Each field is sanitised before being inserted into the system message: control characters are stripped and field lengths are capped (`name` at 100 chars, `preferences` at 500, `custom_instructions` at 1000). If a field exceeds the limit it is truncated and a warning is logged. If all fields are empty after sanitisation, the plugin does nothing.

---

### image_router

Inspects the last 10 messages and up to 20 content parts per message looking for image payloads. Behaviour is controlled through `config.json` under the `image_router` key.

```json
{
  "image_router": {
    "allow_external_urls": false,
    "reject_oversized_b64": true,
    "max_b64_bytes": 2097152
  }
}
```

| Key | Default | Description |
|---|---|---|
| `allow_external_urls` | `false` | When `false`, external `http/https` image URLs are blocked. Set to `true` only if your vision model is known to fetch URLs safely. |
| `reject_oversized_b64` | `true` | When `true`, base64 payloads larger than `max_b64_bytes` are rejected instead of just logged. |
| `max_b64_bytes` | `2097152` | Maximum accepted base64 payload size in bytes (default: 2 MB). |

The plugin also enforces a hard pre-regex length cap of 10 MB on any URL string before pattern matching, which prevents potential ReDoS issues from malformed inputs.

---

### routing_transparency

Appends a small, unobtrusive footer to every model response revealing which expert handled the request and the router confidence.

Example output (with default settings):
```
---
Routed to: **programador** (confidence: 87%)
```

All behaviour is controlled through `config.json` under the `routing_transparency` key:

```json
{
  "routing_transparency": {
    "enabled":     true,
    "show_score":  true,
    "show_method": false,
    "separator":   "---",
    "label":       "Routed to"
  }
}
```

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Master on/off switch. Set to `false` to disable the footer entirely. |
| `show_score` | `true` | Whether to show the confidence percentage next to the expert name. |
| `show_method` | `false` | Reserved for future use (will show embedding vs keyword). |
| `separator` | `"---"` | Separator line printed immediately before the footer. Max 80 chars. |
| `label` | `"Routed to"` | Prefix text displayed before the expert name. Max 60 chars. |

---

### pii_masker

Detects and redacts Personally Identifiable Information from messages before they are sent to external API backends (type `api`). By default runs only for cloud experts to avoid unnecessary processing for local models. Can be forced to run for all experts via `force_enabled`.

```json
{
  "pii_masker": {
    "enabled": true,
    "use_spacy": false,
    "spacy_model": "es_core_news_sm",
    "mask_names": false,
    "force_enabled": false
  }
}
```

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Master on/off switch. |
| `use_spacy` | `false` | Enables spaCy NER for person name and location detection. Requires a spaCy model to be installed. |
| `spacy_model` | `"es_core_news_sm"` | The spaCy model to load when `use_spacy` is `true`. |
| `mask_names` | `false` | When `true` and `use_spacy` is enabled, replaces detected person names with `[PERSON_NAME]` and locations with `[LOCATION]`. |
| `force_enabled` | `false` | When `true`, applies masking even for non-API (local) experts. |

Built-in patterns (no extra dependencies): DNI/NIE, IBAN, credit card numbers, Spanish Social Security numbers, email addresses, Spanish phone numbers, IPv4 addresses, and GPS coordinates.

---

### telemetry_dashboard

Exposes a real-time web dashboard for monitoring expert performance. A lightweight Flask server starts in the background on port `8081` (independent of the main API server).

Dashboard URL: `http://localhost:8081`

Features:
- KPI cards: total requests, total API cost, tokens processed, global success rate.
- Hourly bar chart for the last 24 hours.
- Cost distribution doughnut chart per expert.
- Per-expert table with requests, token counts (input/output), throughput (T/s), average latency, and estimated USD cost.
- CSV export via `GET /api/export`.
- Data persists in `logs/telemetry.json` using atomic writes.

Cost estimation is only calculated for experts of type `api`. The internal price table covers GPT-4o, GPT-4o-mini, GPT-4-turbo, GPT-3.5-turbo, Claude 3.5 Sonnet, Claude 3 Haiku, Gemini 1.5 Pro, Gemini 1.5 Flash, and Gemini 2.0 Flash. The table can be extended by editing the `_COST_PER_1M` dictionary inside the plugin file.

No configuration in `config.json` is required. The dashboard starts automatically when the plugin is loaded.

## Installation

1. Copy the plugin file into the `plugins/` directory of your l3mcore installation.
2. Restart the server. l3mcore will load it automatically.

Plugin filenames must contain only letters, numbers, hyphens and underscores (`^[a-zA-Z0-9_-]+$`).

## Documentation

- [Plugin system documentation](https://docs.lemoe.link/avanzado/plugins)
- [image_router plugin](https://docs.lemoe.link/avanzado/plugin-image-router)
- [routing_transparency plugin](https://docs.lemoe.link/avanzado/plugin-routing-transparency)
- [pii_masker plugin](https://docs.lemoe.link/avanzado/plugin-pii-masker)
