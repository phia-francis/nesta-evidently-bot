import re


_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_question_text(text: str) -> str:
    return text.replace("•", "").strip().lower()


def slugify(value: str) -> str:
    slug = _SLUG_PATTERN.sub("_", value.strip().lower())
    return slug.strip("_")
