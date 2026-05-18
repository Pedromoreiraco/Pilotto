import json
import os
from typing import Optional


_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def _load_json(filename: str) -> dict:
    path = os.path.join(_CONFIG_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_rules: dict = {}
_categories: dict = {}


def _ensure_loaded():
    global _rules, _categories
    if not _rules:
        _rules = _load_json("rules.json")
    if not _categories:
        _categories = _load_json("categories.json")


def categorize(description: str) -> Optional[str]:
    _ensure_loaded()
    desc_lower = description.lower().strip()

    for pattern, category in _rules.items():
        if pattern.lower() in desc_lower:
            return category

    for category, keywords in _categories.items():
        if category == "Outros":
            continue
        for keyword in keywords:
            if keyword.lower() in desc_lower:
                return category

    return None


def get_all_categories() -> list[str]:
    _ensure_loaded()
    return list(_categories.keys())
