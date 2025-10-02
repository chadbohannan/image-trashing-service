"""Database management for iGallery."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple
import time


class Database:
    """Manages SQLite database for thumbnail cache and image metadata."""

    def __init__(self, db_path: str = ".igallery.db"):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Thumbnail cache table - stores thumbnail as BLOB
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thumbnails (
                    image_path TEXT PRIMARY KEY,
                    thumbnail_data BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    image_mtime REAL NOT NULL,
                    image_size INTEGER NOT NULL
                )
            """)

            # Image metadata table (for view tracking)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS image_metadata (
                    image_path TEXT PRIMARY KEY,
                    last_viewed_at REAL
                )
            """)

            # Trash table - tracks trashed images
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trash (
                    trash_path TEXT PRIMARY KEY,
                    original_path TEXT NOT NULL,
                    trashed_at REAL NOT NULL
                )
            """)

            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_viewed
                ON image_metadata(last_viewed_at)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trashed_at
                ON trash(trashed_at DESC)
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get_thumbnail(self, image_path: str, image_mtime: float) -> Optional[bytes]:
        """Get cached thumbnail data if it exists and is up-to-date.

        Args:
            image_path: Path to the original image
            image_mtime: Modification time of the original image

        Returns:
            Thumbnail data as bytes if valid, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT thumbnail_data, image_mtime FROM thumbnails WHERE image_path = ?",
                (image_path,)
            )
            row = cursor.fetchone()

            if row and row['image_mtime'] == image_mtime:
                return row['thumbnail_data']

            return None

    def save_thumbnail(
        self,
        image_path: str,
        thumbnail_data: bytes,
        image_mtime: float,
        image_size: int
    ):
        """Save thumbnail to cache.

        Args:
            image_path: Path to the original image
            thumbnail_data: Thumbnail image data as bytes
            image_mtime: Modification time of the original image
            image_size: Size of the original image in bytes
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO thumbnails
                (image_path, thumbnail_data, created_at, image_mtime, image_size)
                VALUES (?, ?, ?, ?, ?)
                """,
                (image_path, thumbnail_data, time.time(), image_mtime, image_size)
            )
            conn.commit()

    def sync_images(self, image_paths: list[str]):
        """Sync image metadata for all images, using mtime for new entries.

        This allows prioritizing older files (by mtime) when they haven't been viewed yet.

        Args:
            image_paths: List of all image paths to sync
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            for path in image_paths:
                # Check if record exists
                cursor.execute(
                    "SELECT image_path FROM image_metadata WHERE image_path = ?",
                    (path,)
                )
                if not cursor.fetchone():
                    # New image - insert with mtime as last_viewed_at to prioritize older files
                    try:
                        from pathlib import Path
                        mtime = Path(path).stat().st_mtime
                    except (OSError, FileNotFoundError):
                        # If file doesn't exist (e.g., in tests), use epoch time as fallback
                        mtime = 0.0

                    cursor.execute(
                        """
                        INSERT INTO image_metadata (image_path, last_viewed_at)
                        VALUES (?, ?)
                        """,
                        (path, mtime)
                    )

            conn.commit()

    def record_view(self, image_path: str):
        """Record that an image was viewed.

        Args:
            image_path: Path to the viewed image
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO image_metadata (image_path, last_viewed_at)
                VALUES (?, ?)
                ON CONFLICT(image_path) DO UPDATE SET
                    last_viewed_at = ?
                """,
                (image_path, time.time(), time.time())
            )
            conn.commit()

    def get_least_recently_viewed(self, image_paths: list[str]) -> Optional[str]:
        """Get the least recently viewed image from a list.

        Returns the image with the oldest last_viewed_at timestamp.
        For unviewed images, last_viewed_at contains the file mtime,
        so older files are naturally prioritized.

        Assumes all images have been synced to the database first.

        Args:
            image_paths: List of image paths to consider

        Returns:
            Path to least recently viewed image, or None if list is empty
        """
        if not image_paths:
            return None

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create placeholders for SQL IN clause
            placeholders = ','.join('?' * len(image_paths))

            # Query for the image with the oldest last_viewed_at
            # Unviewed images have mtime, viewed images have actual view timestamp
            cursor.execute(
                f"""
                SELECT image_path, last_viewed_at
                FROM image_metadata
                WHERE image_path IN ({placeholders})
                ORDER BY last_viewed_at ASC
                LIMIT 1
                """,
                image_paths
            )

            row = cursor.fetchone()
            if row:
                return row['image_path']

            # Fallback: return first image if no records found
            return image_paths[0] if image_paths else None

    def delete_thumbnail_record(self, image_path: str):
        """Delete thumbnail record from database.

        Args:
            image_path: Path to the image
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM thumbnails WHERE image_path = ?", (image_path,))
            conn.commit()

    def delete_metadata_record(self, image_path: str):
        """Delete metadata record from database.

        Args:
            image_path: Path to the image
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM image_metadata WHERE image_path = ?", (image_path,))
            conn.commit()

    def add_to_trash(self, trash_path: str, original_path: str):
        """Record an image as trashed.

        Args:
            trash_path: Path to the image in trash folder
            original_path: Original path of the image before trashing
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO trash (trash_path, original_path, trashed_at)
                VALUES (?, ?, ?)
                """,
                (trash_path, original_path, time.time())
            )
            conn.commit()

    def list_trashed_images(self) -> list[dict]:
        """Get list of all trashed images.

        Returns:
            List of dicts with trash_path, original_path, and trashed_at
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT trash_path, original_path, trashed_at
                FROM trash
                ORDER BY trashed_at DESC
                """
            )
            return [
                {
                    'trash_path': row['trash_path'],
                    'original_path': row['original_path'],
                    'trashed_at': row['trashed_at']
                }
                for row in cursor.fetchall()
            ]

    def remove_from_trash(self, trash_path: str):
        """Remove an image record from trash table.

        Args:
            trash_path: Path to the image in trash folder
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trash WHERE trash_path = ?", (trash_path,))
            conn.commit()

    def get_trash_item(self, trash_path: str) -> dict | None:
        """Get trash record for a specific image.

        Args:
            trash_path: Path to the image in trash folder

        Returns:
            Dict with trash_path, original_path, trashed_at or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT trash_path, original_path, trashed_at FROM trash WHERE trash_path = ?",
                (trash_path,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'trash_path': row['trash_path'],
                    'original_path': row['original_path'],
                    'trashed_at': row['trashed_at']
                }
            return None

    def clear_trash_table(self):
        """Remove all records from trash table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trash")
            conn.commit()

    def cleanup_orphaned_records(self, valid_image_paths: set[str], valid_trash_paths: set[str]):
        """Remove database records for images that no longer exist on filesystem.

        Args:
            valid_image_paths: Set of image paths that currently exist in gallery
            valid_trash_paths: Set of image paths that currently exist in trash
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get all image paths in thumbnails table
            cursor.execute("SELECT image_path FROM thumbnails")
            thumbnail_paths = [row['image_path'] for row in cursor.fetchall()]

            # Get all image paths in metadata table
            cursor.execute("SELECT image_path FROM image_metadata")
            metadata_paths = [row['image_path'] for row in cursor.fetchall()]

            # Get all trash paths
            cursor.execute("SELECT trash_path FROM trash")
            trash_db_paths = [row['trash_path'] for row in cursor.fetchall()]

            # Delete orphaned thumbnail records (not in gallery or trash)
            all_valid = valid_image_paths | valid_trash_paths
            orphaned_thumbnails = [p for p in thumbnail_paths if p not in all_valid]
            if orphaned_thumbnails:
                placeholders = ','.join('?' * len(orphaned_thumbnails))
                cursor.execute(
                    f"DELETE FROM thumbnails WHERE image_path IN ({placeholders})",
                    orphaned_thumbnails
                )

            # Delete orphaned metadata records (not in gallery or trash)
            orphaned_metadata = [p for p in metadata_paths if p not in all_valid]
            if orphaned_metadata:
                placeholders = ','.join('?' * len(orphaned_metadata))
                cursor.execute(
                    f"DELETE FROM image_metadata WHERE image_path IN ({placeholders})",
                    orphaned_metadata
                )

            # Delete orphaned trash records
            orphaned_trash = [p for p in trash_db_paths if p not in valid_trash_paths]
            if orphaned_trash:
                placeholders = ','.join('?' * len(orphaned_trash))
                cursor.execute(
                    f"DELETE FROM trash WHERE trash_path IN ({placeholders})",
                    orphaned_trash
                )

            conn.commit()

            return len(orphaned_thumbnails), len(orphaned_metadata), len(orphaned_trash)
