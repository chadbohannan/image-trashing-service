"""Integration tests for the complete iGallery service."""

import tempfile
from pathlib import Path
import pytest
from PIL import Image

from igallery.app import create_app
from igallery.database import Database
from igallery.thumbnail_service import ThumbnailService
from igallery.file_operations import FileOperations


@pytest.fixture
def test_gallery():
    """Create a complete test gallery setup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gallery_path = Path(tmpdir) / "gallery"
        gallery_path.mkdir()

        # Create test images with different formats
        Image.new('RGB', (800, 600), color='red').save(
            gallery_path / "red.jpg", 'JPEG'
        )
        Image.new('RGB', (1024, 768), color='blue').save(
            gallery_path / "blue.png", 'PNG'
        )
        Image.new('RGB', (640, 480), color='green').save(
            gallery_path / "green.webp", 'WEBP'
        )

        # Create nested structure
        vacation_dir = gallery_path / "vacation"
        vacation_dir.mkdir()
        for i in range(3):
            Image.new('RGB', (800, 600), color='yellow').save(
                vacation_dir / f"beach{i}.jpg", 'JPEG'
            )

        work_dir = gallery_path / "work"
        work_dir.mkdir()
        Image.new('RGB', (800, 600), color='gray').save(
            work_dir / "office.jpg", 'JPEG'
        )

        yield {
            'path': gallery_path,
            'db_path': str(gallery_path / 'test.db')
        }


class TestFullIntegration:
    """Test complete workflows through the system."""

    def test_complete_gallery_workflow(self, test_gallery):
        """Test complete workflow: browse, view, trash."""
        gallery_path = test_gallery['path']

        # 1. Initialize services
        db = Database(test_gallery['db_path'])
        thumbnail_service = ThumbnailService(db)
        file_ops = FileOperations(str(gallery_path), gallery_root=str(gallery_path))

        # 2. List images
        images = file_ops.list_images()
        assert len(images) == 3  # red, blue, green

        # 3. Generate thumbnails for all images
        thumbnails = []
        for image in images:
            thumb_data = thumbnail_service.get_or_create_thumbnail(image)
            thumbnails.append(thumb_data)
            assert isinstance(thumb_data, bytes)
            assert len(thumb_data) > 0

        # 4. Record views
        for image in images:
            db.record_view(image)

        # 5. Get least recently viewed
        lrv = db.get_least_recently_viewed(images)
        assert lrv in images

        # 6. Move image to trash
        image_to_trash = images[0]
        trash_path = file_ops.move_to_trash(image_to_trash)

        # Record in database
        db.add_to_trash(trash_path, image_to_trash)

        # 7. Verify image is gone
        remaining = file_ops.list_images()
        assert len(remaining) == 2
        assert image_to_trash not in remaining

        # 8. Verify trash exists and image is there
        trash_dir = gallery_path / "trash"
        assert trash_dir.exists()
        assert Path(trash_path).exists()

        # 9. Verify trash is tracked in database
        trashed = db.list_trashed_images()
        assert len(trashed) == 1
        assert trashed[0]['trash_path'] == trash_path

    def test_web_app_integration(self, test_gallery):
        """Test web application with full gallery."""
        app = create_app(
            gallery_root=str(test_gallery['path']),
            db_path=test_gallery['db_path']
        )
        app.config['TESTING'] = True
        client = app.test_client()

        # 1. Access main page
        response = client.get('/')
        assert response.status_code == 200
        assert b'red.jpg' in response.data

        # 2. Get thumbnail
        response = client.get('/thumbnail/red.jpg')
        assert response.status_code == 200
        assert response.content_type.startswith('image/')

        # 3. Get full image
        response = client.get('/image/red.jpg')
        assert response.status_code == 200

        # 4. Navigate to subdirectory
        response = client.get('/?path=vacation')
        assert response.status_code == 200
        assert b'beach0.jpg' in response.data

        # 5. Test carousel
        response = client.get('/carousel/next?mode=random')
        assert response.status_code == 200

        # 6. Trash an image
        import json
        response = client.post(
            '/trash',
            data=json.dumps({'image_name': 'red.jpg'}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # 7. Verify image is gone
        response = client.get('/')
        assert b'red.jpg' not in response.data

    def test_slideshow_mode_progression(self, test_gallery):
        """Test that slideshow mode progresses through images."""
        app = create_app(
            gallery_root=str(test_gallery['path']),
            db_path=test_gallery['db_path']
        )
        app.config['TESTING'] = True
        client = app.test_client()

        # Request multiple images in slideshow mode
        # Gallery has 7 total images: 3 in root, 3 in vacation/, 1 in work/
        viewed_images = set()
        for _ in range(8):
            response = client.get('/carousel/next?mode=slideshow')
            assert response.status_code == 200

            import json
            data = json.loads(response.data)
            viewed_images.add(data['image_name'])

        # Should have viewed all 7 unique images across all directories
        assert len(viewed_images) == 7

    def test_thumbnail_cache_persistence(self, test_gallery):
        """Test that thumbnail cache persists across service restarts."""
        # First service instance
        db1 = Database(test_gallery['db_path'])
        service1 = ThumbnailService(db1)

        gallery_path = test_gallery['path']
        image_path = str(gallery_path / "red.jpg")

        # Generate thumbnail
        thumb1 = service1.get_or_create_thumbnail(image_path)
        assert isinstance(thumb1, bytes)

        # Second service instance (simulating restart)
        db2 = Database(test_gallery['db_path'])
        service2 = ThumbnailService(db2)

        # Should return cached thumbnail
        thumb2 = service2.get_or_create_thumbnail(image_path)
        assert thumb1 == thumb2

    def test_nested_directory_navigation(self, test_gallery):
        """Test navigating through nested directories."""
        gallery_path = test_gallery['path']

        # Start at root
        file_ops = FileOperations(str(gallery_path), gallery_root=str(gallery_path))
        subdirs = file_ops.list_subdirectories()
        assert 'vacation' in subdirs
        assert 'work' in subdirs

        # Navigate to vacation
        vacation_ops = file_ops.navigate_to('vacation')
        images = vacation_ops.list_images()
        assert len(images) == 3

        # Navigate back to parent
        parent_ops = vacation_ops.navigate_to('..')
        assert parent_ops.current_dir.resolve() == gallery_path.resolve()

    def test_pagination_across_many_images(self, test_gallery):
        """Test pagination with many images."""
        gallery_path = test_gallery['path']

        # Add more images
        for i in range(50):
            Image.new('RGB', (100, 100), color='red').save(
                gallery_path / f"img{i:03d}.jpg", 'JPEG'
            )

        file_ops = FileOperations(str(gallery_path), gallery_root=str(gallery_path))

        # Get first page
        page1, total_pages = file_ops.get_page(1, 20)
        assert len(page1) == 20
        assert total_pages == 3  # 53 images total / 20 per page

        # Get last page
        last_page, _ = file_ops.get_page(3, 20)
        assert len(last_page) == 13  # 53 % 20

    def test_view_tracking_accuracy(self, test_gallery):
        """Test that view tracking is accurate."""
        db = Database(test_gallery['db_path'])
        gallery_path = test_gallery['path']

        image_paths = [
            str(gallery_path / "red.jpg"),
            str(gallery_path / "blue.png"),
            str(gallery_path / "green.webp"),
        ]

        # View images in specific order
        db.record_view(image_paths[0])
        db.record_view(image_paths[1])
        db.record_view(image_paths[2])

        # Least recently viewed should be first
        lrv = db.get_least_recently_viewed(image_paths)
        assert lrv == image_paths[0]

        # View first image again
        db.record_view(image_paths[0])

        # Now second image should be least recently viewed
        lrv = db.get_least_recently_viewed(image_paths)
        assert lrv == image_paths[1]
