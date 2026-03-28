"""
Utility functions for Krishi Saarthi agents.
"""
import math
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def load_json(filename: str) -> list:
    """Load a JSON file from the data directory."""
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


def euclidean_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate Euclidean distance between two lat/lng points.
    Returns approximate distance in km (mock, not geodesic).
    """
    return math.sqrt((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) * 111  # 1 degree ≈ 111km


def normalize_freshness(freshness: int) -> str:
    """Convert numeric freshness (1-5) to human-readable string."""
    labels = {1: "Very Old", 2: "Old", 3: "Average", 4: "Fresh", 5: "Very Fresh"}
    return labels.get(freshness, "Unknown")


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