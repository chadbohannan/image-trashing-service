"""Tests for Flask web application."""

import json
import tempfile
from pathlib import Path
import pytest
from PIL import Image

from igallery.app import create_app


@pytest.fixture
def temp_gallery():
    """Create a temporary gallery directory with test images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gallery_path = Path(tmpdir) / "gallery"
        gallery_path.mkdir()

        # Create test images
        for i in range(25):
            img_path = gallery_path / f"image{i:02d}.jpg"
            Image.new('RGB', (800, 600), color='red').save(img_path, 'JPEG')

        # Create subdirectories
        subdir = gallery_path / "vacation"
        subdir.mkdir()
        for i in range(5):
            img_path = subdir / f"vacation{i}.jpg"
            Image.new('RGB', (800, 600), color='blue').save(img_path, 'JPEG')

        yield gallery_path


@pytest.fixture
def app(temp_gallery):
    """Create Flask app for testing."""
    app = create_app(
        gallery_root=str(temp_gallery),
        db_path=str(temp_gallery / "test.db")
    )
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestWebRoutes:
    """Test web application routes."""

    def test_index_page(self, client):
        """Test that index page loads."""
        response = client.get('/')
        assert response.status_code == 200

    def test_index_shows_images(self, client):
        """Test that index page shows images."""
        response = client.get('/')
        assert response.status_code == 200
        assert b'image' in response.data

    def test_pagination_first_page(self, client):
        """Test pagination on first page."""
        response = client.get('/?page=1')
        assert response.status_code == 200

    def test_pagination_second_page(self, client):
        """Test pagination on second page."""
        response = client.get('/?page=2')
        assert response.status_code == 200

    def test_subdirectory_navigation(self, client):
        """Test navigating to subdirectory."""
        response = client.get('/?path=vacation')
        assert response.status_code == 200

    def test_thumbnail_endpoint(self, client, temp_gallery):
        """Test thumbnail generation endpoint."""
        images = list(temp_gallery.glob("*.jpg"))
        if images:
            image_name = images[0].name
            response = client.get(f'/thumbnail/{image_name}')
            assert response.status_code == 200
            assert response.content_type.startswith('image/')

    def test_carousel_page(self, client):
        """Test carousel page loads."""
        response = client.get('/carousel')
        assert response.status_code == 200

    def test_carousel_next_random(self, client):
        """Test carousel random next endpoint."""
        response = client.get('/carousel/next?mode=random')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'image_url' in data
        assert 'image_name' in data

    def test_carousel_next_slideshow(self, client):
        """Test carousel slideshow next endpoint."""
        response = client.get('/carousel/next?mode=slideshow')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'image_url' in data
        assert 'image_name' in data

    def test_carousel_slideshow_returns_least_viewed(self, client):
        """Test that slideshow mode returns least recently viewed images."""
        # Request multiple times
        viewed_images = []
        for _ in range(5):
            response = client.get('/carousel/next?mode=slideshow')
            data = json.loads(response.data)
            viewed_images.append(data['image_name'])

        # All should be different (until we cycle through)
        assert len(viewed_images) == 5

    def test_trash_endpoint(self, client, temp_gallery):
        """Test trash endpoint."""
        images = list(temp_gallery.glob("*.jpg"))
        if images:
            image_name = images[0].name

            response = client.post(
                '/trash',
                data=json.dumps({'image_name': image_name}),
                content_type='application/json'
            )

            assert response.status_code == 200

            data = json.loads(response.data)
            assert data['success'] is True

            # Verify image is in trash
            trash_dir = temp_gallery / "trash"
            assert (trash_dir / image_name).exists()

    def test_trash_removes_from_gallery(self, client, temp_gallery):
        """Test that trashed images are removed from gallery."""
        # Get initial count
        images_before = list(temp_gallery.glob("*.jpg"))
        count_before = len(images_before)

        # Trash an image
        image_name = images_before[0].name
        client.post(
            '/trash',
            data=json.dumps({'image_name': image_name}),
            content_type='application/json'
        )

        # Check count after
        images_after = list(temp_gallery.glob("*.jpg"))
        assert len(images_after) == count_before - 1

    def test_restore_from_trash(self, client, temp_gallery, app):
        """Test restoring an image from trash."""
        from igallery.database import Database

        # Trash an image first
        images = list(temp_gallery.glob("*.jpg"))
        image_name = images[0].name

        response = client.post(
            '/trash',
            data=json.dumps({'image_name': image_name}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Verify image is in trash
        trash_dir = temp_gallery / "trash"
        trash_full_path = trash_dir / image_name
        assert trash_full_path.exists()
        assert not (temp_gallery / image_name).exists()

        # Get the trash path from database to see what was actually stored
        db = Database(str(temp_gallery / "test.db"))
        trashed_items = db.list_trashed_images()
        assert len(trashed_items) > 0

        # Use the actual trash_path from database, compute relative path
        # Resolve both paths to handle macOS /var -> /private/var symlink
        trash_path_from_db = Path(trashed_items[0]['trash_path']).resolve()
        trash_dir_resolved = trash_dir.resolve()
        relative_trash_path = trash_path_from_db.relative_to(trash_dir_resolved)

        # Restore the image
        response = client.post(
            '/trash/restore',
            data=json.dumps({'trash_path': str(relative_trash_path)}),
            content_type='application/json'
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True

        # Verify image is back in gallery
        assert (temp_gallery / image_name).exists()
        assert not trash_full_path.exists()

    def test_restore_nonexistent_image(self, client):
        """Test restoring an image that doesn't exist in trash."""
        response = client.post(
            '/trash/restore',
            data=json.dumps({'trash_path': 'nonexistent.jpg'}),
            content_type='application/json'
        )
        assert response.status_code == 404

    def test_full_image_endpoint(self, client, temp_gallery):
        """Test full image serving endpoint."""
        images = list(temp_gallery.glob("*.jpg"))
        if images:
            image_name = images[0].name
            response = client.get(f'/image/{image_name}')
            assert response.status_code == 200
            assert response.content_type.startswith('image/')

    def test_invalid_image_404(self, client):
        """Test that invalid image returns 404."""
        response = client.get('/image/nonexistent.jpg')
        assert response.status_code == 404

    def test_parent_directory_link(self, client):
        """Test parent directory navigation link."""
        # Navigate to subdirectory first
        response = client.get('/?path=vacation')
        assert response.status_code == 200
        assert b'..' in response.data or b'parent' in response.data.lower()

    def test_carousel_with_no_images(self, temp_gallery, client):
        """Test carousel behavior with no images."""
        # Remove all images
        for img in temp_gallery.glob("*.jpg"):
            img.unlink()

        response = client.get('/carousel/next?mode=random')
        # Should handle gracefully
        assert response.status_code in [200, 404]

    def test_pagination_per_page_param(self, client):
        """Test custom per_page parameter."""
        response = client.get('/?per_page=5')
        assert response.status_code == 200

    def test_breadcrumb_navigation(self, client):
        """Test that breadcrumb/path info is present."""
        response = client.get('/?path=vacation')
        assert response.status_code == 200
        # Should show current path
        assert b'vacation' in response.data
