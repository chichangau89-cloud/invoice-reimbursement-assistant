import hashlib
import json
import re


KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity(parts: list[object]) -> str:
    return digest(json.dumps(parts, ensure_ascii=False, separators=(",", ":")))


def validate_key(value: str, field_name: str = "identifier") -> str:
    if not KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be 1-64 ASCII letters/digits/_/-")
    return value
