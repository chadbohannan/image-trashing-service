"""Tests for file operations (navigation, trash)."""

import tempfile
from pathlib import Path
import pytest
from PIL import Image

from igallery.file_operations import FileOperations


@pytest.fixture
def temp_gallery():
    """Create a temporary gallery directory with test images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gallery_path = Path(tmpdir) / "gallery"
        gallery_path.mkdir()

        # Create test image files
        for i in range(15):
            img_path = gallery_path / f"image{i:02d}.jpg"
            Image.new('RGB', (100, 100), color='red').save(img_path, 'JPEG')

        # Create subdirectories with images
        subdir1 = gallery_path / "subdir1"
        subdir1.mkdir()
        for i in range(5):
            img_path = subdir1 / f"sub_image{i}.jpg"
            Image.new('RGB', (100, 100), color='blue').save(img_path, 'JPEG')

        subdir2 = gallery_path / "subdir2"
        subdir2.mkdir()

        # Create some non-image files
        (gallery_path / "readme.txt").write_text("test")

        yield gallery_path


@pytest.fixture
def file_ops(temp_gallery):
    """Create file operations instance."""
    return FileOperations(str(temp_gallery), gallery_root=str(temp_gallery))


class TestFileOperations:
    """Test file operations."""

    def test_list_images_in_directory(self, file_ops, temp_gallery):
        """Test listing images in directory."""
        images = file_ops.list_images()

        # Should find 15 images in root
        assert len(images) == 15
        assert all(Path(img).suffix.lower() == '.jpg' for img in images)

    def test_list_images_sorted(self, file_ops):
        """Test that images are sorted by name."""
        images = file_ops.list_images()

        # Check that images are sorted
        assert images == sorted(images)

    def test_list_subdirectories(self, file_ops, temp_gallery):
        """Test listing subdirectories."""
        subdirs = file_ops.list_subdirectories()

        assert len(subdirs) == 2
        assert 'subdir1' in subdirs
        assert 'subdir2' in subdirs

    def test_list_images_in_subdirectory(self, temp_gallery):
        """Test listing images in subdirectory."""
        file_ops = FileOperations(str(temp_gallery / "subdir1"), gallery_root=str(temp_gallery))
        images = file_ops.list_images()

        assert len(images) == 5

    def test_navigate_to_subdirectory(self, temp_gallery):
        """Test navigating to subdirectory."""
        file_ops = FileOperations(str(temp_gallery))

        # Navigate to subdir1
        new_ops = file_ops.navigate_to("subdir1")

        assert new_ops.current_dir.name == "subdir1"
        assert len(new_ops.list_images()) == 5

    def test_navigate_to_parent(self, temp_gallery):
        """Test navigating to parent directory."""
        file_ops = FileOperations(str(temp_gallery / "subdir1"), gallery_root=str(temp_gallery))

        parent_ops = file_ops.navigate_to("..")

        assert parent_ops.current_dir.resolve() == temp_gallery.resolve()

    def test_move_to_trash(self, file_ops, temp_gallery):
        """Test moving image to trash."""
        images = file_ops.list_images()
        image_to_trash = images[0]

        trash_path = file_ops.move_to_trash(image_to_trash)

        # Image should no longer be in directory
        remaining_images = file_ops.list_images()
        assert image_to_trash not in remaining_images
        assert len(remaining_images) == len(images) - 1

        # Image should be in trash folder at gallery root
        assert Path(trash_path).exists()
        assert str(Path(trash_path).parent.name) == "trash"

    def test_trash_directory_created_lazily(self, file_ops, temp_gallery):
        """Test that trash directory is created on first use."""
        trash_dir = temp_gallery / "trash"
        assert not trash_dir.exists()

        # Move file to trash
        images = file_ops.list_images()
        file_ops.move_to_trash(images[0])

        # Trash directory should now exist
        assert trash_dir.exists()

    def test_move_multiple_files_to_trash(self, file_ops):
        """Test moving multiple files to trash."""
        images = file_ops.list_images()
        to_trash = images[:3]

        for img in to_trash:
            file_ops.move_to_trash(img)

        remaining_images = file_ops.list_images()
        assert len(remaining_images) == len(images) - 3

    def test_trash_preserves_filenames(self, file_ops, temp_gallery):
        """Test that trash preserves original filenames."""
        images = file_ops.list_images()
        image_to_trash = images[0]
        original_name = Path(image_to_trash).name

        file_ops.move_to_trash(image_to_trash)

        trash_file = temp_gallery / "trash" / original_name
        assert trash_file.exists()

    def test_handle_duplicate_filenames_in_trash(self, file_ops, temp_gallery):
        """Test handling duplicate filenames when moving to trash."""
        images = file_ops.list_images()
        image1 = images[0]

        # Move to trash
        file_ops.move_to_trash(image1)

        # Create another file with same name and move to trash
        new_file = temp_gallery / Path(image1).name
        Image.new('RGB', (100, 100), color='green').save(new_file, 'JPEG')

        file_ops_new = FileOperations(str(temp_gallery))
        file_ops_new.move_to_trash(str(new_file))

        # Both files should be in trash (one with modified name)
        trash_dir = temp_gallery / "trash"
        trash_files = list(trash_dir.glob("*.jpg"))
        assert len(trash_files) == 2

    def test_get_image_path(self, file_ops):
        """Test getting full image path."""
        images = file_ops.list_images()
        image_name = Path(images[0]).name

        full_path = file_ops.get_image_path(image_name)

        assert Path(full_path).exists()
        assert Path(full_path).name == image_name

    def test_pagination_info(self, file_ops):
        """Test getting pagination info."""
        images = file_ops.list_images()

        # Get page 1 with 10 items per page
        page_images, total_pages = file_ops.get_page(1, 10)

        assert len(page_images) == 10
        assert total_pages == 2  # 15 images / 10 per page = 2 pages

    def test_pagination_last_page(self, file_ops):
        """Test getting last page with partial items."""
        # Get page 2 with 10 items per page
        page_images, total_pages = file_ops.get_page(2, 10)

        assert len(page_images) == 5  # Remaining 5 images
        assert total_pages == 2

    def test_pagination_out_of_range(self, file_ops):
        """Test pagination with out of range page number."""
        page_images, total_pages = file_ops.get_page(999, 10)

        assert len(page_images) == 0
        assert total_pages == 2

    def test_empty_directory(self, temp_gallery):
        """Test operations on empty directory."""
        empty_dir = temp_gallery / "empty"
        empty_dir.mkdir()

        file_ops = FileOperations(str(empty_dir), gallery_root=str(temp_gallery))

        assert len(file_ops.list_images()) == 0
        assert len(file_ops.list_subdirectories()) == 0

        page_images, total_pages = file_ops.get_page(1, 10)
        assert len(page_images) == 0
        assert total_pages == 0

    def test_relative_path_handling(self, file_ops):
        """Test that relative paths are handled correctly."""
        subdirs = file_ops.list_subdirectories()
        assert all(not Path(d).is_absolute() for d in subdirs)
