"""Flask web application for iGallery."""

import io
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, render_template, send_file, request, jsonify, abort, make_response

from igallery.database import Database
from igallery.thumbnail_service import ThumbnailService
from igallery.file_operations import FileOperations


def _collect_all_image_paths_in_dir(directory: Path, exclude_dirs: set[str] = None) -> set[str]:
    """Recursively collect all image paths in a directory.

    Args:
        directory: Directory to scan
        exclude_dirs: Set of directory names to exclude

    Returns:
        Set of absolute image paths
    """
    exclude_dirs = exclude_dirs or set()
    images = set()

    for root, dirs, files in os.walk(directory):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for file in files:
            file_path = Path(root) / file
            if ThumbnailService.is_image_file(str(file_path)):
                images.add(str(file_path.resolve()))

    return images


def create_app(
    gallery_root: str = ".",
    db_path: str = ".igallery.db"
):
    """Create and configure Flask application.

    Args:
        gallery_root: Root directory for image gallery
        db_path: Path to SQLite database

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    app.config['GALLERY_ROOT'] = gallery_root
    app.config['DB_PATH'] = db_path

    # Initialize services
    db = Database(db_path)
    thumbnail_service = ThumbnailService(db)

    # Track cleanup status
    cleanup_status = {'in_progress': False, 'last_run': None}

    def cleanup_orphaned_records_async():
        """Background task to cleanup orphaned database records."""
        if cleanup_status['in_progress']:
            return  # Already running

        cleanup_status['in_progress'] = True
        try:
            gallery_path = Path(gallery_root).resolve()
            trash_path = gallery_path / "trash"

            # Collect valid paths
            valid_gallery = _collect_all_image_paths_in_dir(gallery_path, exclude_dirs={'trash'})
            valid_trash = _collect_all_image_paths_in_dir(trash_path) if trash_path.exists() else set()

            # Cleanup
            orphaned_thumbs, orphaned_meta, orphaned_trash = db.cleanup_orphaned_records(
                valid_gallery, valid_trash
            )

            import time
            cleanup_status['last_run'] = time.time()

            if orphaned_thumbs or orphaned_meta or orphaned_trash:
                print(f"Cleanup: Removed {orphaned_thumbs} thumbnails, {orphaned_meta} metadata, {orphaned_trash} trash records")
        except Exception as e:
            # Silently handle errors in background thread
            print(f"Background cleanup error: {e}")
        finally:
            cleanup_status['in_progress'] = False

    # Start background cleanup on first request (skip in testing mode)
    @app.before_request
    def lazy_cleanup():
        """Trigger cleanup on first request only."""
        if app.config.get('TESTING'):
            return
        if cleanup_status['last_run'] is None and not cleanup_status['in_progress']:
            threading.Thread(target=cleanup_orphaned_records_async, daemon=True).start()

    def validate_gallery_path(relative_path: str = '') -> Path:
        """Validate and resolve a gallery path.

        Args:
            relative_path: Relative path within gallery

        Returns:
            Resolved Path object

        Raises:
            403: Path traversal attempt
            400: Invalid path
        """
        try:
            current_dir = (Path(gallery_root) / relative_path).resolve()
            gallery_root_resolved = Path(gallery_root).resolve()
            if not str(current_dir).startswith(str(gallery_root_resolved)):
                abort(403)
            return current_dir
        except Exception:
            abort(400)

    @app.route('/')
    def index():
        """Gallery index page with thumbnail grid."""
        # Get path parameter for subdirectory navigation
        relative_path = request.args.get('path', '')
        current_dir = validate_gallery_path(relative_path)

        file_ops = FileOperations(str(current_dir), gallery_root=gallery_root)

        # Pagination
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))

        items, total_pages = file_ops.get_page_with_directories(page, per_page)

        # If this is an AJAX request, return JSON
        if request.args.get('fetch_images_only') == 'true':
            return jsonify({
                'success': True,
                'items': items,
                'page': page,
                'total_pages': total_pages
            })

        # Build breadcrumbs
        breadcrumbs = []
        if relative_path:
            parts = Path(relative_path).parts
            for i, part in enumerate(parts):
                path = '/'.join(parts[:i+1])
                breadcrumbs.append({'name': part, 'path': path})

        return render_template(
            'index.html',
            items=items,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            current_path=relative_path,
            breadcrumbs=breadcrumbs,
            has_parent=relative_path != ''
        )

    @app.route('/thumbnail/<path:image_path>')
    def thumbnail(image_path):
        """Serve thumbnail for an image."""
        full_image_path = validate_gallery_path(image_path)

        if not full_image_path.exists():
            abort(404)

        # Get image modification time for cache validation
        image_mtime = os.path.getmtime(str(full_image_path))
        last_modified = datetime.fromtimestamp(image_mtime, timezone.utc)

        # Check if client has a cached version
        if_modified_since = request.headers.get('If-Modified-Since')
        if if_modified_since:
            try:
                # Parse client's cached timestamp
                client_mtime = datetime.strptime(if_modified_since, '%a, %d %b %Y %H:%M:%S GMT')
                # If file hasn't been modified, return 304 Not Modified
                if last_modified <= client_mtime:
                    return make_response('', 304)
            except ValueError:
                pass  # Invalid date format, ignore

        # Generate or retrieve thumbnail
        try:
            thumbnail_data = thumbnail_service.get_or_create_thumbnail(str(full_image_path))
            response = make_response(send_file(
                io.BytesIO(thumbnail_data),
                mimetype='image/jpeg',
                as_attachment=False
            ))

            # Set caching headers
            response.headers['Last-Modified'] = last_modified.strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.headers['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'

            return response
        except Exception as e:
            app.logger.error(f"Error generating thumbnail: {e}")
            abort(500)

    @app.route('/image/<path:image_path>')
    def image(image_path):
        """Serve full-size image."""
        preload = request.args.get('preload', 'false') == 'true'
        full_image_path = validate_gallery_path(image_path)

        if not full_image_path.exists():
            abort(404)

        # Record view only if not preloading
        if not preload:
            db.record_view(str(full_image_path))

        return send_file(str(full_image_path))

    @app.route('/carousel')
    def carousel():
        """Carousel page."""
        relative_path = request.args.get('path', '')

        return render_template(
            'carousel.html',
            current_path=relative_path
        )

    @app.route('/carousel/next')
    def carousel_next():
        """Get next image for carousel (slideshow mode)."""
        relative_path = request.args.get('path', '')
        preload = request.args.get('preload', 'false') == 'true'

        # Get images from current gallery directory (respects folder hierarchy)
        current_dir = validate_gallery_path(relative_path)
        gallery_images = _collect_all_image_paths_in_dir(current_dir, exclude_dirs={'trash'})
        images = sorted(list(gallery_images))

        if not images:
            return jsonify({'error': 'No images found'}), 404

        # Sync images (ensures all images have metadata)
        db.sync_images(images)

        # Select least recently viewed image
        selected_image = db.get_least_recently_viewed(images)

        # Only record view if not preloading
        if not preload:
            db.record_view(selected_image)

        # Construct relative path from gallery root to image
        selected_path = Path(selected_image)
        gallery_root_path = Path(gallery_root).resolve()
        relative_to_gallery = selected_path.relative_to(gallery_root_path)

        # Get filename for display
        image_name = relative_to_gallery.name

        return jsonify({
            'image_url': f'/image/{relative_to_gallery}',
            'image_name': image_name,
            'image_path': str(relative_to_gallery)  # Full relative path for operations
        })

    @app.route('/trash', methods=['POST'])
    def trash():
        """Move image to trash."""
        data = request.get_json()
        image_name = data.get('image_name')
        relative_path = request.args.get('path', '')

        if not image_name:
            return jsonify({'error': 'No image specified'}), 400

        current_dir = validate_gallery_path(relative_path)

        file_ops = FileOperations(str(current_dir), gallery_root=gallery_root)
        image_path = current_dir / image_name

        if not image_path.exists():
            return jsonify({'error': 'Image not found'}), 404

        try:
            # Move to trash and get new path
            trash_path = file_ops.move_to_trash(str(image_path))

            # Record in database
            db.add_to_trash(trash_path, str(image_path))

            return jsonify({'success': True})
        except Exception as e:
            app.logger.error(f"Error moving to trash: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/trash-view')
    def trash_view():
        """View images in trash."""
        # Sync trash folder with database (recovers from database deletion)
        trash_dir = Path(gallery_root) / "trash"
        db.sync_trash_folder(str(trash_dir), gallery_root)

        # Get trashed images from database
        trashed_images = db.list_trashed_images()

        # Extract just the filenames and paths for template
        trash_items = []
        for item in trashed_images:
            trash_path = Path(item['trash_path'])
            # Get relative path from trash folder
            try:
                rel_path = trash_path.relative_to(Path(gallery_root) / "trash")
                display_path = str(rel_path)
            except ValueError:
                display_path = trash_path.name

            trash_items.append({
                'path': display_path,
                'original': item['original_path'],
                'trashed_at': item['trashed_at']
            })

        return render_template(
            'trash.html',
            images=trash_items,
            image_count=len(trash_items)
        )

    @app.route('/trash/thumbnail/<path:relative_path>')
    def trash_thumbnail(relative_path):
        """Serve thumbnail for a trashed image."""
        trash_dir = Path(gallery_root) / "trash"
        image_path = trash_dir / relative_path

        if not image_path.exists():
            abort(404)

        # Get image modification time for cache validation
        image_mtime = os.path.getmtime(str(image_path))
        last_modified = datetime.fromtimestamp(image_mtime, timezone.utc)

        # Check if client has a cached version
        if_modified_since = request.headers.get('If-Modified-Since')
        if if_modified_since:
            try:
                # Parse client's cached timestamp
                client_mtime = datetime.strptime(if_modified_since, '%a, %d %b %Y %H:%M:%S GMT')
                # If file hasn't been modified, return 304 Not Modified
                if last_modified <= client_mtime:
                    return make_response('', 304)
            except ValueError:
                pass  # Invalid date format, ignore

        # Generate or retrieve thumbnail
        try:
            thumbnail_data = thumbnail_service.get_or_create_thumbnail(str(image_path))
            response = make_response(send_file(
                io.BytesIO(thumbnail_data),
                mimetype='image/jpeg',
                as_attachment=False
            ))

            # Set caching headers
            response.headers['Last-Modified'] = last_modified.strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.headers['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'

            return response
        except Exception as e:
            app.logger.error(f"Error generating thumbnail: {e}")
            abort(500)

    @app.route('/trash/restore', methods=['POST'])
    def restore_from_trash():
        """Restore an image from trash to its original location."""
        try:
            data = request.get_json()
            relative_trash_path = data.get('trash_path')

            if not relative_trash_path:
                return jsonify({'error': 'No trash path provided'}), 400

            # Construct full trash path and resolve it (to handle symlinks like /var -> /private/var on macOS)
            trash_path = str((Path(gallery_root) / "trash" / relative_trash_path).resolve())

            # Get trash record from database
            trash_item = db.get_trash_item(trash_path)
            if not trash_item:
                return jsonify({'error': 'Image not found in trash database'}), 404

            original_path = trash_item['original_path']

            # Verify trash file exists
            if not Path(trash_path).exists():
                return jsonify({'error': 'Trash file not found on disk'}), 404

            # Create original directory if needed
            Path(original_path).parent.mkdir(parents=True, exist_ok=True)

            # Move file back to original location
            import shutil
            shutil.move(trash_path, original_path)

            # Remove trash record from database
            db.remove_from_trash(trash_path)

            # Clean up empty subdirectories in trash
            trash_dir = Path(gallery_root) / "trash"
            try:
                parent_dir = Path(trash_path).parent
                while parent_dir != trash_dir and parent_dir.exists():
                    if not any(parent_dir.iterdir()):
                        parent_dir.rmdir()
                        parent_dir = parent_dir.parent
                    else:
                        break
            except OSError:
                pass

            return jsonify({'success': True, 'original_path': original_path})
        except Exception as e:
            app.logger.error(f"Error restoring from trash: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/trash/delete-all', methods=['POST'])
    def delete_all_trash():
        """Permanently delete all files in trash."""
        try:
            # Get all trashed images from database
            trashed_images = db.list_trashed_images()

            for item in trashed_images:
                trash_path = item['trash_path']

                # Delete physical file
                if Path(trash_path).exists():
                    Path(trash_path).unlink()

                # Clean up database records
                db.delete_thumbnail_record(trash_path)
                db.delete_metadata_record(trash_path)
                db.remove_from_trash(trash_path)

            deleted_count = len(trashed_images)

            # Clean up empty subdirectories in trash
            trash_dir = Path(gallery_root) / "trash"
            if trash_dir.exists():
                for root, dirs, files in os.walk(trash_dir, topdown=False):
                    for dir_name in dirs:
                        dir_path = Path(root) / dir_name
                        try:
                            if not any(dir_path.iterdir()):
                                dir_path.rmdir()
                        except OSError:
                            pass

            return jsonify({'success': True, 'deleted': deleted_count})
        except Exception as e:
            app.logger.error(f"Error deleting trash: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/metadata/delete', methods=['POST'])
    def delete_metadata():
        """Delete the database file to clear all metadata."""
        try:
            db_path_obj = Path(app.config['DB_PATH'])

            if db_path_obj.exists():
                # Delete the database file
                db_path_obj.unlink()
                return jsonify({'success': True, 'message': 'Database deleted successfully'})
            else:
                return jsonify({'success': True, 'message': 'Database file does not exist'})
        except Exception as e:
            app.logger.error(f"Error deleting database: {e}")
            return jsonify({'error': str(e)}), 500

    return app


def main():
    """Main entry point for the application."""
    import argparse
    import signal
    import sys

    parser = argparse.ArgumentParser(description='Image Trashing Service')
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8000,
        help='Port to bind to (default: 8000)'
    )
    parser.add_argument(
        '--gallery-root',
        default='.',
        help='Root directory for image gallery (default: current directory)'
    )

    args = parser.parse_args()

    gallery_root = Path(args.gallery_root).resolve()
    db_path = str(gallery_root / '.igallery.db')

    app = create_app(
        gallery_root=str(gallery_root),
        db_path=db_path
    )

    print(f"Starting Image Trashing Service on http://{args.host}:{args.port}")
    print(f"Gallery root: {gallery_root}")
    print("Press Ctrl+C to stop\n")

    # Suppress Flask's shutdown messages
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    try:
        app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
    except (KeyboardInterrupt, SystemExit):
        print("\nShutdown complete")
        sys.exit(0)


if __name__ == '__main__':
    main()
