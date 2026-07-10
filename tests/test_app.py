"""Smoke tests for the CSS-grid calendar app.

Run with:  uv run pytest
"""

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_root_returns_current_month():
    r = client.get("/")
    assert r.status_code == 200
    assert "cal-grid" in r.text


def test_month_route_renders_may_2026():
    r = client.get("/05/2026")
    assert r.status_code == 200
    assert "May 2026" in r.text
    assert "CW" in r.text  # ISO week bars are drawn


def test_may_2026_marks_holidays():
    # sample_data defines two holidays in May 2026 -> magenta cells.
    r = client.get("/05/2026")
    assert "#e121ff" in r.text


def test_september_is_30_days_with_pad_column():
    r = client.get("/09/2026")
    assert r.status_code == 200
    # 30-day month -> at least one dark padding cell for the missing 31st.
    assert "#605060" in r.text


def test_july_2026_has_all_object_rows():
    r = client.get("/07/2026")
    assert r.status_code == 200
    for name in ["Adam", "Kinga", "Alicja", "Ferie", "Wakacje", "Taxus", "Wiesia"]:
        assert name in r.text


def test_invalid_month_returns_404():
    r = client.get("/13/2026")
    assert r.status_code == 404
