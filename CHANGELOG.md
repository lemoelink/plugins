# Changelog

All notable changes to the l3mcore plugin collection are recorded here.
The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## 2026-06-10

### paperless_search.py

**Added**

Initial release of the Paperless-ngx integration plugin. It enables local document searching and RAG injection:
- Uses the local classifier model LEMoEppc to determine if a query has document retrieval intent.
- Uses the local model lemoe-query-distiller to clean and distill search terms from user prompts.
- Queries a local Paperless-ngx instance and automatically injects relevant document texts and metadata as context.
- Implements an exclude_words checklist validation (e.g. "crea", "inventa", "plantilla", "ficticia", "haz") to prevent false positive triggers on creative requests.
- Collaborates with document-expert to ensure secure, offline, and localized document assistance.

---

## 2026-06-03

### image_router.py

**Security**

External image URLs (http and https) are now blocked by default. Previously the plugin accepted them and only left a warning in the log, which meant the vision model could end up receiving URLs pointing to arbitrary third-party servers. The new default is to reject them outright. If you need external URLs to work, set `allow_external_urls: true` in the `image_router` section of your config file.

A hard length cap of 10 MB is now applied to any URL string before the base64 regex runs. This is a preventive measure against crafted inputs that could cause the pattern matcher to spend an unreasonable amount of time backtracking.

Base64 payloads larger than the configured threshold are now rejected by default rather than just logged. The default threshold has been raised from 512 KB to 2 MB, which should comfortably cover most real-world use cases without putting unnecessary pressure on the vision model. Both the threshold and the reject behaviour are configurable via `max_b64_bytes` and `reject_oversized_b64`.

**Changed**

The expert label is now validated once when the module is loaded instead of on every incoming request. It was a constant value and there was no point checking it repeatedly.

---

### user_profile.py

**Security**

The `name`, `preferences` and `custom_instructions` fields pulled from the user profile config are now sanitised before being inserted into the LLM system message. Control characters (newlines, carriage returns and similar) are stripped, and each field has an upper length limit: 100 characters for the name, 500 for preferences and 1000 for custom instructions. Fields that exceed the limit are truncated and a warning is written to the log. Without these checks it was possible to craft a profile entry that would inject additional instructions into the system context, which is a well-known prompt injection vector.

**Changed**

The plugin now exits early if all profile fields are empty after sanitisation, instead of building a context block and then discarding it.

The user name is now logged using its repr form rather than its raw value, which avoids situations where a name containing special characters could produce misleading log entries.

---

### system_time.py

**Security**

The date format string read from config is now validated before being used with `strftime`. Two checks are applied: the string must not exceed 100 characters, and it must not contain control characters. If either check fails the plugin falls back to the built-in default format and logs a warning. This prevents a misconfigured or tampered config file from producing a malformed system message.

---

### system_time.py -- initial release

Injects the current local date and time as a system message at the beginning of every conversation. The format is configurable via the `system_time.format` key in config.

### user_profile.py -- initial release

Injects user profile information (name, preferences, custom instructions) as a system message so experts can adjust their tone and content accordingly. The plugin does nothing if no profile is configured.
