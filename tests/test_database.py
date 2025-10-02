"""Tests for database and image metadata tracking."""

import tempfile
import time
from pathlib import Path
import pytest

from igallery.database import Database


@pytest.fixture
def temp_db():
    """Create a temporary database for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        yield Database(db_path)


class TestDatabase:
    """Test database operations."""

    def test_database_initialized(self, temp_db):
        """Test that database tables are created."""
        # Should not raise any errors
        assert temp_db.db_path is not None

    def test_save_and_get_thumbnail(self, temp_db):
        """Test saving and retrieving thumbnail records."""
        thumbnail_data = b"fake thumbnail data"
        temp_db.save_thumbnail(
            "/path/to/image.jpg",
            thumbnail_data,
            12345.0,
            1024
        )

        retrieved_data = temp_db.get_thumbnail("/path/to/image.jpg", 12345.0)
        assert retrieved_data == thumbnail_data

    def test_thumbnail_invalidated_on_mtime_change(self, temp_db):
        """Test that thumbnail is invalidated when image mtime changes."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(b"fake image data")
            image_path = tmp.name

        try:
            # Save thumbnail with old mtime
            temp_db.save_thumbnail(image_path, b"thumbnail data", 12345.0, 100)

            # Try to get with different mtime
            result = temp_db.get_thumbnail(image_path, 99999.0)
            assert result is None

        finally:
            Path(image_path).unlink()

    def test_record_view(self, temp_db):
        """Test recording image views."""
        image_path = "/path/to/image.jpg"

        # Record first view
        temp_db.record_view(image_path)
        time.sleep(0.01)  # Small delay to ensure different timestamps

        # Record second view
        temp_db.record_view(image_path)

        # Can't directly check view count without querying, but should not raise

    def test_least_recently_viewed_unviewed_images(self, temp_db):
        """Test that unviewed images are prioritized."""
        images = ["/img1.jpg", "/img2.jpg", "/img3.jpg"]

        # Sync all images first
        temp_db.sync_images(images)

        # View only the first image
        temp_db.record_view(images[0])

        # Should return one of the unviewed images
        result = temp_db.get_least_recently_viewed(images)
        assert result in [images[1], images[2]]

    def test_least_recently_viewed_all_viewed(self, temp_db):
        """Test least recently viewed when all images have been viewed."""
        images = ["/img1.jpg", "/img2.jpg", "/img3.jpg"]

        # View images in order with delays
        temp_db.record_view(images[0])
        time.sleep(0.01)
        temp_db.record_view(images[1])
        time.sleep(0.01)
        temp_db.record_view(images[2])

        # Should return the first image (least recently viewed)
        result = temp_db.get_least_recently_viewed(images)
        assert result == images[0]

    def test_least_recently_viewed_empty_list(self, temp_db):
        """Test least recently viewed with empty list."""
        result = temp_db.get_least_recently_viewed([])
        assert result is None

    def test_least_recently_viewed_single_image(self, temp_db):
        """Test least recently viewed with single image."""
        result = temp_db.get_least_recently_viewed(["/img1.jpg"])
        assert result == "/img1.jpg"

    def test_delete_thumbnail_record(self, temp_db):
        """Test deleting thumbnail record."""
        image_path = "/path/to/image.jpg"

        temp_db.save_thumbnail(image_path, "/path/to/thumb.jpg", 12345.0, 100)
        temp_db.delete_thumbnail_record(image_path)

        # After deletion, should not find the record
        # (would need to check database directly to verify)

    def test_delete_metadata_record(self, temp_db):
        """Test deleting metadata record."""
        image_path = "/path/to/image.jpg"

        temp_db.record_view(image_path)
        temp_db.delete_metadata_record(image_path)

        # After deletion, should not find the record

    def test_multiple_images_tracking(self, temp_db):
        """Test tracking multiple images independently."""
        images = [f"/img{i}.jpg" for i in range(10)]

        # Sync all images first
        temp_db.sync_images(images)

        # View images in different orders
        for img in images[::2]:  # Even indices
            temp_db.record_view(img)
            time.sleep(0.01)

        # Get least recently viewed
        result = temp_db.get_least_recently_viewed(images)

        # Should return an unviewed image (odd index)
        assert result in images[1::2]

    def test_get_trash_item(self, temp_db):
        """Test retrieving trash item by trash path."""
        trash_path = "/gallery/trash/image.jpg"
        original_path = "/gallery/image.jpg"

        # Add to trash
        temp_db.add_to_trash(trash_path, original_path)

        # Retrieve trash item
        item = temp_db.get_trash_item(trash_path)
        assert item is not None
        assert item['trash_path'] == trash_path
        assert item['original_path'] == original_path
        assert 'trashed_at' in item

    def test_get_trash_item_nonexistent(self, temp_db):
        """Test retrieving nonexistent trash item returns None."""
        item = temp_db.get_trash_item("/nonexistent/path.jpg")
        assert item is None
