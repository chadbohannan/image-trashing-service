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

        # Create subdirectory with images
        subdir = gallery_path / "subdir"
        subdir.mkdir()
        Image.new('RGB', (800, 600), color='green').save(subdir / "subimage.jpg", 'JPEG')

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

    def test_app_continues_after_db_deletion(self, app_with_db):
        """Test that all app functionality continues after database deletion."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        images = list(gallery_path.glob("*.jpg"))
        image_name = images[0].name

        # Make initial requests to populate database
        response = client.get('/')
        assert response.status_code == 200

        # Get thumbnail (caches in database)
        response = client.get(f'/thumbnail/{image_name}')
        assert response.status_code == 200
        thumbnail_before = response.data

        # View image (records in database)
        response = client.get(f'/image/{image_name}')
        assert response.status_code == 200

        # Get carousel (uses database for ordering)
        response = client.get('/carousel/next')
        assert response.status_code == 200

        # Verify database exists
        assert db_path.exists()

        # DELETE THE DATABASE
        db_path.unlink()
        assert not db_path.exists()

        # Verify all functionality continues to work

        # 1. Gallery view should work
        response = client.get('/')
        assert response.status_code == 200

        # 2. Thumbnails should regenerate
        response = client.get(f'/thumbnail/{image_name}')
        assert response.status_code == 200
        assert len(response.data) > 0

        # 3. Image viewing should work
        response = client.get(f'/image/{images[1].name}')
        assert response.status_code == 200

        # 4. Carousel should work (ordering may be lost but shouldn't crash)
        response = client.get('/carousel/next')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'image_url' in data
        assert 'image_name' in data

        # 5. Trash functionality should work
        response = client.post(
            '/trash',
            data=json.dumps({'image_name': images[2].name}),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

        # 6. Pagination should work
        response = client.get('/?page=1')
        assert response.status_code == 200

    def test_database_reinitialization(self):
        """Test that database can be reinitialized after deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database and save data
            db1 = Database(str(db_path))
            db1.save_thumbnail("/img1.jpg", b"thumb1", 100.0, 1024)
            db1.record_view("/img1.jpg")

            # Verify data is saved
            assert db1.get_thumbnail("/img1.jpg", 100.0) == b"thumb1"
            assert db_path.exists()

            # Delete database file
            db_path.unlink()
            assert not db_path.exists()

            # Create new database instance - should reinitialize
            db2 = Database(str(db_path))
            assert db_path.exists()

            # Old data should be lost
            assert db2.get_thumbnail("/img1.jpg", 100.0) is None

            # Should be able to use new database
            db2.save_thumbnail("/img2.jpg", b"thumb2", 200.0, 2048)
            assert db2.get_thumbnail("/img2.jpg", 200.0) == b"thumb2"

    def test_database_persistence_across_operations(self, temp_gallery_with_db):
        """Test that database persists data until deleted."""
        db_path = temp_gallery_with_db['db_path']

        # Create database and add data
        db1 = Database(str(db_path))
        db1.save_thumbnail("/img1.jpg", b"thumb1", 100.0, 1024)
        db1.record_view("/img1.jpg")

        # Create new instance (simulating app restart) - data should persist
        db2 = Database(str(db_path))
        assert db2.get_thumbnail("/img1.jpg", 100.0) == b"thumb1"

        # Delete database
        db_path.unlink()

        # Create new instance - data should be lost
        db3 = Database(str(db_path))
        assert db3.get_thumbnail("/img1.jpg", 100.0) is None

    def test_trash_sync_after_db_deletion(self, app_with_db):
        """Test that trash folder syncs correctly after database deletion."""
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

        # Trash an image from subdirectory
        response = client.post(
            '/trash?path=subdir',
            data=json.dumps({'image_name': 'subimage.jpg'}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Verify trash view shows images
        response = client.get('/trash-view')
        assert response.status_code == 200

        # Delete database (loses trash tracking)
        db_path.unlink()

        # Access trash view - should sync and rediscover files
        response = client.get('/trash-view')
        assert response.status_code == 200

        # Verify trash files still exist on filesystem
        trash_dir = gallery_path / "trash"
        trash_files = list(trash_dir.glob("**/*.jpg"))
        assert len(trash_files) == 4  # 3 root images + 1 subdirectory image

        # Verify subdirectory structure is preserved
        assert (trash_dir / "subdir" / "subimage.jpg").exists()

        # Try to restore an image after resync
        image_name = images[0].name
        response = client.post(
            '/trash/restore',
            data=json.dumps({'trash_path': image_name}),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Verify image was restored
        assert (gallery_path / image_name).exists()

    def test_metadata_deletion_endpoint(self, app_with_db):
        """Test the /metadata/delete endpoint."""
        app, paths = app_with_db
        client = app.test_client()
        db_path = paths['db_path']
        gallery_path = paths['gallery_path']

        images = list(gallery_path.glob("*.jpg"))

        # Create some metadata
        for i in range(3):
            response = client.get(f'/image/{images[i].name}')
            assert response.status_code == 200

        response = client.get(f'/thumbnail/{images[0].name}')
        assert response.status_code == 200

        # Verify database exists
        assert db_path.exists()

        # Delete metadata via endpoint
        response = client.post('/metadata/delete')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

        # Verify database file is deleted
        assert not db_path.exists()

        # Verify app continues to work after deletion
        response = client.get('/')
        assert response.status_code == 200

        # Thumbnails should regenerate
        response = client.get(f'/thumbnail/{images[0].name}')
        assert response.status_code == 200

        # Carousel should work
        response = client.get('/carousel/next')
        assert response.status_code == 200

        # Test endpoint when database is already missing
        db_path.unlink() if db_path.exists() else None
        response = client.post('/metadata/delete')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_graceful_startup_without_database(self):
        """Test that app starts correctly without existing database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gallery_path = Path(tmpdir) / "gallery"
            gallery_path.mkdir()

            # Create test images
            for i in range(5):
                img_path = gallery_path / f"image{i}.jpg"
                Image.new('RGB', (800, 600), color='red').save(img_path, 'JPEG')

            # Don't create database beforehand
            db_path = gallery_path / ".igallery.db"
            assert not db_path.exists()

            # Create app - database should be created automatically
            app = create_app(
                gallery_root=str(gallery_path),
                db_path=str(db_path)
            )
            app.config['TESTING'] = True
            client = app.test_client()

            # All operations should work
            response = client.get('/')
            assert response.status_code == 200

            images = list(gallery_path.glob("*.jpg"))
            response = client.get(f'/thumbnail/{images[0].name}')
            assert response.status_code == 200

            response = client.get(f'/image/{images[1].name}')
            assert response.status_code == 200

            response = client.get('/carousel/next')
            assert response.status_code == 200
