"""Thumbnail generation and caching service."""

import io
import os
from pathlib import Path
from typing import Tuple

from PIL import Image

from igallery.database import Database


class ThumbnailService:
    """Manages thumbnail generation and caching."""

    SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

    def __init__(self, db: Database):
        """Initialize thumbnail service.

        Args:
            db: Database instance to use for caching
        """
        self.db = db

    def get_or_create_thumbnail(
        self,
        image_path: str,
        size: Tuple[int, int] = (300, 300)
    ) -> bytes:
        """Get cached thumbnail or create new one.

        Args:
            image_path: Path to the original image
            size: Maximum dimensions for thumbnail (width, height)

        Returns:
            Thumbnail image data as bytes
        """
        image_path = str(Path(image_path).resolve())
        stat = os.stat(image_path)
        image_mtime = stat.st_mtime

        # Check cache
        cached_thumbnail = self.db.get_thumbnail(image_path, image_mtime)
        if cached_thumbnail:
            return cached_thumbnail

        # Generate new thumbnail
        thumbnail_data = self._generate_thumbnail(image_path, size)

        # Save to cache
        self.db.save_thumbnail(
            image_path,
            thumbnail_data,
            image_mtime,
            stat.st_size
        )

        return thumbnail_data

    def _generate_thumbnail(
        self,
        image_path: str,
        size: Tuple[int, int]
    ) -> bytes:
        """Generate a thumbnail for an image.

        Args:
            image_path: Path to the original image
            size: Maximum dimensions for thumbnail

        Returns:
            Thumbnail image data as bytes
        """
        try:
            # Open and resize image
            with Image.open(image_path) as img:
                # Convert RGBA to RGB for consistent JPEG output
                if img.mode in ('RGBA', 'P', 'LA'):
                    img = img.convert('RGB')

                # Create thumbnail maintaining aspect ratio
                img.thumbnail(size, Image.Resampling.LANCZOS)

                # Save to bytes buffer as JPEG
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)

                return buffer.getvalue()

        except Exception as e:
            raise RuntimeError(f"Failed to generate thumbnail for {image_path}: {e}")

    @staticmethod
    def is_image_file(file_path: str) -> bool:
        """Check if a file is a supported image format.

        Args:
            file_path: Path to file

        Returns:
            True if file is a supported image format
        """
        return Path(file_path).suffix.lower() in ThumbnailService.SUPPORTED_FORMATS
