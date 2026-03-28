"""Utility functions for Krishi Saarthi agents.

This module centralises access to JSON data and lightweight
domain configuration so that application logic does not
rely on hardcoded constants.
"""
import math
import json
import os
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'config')


def load_json(filename: str) -> list:
    """Load a JSON array from the data directory.

    Returns an empty list when the file does not exist.
    """
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(filename: str, data) -> None:
    """Save data to a JSON file in the data directory."""
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@lru_cache(maxsize=1)
def load_domain_config() -> dict:
    """Load domain configuration from config/domain_config.json.

    This provides known products, unit patterns, freshness
    keywords and SMS command mappings without hardcoding
    them in Python code. If the config file is missing or
    incomplete, sensible defaults are returned.
    """
    path = os.path.join(CONFIG_DIR, 'domain_config.json')
    if not os.path.exists(path):
        return {
            "known_products": [],
            "unit_patterns": [],
            "freshness_keywords": {},
            "sms_commands": {},
        }
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {
        "known_products": data.get("known_products", []),
        "unit_patterns": data.get("unit_patterns", []),
        "freshness_keywords": data.get("freshness_keywords", {}),
        "sms_commands": data.get("sms_commands", {}),
    }


def euclidean_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate Euclidean distance between two lat/lng points.
    Returns approximate distance in km (mock, not geodesic).
    """
    return math.sqrt((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) * 111  # 1 degree ≈ 111km


def normalize_freshness(freshness: int) -> str:
    """Convert numeric freshness (1-5) to human-readable string."""
    labels = {
        1: "Bahut purana",
        2: "Purana",
        3: "Theek-thaak",
        4: "Taaza",
        5: "Bahut taaza",
    }
    return labels.get(freshness, "Pata nahi")


def get_vendor_by_id(vendor_id: int) -> dict:
    """Fetch a vendor record by ID."""
    vendors = load_json('vendors.json')
    for v in vendors:
        if v['id'] == vendor_id:
            return v
    return {}


def get_consumer_by_id(consumer_id: int) -> dict:
    """Fetch a consumer record by ID."""
    consumers = load_json('consumers.json')
    for c in consumers:
        if c['id'] == consumer_id:
            return c
    return {}