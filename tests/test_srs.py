"""Tests for the FSRS Spaced Repetition Agent."""

from datetime import UTC, datetime, timedelta

from src.agents.srs import (
    get_due_items,
    process_review_response,
    schedule_new_items,
)


class TestScheduleNewItems:
    """Test scheduling freshly learned vocabulary."""

    def test_schedules_single_item(self):
        items = [{"word": "mesa", "translation": "table", "context_sentence": "Una mesa para dos"}]
        result = schedule_new_items(items)

        assert len(result) == 1
        assert result[0]["word"] == "mesa"
        assert "next_review" in result[0]
        assert "card_state" in result[0]

    def test_schedules_multiple_items(self):
        items = [
            {"word": "mesa", "translation": "table"},
            {"word": "cuenta", "translation": "bill"},
            {"word": "propina", "translation": "tip"},
        ]
        result = schedule_new_items(items)
        assert len(result) == 3

    def test_empty_input(self):
        result = schedule_new_items([])
        assert result == []


class TestProcessReviewResponse:
    """Test processing user responses to review cards."""

    def test_good_rating_increases_interval(self):
        items = schedule_new_items([{"word": "mesa", "translation": "table"}])
        card_state = items[0]["card_state"]

        # Rate as "Good"
        result = process_review_response(card_state, rating=3)
        assert "next_review" in result
        assert "review_log" in result
        assert result["review_log"]["rating"] == 3

    def test_again_rating_resets(self):
        items = schedule_new_items([{"word": "mesa", "translation": "table"}])
        card_state = items[0]["card_state"]

        # Rate as "Again" (forgot)
        result = process_review_response(card_state, rating=1)
        assert result["review_log"]["rating"] == 1

    def test_easy_rating_longest_interval(self):
        items = schedule_new_items([{"word": "mesa", "translation": "table"}])
        card_state = items[0]["card_state"]

        # Rate as "Easy"
        easy_result = process_review_response(card_state, rating=4)
        good_result = process_review_response(card_state, rating=3)

        # Easy should schedule further out than Good
        easy_next = datetime.fromisoformat(easy_result["next_review"])
        good_next = datetime.fromisoformat(good_result["next_review"])
        assert easy_next >= good_next


class TestGetDueItems:
    """Test retrieving items due for review."""

    def test_returns_overdue_items(self):
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()

        items = [
            {"word": "mesa", "next_review": past},
            {"word": "cuenta", "next_review": future},
        ]

        due = get_due_items(items)
        assert len(due) == 1
        assert due[0]["word"] == "mesa"

    def test_respects_limit(self):
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        items = [{"word": f"word_{i}", "next_review": past} for i in range(20)]

        due = get_due_items(items, limit=5)
        assert len(due) == 5

    def test_empty_when_nothing_due(self):
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        items = [{"word": "mesa", "next_review": future}]

        due = get_due_items(items)
        assert due == []
