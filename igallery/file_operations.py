"""File operations for image gallery."""

import os
import shutil
from pathlib import Path
from typing import List, Tuple

from igallery.thumbnail_service import ThumbnailService


class FileOperations:
    """Manages file system operations for the gallery."""

    def __init__(self, current_dir: str = ".", gallery_root: str = None):
        """Initialize file operations.

        Args:
            current_dir: Directory to operate in
            gallery_root: Root directory of the gallery (for trash location)
        """
        self.current_dir = Path(current_dir).resolve()
        self.gallery_root = Path(gallery_root).resolve() if gallery_root else self.current_dir

    def list_images(self) -> List[str]:
        """List all images in current directory.

        Returns:
            Sorted list of image file paths
        """
        images = []
        try:
            for entry in self.current_dir.iterdir():
                if entry.is_file() and ThumbnailService.is_image_file(str(entry)):
                    images.append(str(entry))
        except PermissionError:
            pass

        return sorted(images)

    def list_subdirectories(self) -> List[str]:
        """List all subdirectories in current directory.

        Returns:
            Sorted list of subdirectory names (relative)
        """
        subdirs = []
        try:
            for entry in self.current_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith('.') and entry.name != 'trash':
                    subdirs.append(entry.name)
        except PermissionError:
            pass

        return sorted(subdirs)

    def navigate_to(self, path: str) -> 'FileOperations':
        """Navigate to a subdirectory or parent.

        Args:
            path: Relative path to navigate to (e.g., "subdir" or "..")

        Returns:
            New FileOperations instance for the target directory
        """
        target_dir = (self.current_dir / path).resolve()

        # Security check: ensure target is a directory
        if not target_dir.is_dir():
            raise ValueError(f"Not a directory: {path}")

        return FileOperations(str(target_dir))

    def move_to_trash(self, image_path: str) -> str:
        """Move an image to the trash folder in gallery root.

        Args:
            image_path: Path to image to trash

        Returns:
            Path to the trashed image in trash folder
        """
        # Trash folder is always at gallery root
        trash_dir = self.gallery_root / "trash"
        trash_dir.mkdir(exist_ok=True)

        image_path = Path(image_path).resolve()

        # Preserve directory structure relative to gallery root
        try:
            rel_path = image_path.relative_to(self.gallery_root)
            target_path = trash_dir / rel_path

            # Create subdirectories in trash if needed
            target_path.parent.mkdir(parents=True, exist_ok=True)
        except ValueError:
            # Image is outside gallery root, just use filename
            target_path = trash_dir / image_path.name

        # Handle duplicate filenames
        if target_path.exists():
            counter = 1
            stem = image_path.stem
            suffix = image_path.suffix
            base_dir = target_path.parent
            while target_path.exists():
                target_path = base_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        shutil.move(str(image_path), str(target_path))
        return str(target_path)

    def get_image_path(self, image_name: str) -> str:
        """Get full path for an image by name.

        Args:
            image_name: Name of the image file

        Returns:
            Full path to the image
        """
        return str(self.current_dir / image_name)

    def get_page(self, page: int, per_page: int = 20) -> Tuple[List[str], int]:
        """Get paginated list of images.

        Args:
            page: Page number (1-indexed)
            per_page: Number of images per page

        Returns:
            Tuple of (list of image paths for page, total number of pages)
        """
        images = self.list_images()
        total_images = len(images)

        if total_images == 0:
            return [], 0

        total_pages = (total_images + per_page - 1) // per_page

        # Handle out of range
        if page < 1 or page > total_pages:
            return [], total_pages

        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page

        return images[start_idx:end_idx], total_pages

    def get_relative_path(self, full_path: str) -> str:
        """Get relative path from current directory.

        Args:
            full_path: Full path to file

        Returns:
            Relative path from current directory
        """
        try:
            return str(Path(full_path).relative_to(self.current_dir))
        except ValueError:
            return str(Path(full_path).name)
