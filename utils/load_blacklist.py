# utils/load_blacklist.py

import json
import re
from pathlib import Path
from typing import Iterable, List, Pattern

from utils.regex_patterns import BLACKLIST as STATIC_REGEX_PATTERNS

BLACKLIST_FILE = Path("config/blacklist.json")


def _load_dynamic_words() -> List[str]:
    """
    Load dynamic words from JSON. Expected shape:
    {
        "offensive_words": ["word1", "word2", ...]
    }
    """
    if not BLACKLIST_FILE.exists():
        return []

    try:
        with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except json.JSONDecodeError:
        return []

    words = data.get("offensive_words", [])
    # Keep as lowercase unique list
    return sorted(set([str(w).strip().lower() for w in words if str(w).strip()]))


def _save_dynamic_words(words: Iterable[str]) -> None:
    words = sorted(set([str(w).strip().lower()
                   for w in words if str(w).strip()]))
    BLACKLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump({"offensive_words": words}, f, indent=4)


def word_to_flexible_regex(word: str) -> str:
    """
    Convert a plain word into a regex resilient to separators/obfuscation.
    Example: 'fuck' -> f[^\\w]*u[^\\w]*c[^\\w]*k
    """
    letters = [re.escape(ch) for ch in word]
    return r"[^\w]*".join(letters)  # Use raw string to fix the warning


def compile_blacklist_patterns() -> List[Pattern]:
    """
    Compile final pattern list: static regex patterns + dynamic word-regexes.
    """
    dynamic_words = _load_dynamic_words()
    dynamic_patterns = [word_to_flexible_regex(w) for w in dynamic_words]
    all_patterns = STATIC_REGEX_PATTERNS + dynamic_patterns
    # Case-insensitive, dotall to be safe; don't use re.UNICODE for performance
    return [re.compile(pat, re.IGNORECASE | re.DOTALL) for pat in all_patterns]


def save_dynamic_word(word: str) -> List[str]:
    words = _load_dynamic_words()
    w = word.strip().lower()
    if w and w not in words:
        words.append(w)
        _save_dynamic_words(words)
    return words


def remove_dynamic_word(word: str) -> List[str]:
    words = _load_dynamic_words()
    w = word.strip().lower()
    if w in words:
        words.remove(w)
        _save_dynamic_words(words)
    return words


def list_dynamic_words() -> List[str]:
    return _load_dynamic_words()
