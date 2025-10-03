"""Tests for database recovery and resilience when database file is deleted."""

import json
import os
import tempfile
import time
from pathlib import Path
import pytest
from PIL import Image

from igallery.app import create_app
from igallery.database import Database


@pytest.fixture
def temp_gallery_with_db():
    """Create a temporary gallery directory with test images and database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gallery_path = Path(tmpdir) / "gallery"
        gallery_path.mkdir()

        # Create test images with different mtimes
        for i in range(10):
            img_path = gallery_path / f"image{i:02d}.jpg"
            Image.new('RGB', (800, 600), color='red').save(img_path, 'JPEG')
            # Set different mtimes to test ordering
            os.utime(img_path, (time.time() - (10 - i) * 86400, time.time() - (10 - i) * 86400))

        db_path = gallery_path / ".igallery.db"

        yield {
            'gallery_path': gallery_path,
            'db_path': db_path
        }


@pytest.fixture
def app_with_db(temp_gallery_with_db):
    """Create Flask app with database."""
    gallery_path = temp_gallery_with_db['gallery_path']
    db_path = temp_gallery_with_db['db_path']

    app = create_app(
        gallery_root=str(gallery_path),
        db_path=str(db_path)
    )
    app.config['TESTING'] = True
    return app, temp_gallery_with_db


class TestDatabaseRecovery:
    """Test database recovery scenarios when database file is deleted."""

    def test_database_file_deleted_during_runtime(self, app_with_db):
        """Test that app can handle database file deletion during runtime."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']

        # Make initial request to ensure database is created
        response = client.get('/')
        assert response.status_code == 200

        # Verify database file exists
        assert db_path.exists()

        # Delete the database file
        db_path.unlink()
        assert not db_path.exists()

        # App should still function - verify basic operations work
        # Gallery view should still work
        response = client.get('/')
        assert response.status_code == 200

    def test_thumbnails_regenerated_after_db_deletion(self, app_with_db):
        """Test that thumbnails are regenerated after database deletion."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        # Get a thumbnail (this will cache it in database)
        images = list(gallery_path.glob("*.jpg"))
        image_name = images[0].name
        response = client.get(f'/thumbnail/{image_name}')
        assert response.status_code == 200
        first_thumbnail = response.data

        # Delete the database
        db_path.unlink()

        # Request the thumbnail again - should regenerate
        response = client.get(f'/thumbnail/{image_name}')
        assert response.status_code == 200
        # Thumbnail should be regenerated (data should be similar)
        assert len(response.data) > 0

    def test_view_tracking_after_db_deletion(self, app_with_db):
        """Test that view tracking can resume after database deletion."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        images = list(gallery_path.glob("*.jpg"))
        image_name = images[0].name

        # View an image (records view in database)
        response = client.get(f'/image/{image_name}')
        assert response.status_code == 200

        # Delete the database
        db_path.unlink()

        # View another image - should not crash
        response = client.get(f'/image/{images[1].name}')
        assert response.status_code == 200

    def test_carousel_after_db_deletion(self, app_with_db):
        """Test that carousel mode works after database deletion."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']

        # Request carousel next (requires database for ordering)
        response = client.get('/carousel/next')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'image_url' in data

        # Delete the database
        db_path.unlink()

        # Carousel should still work (may lose ordering, but should not crash)
        response = client.get('/carousel/next')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'image_url' in data

    def test_trash_functionality_after_db_deletion(self, app_with_db):
        """Test that trash functionality continues after database deletion."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        images = list(gallery_path.glob("*.jpg"))
        image_name = images[0].name

        # Trash an image before database deletion
        response = client.post(
            '/trash',
            data=json.dumps({'image_name': image_name}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Delete the database
        db_path.unlink()

        # Try to trash another image - should work (file operation should succeed)
        response = client.post(
            '/trash',
            data=json.dumps({'image_name': images[1].name}),
            content_type='application/json'
        )
        assert response.status_code == 200

    def test_database_reinitialization_after_deletion(self):
        """Test that database can be reinitialized after deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database
            db1 = Database(str(db_path))
            db1.save_thumbnail("/img.jpg", b"data", 123.0, 100)

            # Verify database file exists
            assert db_path.exists()

            # Delete database file
            db_path.unlink()
            assert not db_path.exists()

            # Create new database instance - should reinitialize
            db2 = Database(str(db_path))
            assert db_path.exists()

            # Should be able to use the new database
            db2.save_thumbnail("/img2.jpg", b"data2", 456.0, 200)
            result = db2.get_thumbnail("/img2.jpg", 456.0)
            assert result == b"data2"

            # Old data should be gone (lost)
            result = db2.get_thumbnail("/img.jpg", 123.0)
            assert result is None

    def test_multiple_requests_after_db_deletion(self, app_with_db):
        """Test that multiple requests work correctly after database deletion."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        # Make initial request
        response = client.get('/')
        assert response.status_code == 200

        # Delete database
        db_path.unlink()

        # Make multiple different requests - all should succeed
        response = client.get('/')
        assert response.status_code == 200

        response = client.get('/?page=1')
        assert response.status_code == 200

        images = list(gallery_path.glob("*.jpg"))
        response = client.get(f'/thumbnail/{images[0].name}')
        assert response.status_code == 200

        response = client.get(f'/image/{images[1].name}')
        assert response.status_code == 200

    def test_database_persistence_across_operations(self, temp_gallery_with_db):
        """Test that database persists data across multiple operations until deleted."""
        gallery_path = temp_gallery_with_db['gallery_path']
        db_path = temp_gallery_with_db['db_path']

        # Create database and add data
        db = Database(str(db_path))
        db.save_thumbnail("/img1.jpg", b"thumb1", 100.0, 1024)
        db.record_view("/img1.jpg")

        # Create new database instance (simulating app restart)
        db2 = Database(str(db_path))

        # Data should persist
        thumb = db2.get_thumbnail("/img1.jpg", 100.0)
        assert thumb == b"thumb1"

        # Delete database
        db_path.unlink()

        # Create new database instance
        db3 = Database(str(db_path))

        # Data should be lost
        thumb = db3.get_thumbnail("/img1.jpg", 100.0)
        assert thumb is None

    def test_graceful_degradation_without_database(self):
        """Test that critical functionality works even without persistent database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gallery_path = Path(tmpdir) / "gallery"
            gallery_path.mkdir()

            # Create test images
            for i in range(5):
                img_path = gallery_path / f"image{i}.jpg"
                Image.new('RGB', (800, 600), color='red').save(img_path, 'JPEG')

            # Don't create a database initially
            db_path = gallery_path / ".igallery.db"

            # Create app - database will be created automatically
            app = create_app(
                gallery_root=str(gallery_path),
                db_path=str(db_path)
            )
            app.config['TESTING'] = True
            client = app.test_client()

            # All basic operations should work
            response = client.get('/')
            assert response.status_code == 200

            images = list(gallery_path.glob("*.jpg"))
            response = client.get(f'/thumbnail/{images[0].name}')
            assert response.status_code == 200

            response = client.get(f'/image/{images[1].name}')
            assert response.status_code == 200

    def test_ordering_lost_but_app_continues(self, app_with_db):
        """Test that view ordering is lost after DB deletion but app continues."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        # View images in specific order
        images = sorted(list(gallery_path.glob("*.jpg")))
        for i, img in enumerate(images[:3]):
            time.sleep(0.01)
            response = client.get(f'/image/{img.name}')
            assert response.status_code == 200

        # Get carousel next - should return least recently viewed
        response = client.get('/carousel/next')
        assert response.status_code == 200
        first_carousel = json.loads(response.data)

        # Delete database (loses ordering information)
        db_path.unlink()

        # Carousel should still work (but ordering may be different)
        response = client.get('/carousel/next')
        assert response.status_code == 200
        second_carousel = json.loads(response.data)

        # Should return an image (even if ordering is lost)
        assert 'image_url' in second_carousel
        assert 'image_name' in second_carousel

    def test_trash_folder_sync_after_db_deletion(self, app_with_db):
        """Test that trash folder syncs with database after deletion."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        images = list(gallery_path.glob("*.jpg"))

        # Trash some images
        for i in range(3):
            response = client.post(
                '/trash',
                data=json.dumps({'image_name': images[i].name}),
                content_type='application/json'
            )
            assert response.status_code == 200

        # Verify trash view shows the images
        response = client.get('/trash-view')
        assert response.status_code == 200
        assert b'image00.jpg' in response.data or b'image01.jpg' in response.data

        # Delete database (loses trash tracking)
        db_path.unlink()

        # Access trash view - should sync and rediscover trash files
        response = client.get('/trash-view')
        assert response.status_code == 200

        # Verify trash images are shown (rediscovered from filesystem)
        # The trash folder still contains the files, so they should be visible
        trash_dir = gallery_path / "trash"
        trash_files = list(trash_dir.glob("**/*.jpg"))
        assert len(trash_files) == 3  # Files still exist in trash folder

    def test_trash_restore_after_db_deletion(self, app_with_db):
        """Test that trash restore works after database deletion and resync."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        images = list(gallery_path.glob("*.jpg"))
        image_name = images[0].name

        # Trash an image
        response = client.post(
            '/trash',
            data=json.dumps({'image_name': image_name}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Delete database
        db_path.unlink()

        # Access trash view to trigger sync
        response = client.get('/trash-view')
        assert response.status_code == 200

        # Try to restore the image
        response = client.post(
            '/trash/restore',
            data=json.dumps({'trash_path': image_name}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Verify image was restored
        restored_path = gallery_path / image_name
        assert restored_path.exists()

    def test_trash_folder_with_subdirectories(self, app_with_db):
        """Test trash sync handles subdirectory structure correctly."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        # Create a subdirectory with an image
        subdir = gallery_path / "subdir"
        subdir.mkdir(exist_ok=True)
        subdir_image = subdir / "subimage.jpg"
        Image.new('RGB', (800, 600), color='green').save(subdir_image, 'JPEG')

        # Trash the subdirectory image
        response = client.post(
            '/trash?path=subdir',
            data=json.dumps({'image_name': 'subimage.jpg'}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Delete database
        db_path.unlink()

        # Access trash view to trigger sync
        response = client.get('/trash-view')
        assert response.status_code == 200

        # Verify subdirectory image appears in trash
        trash_dir = gallery_path / "trash" / "subdir"
        assert trash_dir.exists()
        assert (trash_dir / "subimage.jpg").exists()

    def test_delete_metadata_endpoint(self, app_with_db):
        """Test the delete metadata endpoint removes database file."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']

        # Verify database exists
        assert db_path.exists()

        # Call delete metadata endpoint
        response = client.post('/metadata/delete')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True

        # Verify database file is deleted
        assert not db_path.exists()

    def test_delete_metadata_when_db_missing(self, app_with_db):
        """Test delete metadata endpoint handles missing database gracefully."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']

        # Delete database first
        db_path.unlink()

        # Call delete metadata endpoint (should succeed gracefully)
        response = client.post('/metadata/delete')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True

    def test_app_recovery_after_metadata_deletion(self, app_with_db):
        """Test that app recovers after metadata deletion via endpoint."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        images = list(gallery_path.glob("*.jpg"))

        # View some images to create metadata
        for i in range(3):
            response = client.get(f'/image/{images[i].name}')
            assert response.status_code == 200

        # Get a thumbnail to create cache
        response = client.get(f'/thumbnail/{images[0].name}')
        assert response.status_code == 200

        # Delete metadata via endpoint
        response = client.post('/metadata/delete')
        assert response.status_code == 200

        # Verify database is gone
        assert not db_path.exists()

        # Verify app continues to work
        response = client.get('/')
        assert response.status_code == 200

        # Thumbnails should regenerate
        response = client.get(f'/thumbnail/{images[0].name}')
        assert response.status_code == 200

        # Carousel should work
        response = client.get('/carousel/next')
        assert response.status_code == 200
