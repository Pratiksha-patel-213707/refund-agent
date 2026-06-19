from app.order_ids import normalize_order_mentions
from app.tools import get_order_details


def test_normalizes_four_digit_followup():
    assert "ORD-2024-1188" in normalize_order_mentions("1188")


def test_normalizes_spoken_digits():
    assert "ORD-2024-5544" in normalize_order_mentions("order five five four four")
    assert "ORD-2024-5544" in normalize_order_mentions("order double five double four")


def test_normalizes_full_spoken_year():
    assert "ORD-2024-8821" in normalize_order_mentions(
        "order twenty twenty four eight eight two one"
    )


def test_lookup_accepts_unique_suffix():
    assert get_order_details("1188")["order_id"] == "ORD-2024-1188"
