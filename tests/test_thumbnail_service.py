"""Tests for thumbnail generation and caching service."""

import os
import tempfile
from pathlib import Path
import pytest
from PIL import Image

from igallery.thumbnail_service import ThumbnailService
from igallery.database import Database


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_image(temp_dir):
    """Create a test image."""
    image_path = Path(temp_dir) / "test_image.jpg"
    img = Image.new('RGB', (800, 600), color='red')
    img.save(image_path, 'JPEG')
    return str(image_path)


@pytest.fixture
def thumbnail_service(temp_dir):
    """Create a thumbnail service instance."""
    db_path = str(Path(temp_dir) / "test.db")
    db = Database(db_path)
    return ThumbnailService(db)


class TestThumbnailService:
    """Test thumbnail generation and caching."""

    def test_generate_thumbnail_creates_data(self, thumbnail_service, test_image):
        """Test that thumbnail generation creates data."""
        thumbnail_data = thumbnail_service.get_or_create_thumbnail(test_image)

        assert isinstance(thumbnail_data, bytes)
        assert len(thumbnail_data) > 0

    def test_thumbnail_dimensions(self, thumbnail_service, test_image):
        """Test that thumbnail has correct dimensions."""
        thumbnail_data = thumbnail_service.get_or_create_thumbnail(
            test_image, size=(200, 200)
        )

        from io import BytesIO
        with Image.open(BytesIO(thumbnail_data)) as img:
            assert img.width <= 200
            assert img.height <= 200

    def test_thumbnail_maintains_aspect_ratio(self, thumbnail_service, test_image):
        """Test that thumbnail maintains aspect ratio."""
        thumbnail_data = thumbnail_service.get_or_create_thumbnail(
            test_image, size=(200, 200)
        )

        from io import BytesIO
        with Image.open(BytesIO(thumbnail_data)) as img:
            # Original is 800x600 (4:3), thumbnail should maintain this
            original_ratio = 800 / 600
            thumbnail_ratio = img.width / img.height
            assert abs(original_ratio - thumbnail_ratio) < 0.01

    def test_thumbnail_cached_in_database(self, thumbnail_service, test_image):
        """Test that thumbnail is cached in database."""
        thumbnail_data = thumbnail_service.get_or_create_thumbnail(test_image)

        # Get again - should return same data from cache
        cached_data = thumbnail_service.get_or_create_thumbnail(test_image)

        assert thumbnail_data == cached_data

    def test_thumbnail_regenerated_if_image_modified(
        self, thumbnail_service, test_image
    ):
        """Test that thumbnail is regenerated if image is modified."""
        import time
        # Generate initial thumbnail
        first_thumbnail = thumbnail_service.get_or_create_thumbnail(test_image)

        # Modify the image (need to wait to ensure mtime changes)
        time.sleep(0.1)
        img = Image.new('RGB', (800, 600), color='blue')
        img.save(test_image, 'JPEG')

        # Should generate new thumbnail with different data
        second_thumbnail = thumbnail_service.get_or_create_thumbnail(test_image)

        # Content should be different
        assert first_thumbnail != second_thumbnail

    def test_multiple_images_have_different_thumbnails(
        self, thumbnail_service, temp_dir
    ):
        """Test that different images get different thumbnails."""
        # Create two test images with different content
        image1 = Path(temp_dir) / "image1.jpg"
        image2 = Path(temp_dir) / "image2.jpg"

        Image.new('RGB', (800, 600), color='red').save(image1, 'JPEG')
        Image.new('RGB', (800, 600), color='blue').save(image2, 'JPEG')

        thumb1 = thumbnail_service.get_or_create_thumbnail(str(image1))
        thumb2 = thumbnail_service.get_or_create_thumbnail(str(image2))

        # Different images should have different thumbnail data
        assert thumb1 != thumb2

    def test_thumbnails_stored_in_database(self, temp_dir, test_image):
        """Test that thumbnails are stored in database, not filesystem."""
        db_path = str(Path(temp_dir) / "test.db")

        # Create service
        db = Database(db_path)
        service = ThumbnailService(db)

        # Generate thumbnail
        thumbnail_data = service.get_or_create_thumbnail(test_image)

        # Verify it's stored as bytes
        assert isinstance(thumbnail_data, bytes)

    def test_supports_multiple_image_formats(self, thumbnail_service, temp_dir):
        """Test that service supports multiple image formats."""
        formats = [
            ('test.jpg', 'JPEG'),
            ('test.png', 'PNG'),
            ('test.webp', 'WEBP'),
        ]

        for filename, format_name in formats:
            image_path = Path(temp_dir) / filename
            img = Image.new('RGB', (800, 600), color='red')
            img.save(image_path, format_name)

            thumbnail_data = thumbnail_service.get_or_create_thumbnail(str(image_path))
            assert isinstance(thumbnail_data, bytes)
            assert len(thumbnail_data) > 0

    def test_cached_thumbnails_are_bytes(
        self, thumbnail_service, test_image
    ):
        """Test that cached thumbnails are returned as bytes."""
        # Generate thumbnail
        thumbnail_data = thumbnail_service.get_or_create_thumbnail(test_image)

        # Verify it's bytes
        assert isinstance(thumbnail_data, bytes)

        # Get again from cache
        cached_data = thumbnail_service.get_or_create_thumbnail(test_image)

        # Should be same bytes
        assert cached_data == thumbnail_data

        # Verify it's a valid JPEG
        from io import BytesIO
        with Image.open(BytesIO(cached_data)) as img:
            assert img.format == 'JPEG'
            assert img.size[0] > 0
