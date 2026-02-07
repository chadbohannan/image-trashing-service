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
    gallery_roots: list[str] = None,
    db_paths: list[str] = None,
    # Legacy single-root interface for backward compat (e.g. tests)
    gallery_root: str = None,
    db_path: str = None,
):
    """Create and configure Flask application.

    Args:
        gallery_roots: List of root directories for image galleries
        db_paths: List of paths to SQLite databases (one per root)
        gallery_root: Single gallery root (legacy, use gallery_roots instead)
        db_path: Single db path (legacy, use db_paths instead)

    Returns:
        Configured Flask application
    """
    # Normalize to list form
    if gallery_roots is None:
        gallery_roots = [gallery_root or "."]
    if db_paths is None:
        if db_path:
            db_paths = [db_path]
        else:
            db_paths = [str(Path(r).resolve() / '.igallery.db') for r in gallery_roots]

    app = Flask(__name__)

    # Build roots registry
    roots = []
    for i, (root_path, root_db_path) in enumerate(zip(gallery_roots, db_paths)):
        resolved = str(Path(root_path).resolve())
        db = Database(root_db_path)
        roots.append({
            'index': i,
            'name': Path(resolved).name,
            'path': resolved,
            'db_path': root_db_path,
            'db': db,
            'thumbnail_service': ThumbnailService(db),
        })

    # Store config for backward compat
    app.config['GALLERY_ROOT'] = roots[0]['path']
    app.config['GALLERY_ROOTS'] = roots
    app.config['DB_PATH'] = roots[0]['db_path']

    # Track cleanup status per root
    cleanup_status = {'in_progress': False, 'last_run': None}

    def cleanup_orphaned_records_async():
        """Background task to cleanup orphaned database records for all roots."""
        if cleanup_status['in_progress']:
            return

        cleanup_status['in_progress'] = True
        try:
            for root_info in roots:
                gallery_path = Path(root_info['path']).resolve()
                if not gallery_path.exists():
                    continue  # Skip missing roots to avoid purging valid records
                trash_path = gallery_path / "trash"
                root_db = root_info['db']

                valid_gallery = _collect_all_image_paths_in_dir(gallery_path, exclude_dirs={'trash'})
                valid_trash = _collect_all_image_paths_in_dir(trash_path) if trash_path.exists() else set()

                orphaned_thumbs, orphaned_meta, orphaned_trash = root_db.cleanup_orphaned_records(
                    valid_gallery, valid_trash
                )

                if orphaned_thumbs or orphaned_meta or orphaned_trash:
                    print(f"Cleanup [{root_info['name']}]: Removed {orphaned_thumbs} thumbnails, {orphaned_meta} metadata, {orphaned_trash} trash records")

            import time
            cleanup_status['last_run'] = time.time()
        except Exception as e:
            print(f"Background cleanup error: {e}")
        finally:
            cleanup_status['in_progress'] = False

    @app.before_request
    def lazy_cleanup():
        """Trigger cleanup on first request only."""
        if app.config.get('TESTING'):
            return
        if cleanup_status['last_run'] is None and not cleanup_status['in_progress']:
            threading.Thread(target=cleanup_orphaned_records_async, daemon=True).start()

    def get_active_root():
        """Get active gallery root from request's 'root' query param."""
        try:
            idx = int(request.args.get('root', 0))
        except (ValueError, TypeError):
            abort(400, 'Invalid root index')
        if idx < 0 or idx >= len(roots):
            abort(400, 'Invalid root index')
        return roots[idx]

    def get_root_param():
        """Get current root index for URL propagation."""
        try:
            return int(request.args.get('root', 0))
        except (ValueError, TypeError):
            return 0

    def validate_gallery_path(relative_path: str = '', active_root=None) -> Path:
        """Validate and resolve a gallery path.

        Args:
            relative_path: Relative path within gallery
            active_root: Root info dict (if None, resolved from request)

        Returns:
            Resolved Path object

        Raises:
            403: Path traversal attempt
            400: Invalid path
        """
        if active_root is None:
            active_root = get_active_root()
        gallery_root = active_root['path']
        try:
            current_dir = (Path(gallery_root) / relative_path).resolve()
            gallery_root_resolved = Path(gallery_root).resolve()
            if not str(current_dir).startswith(str(gallery_root_resolved)):
                abort(403)
            return current_dir
        except Exception:
            abort(400)

    def _roots_with_availability():
        """Return roots list with current availability status."""
        def _is_available(path):
            try:
                # Try to actually read the directory; Path.exists() can
                # return False for FUSE/encrypted mount points even when
                # they are accessible.
                next(Path(path).iterdir(), None)
                return True
            except (PermissionError, OSError):
                return False

        return [
            {**r, 'available': _is_available(r['path'])}
            for r in roots
        ]

    @app.route('/')
    def index():
        """Gallery index page with thumbnail grid."""
        active = get_active_root()
        root_index = get_root_param()
        gallery_root = active['path']
        try:
            next(Path(gallery_root).iterdir(), None)
            root_available = True
        except (PermissionError, OSError):
            root_available = False

        if not root_available:
            return render_template(
                'index.html',
                items=[],
                page=1,
                per_page=20,
                total_pages=0,
                current_path='',
                breadcrumbs=[],
                has_parent=False,
                roots=_roots_with_availability(),
                root_index=root_index,
                root_unavailable=True,
            )

        relative_path = request.args.get('path', '')
        current_dir = validate_gallery_path(relative_path, active)

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
            has_parent=relative_path != '',
            roots=_roots_with_availability(),
            root_index=root_index,
        )

    @app.route('/thumbnail/<path:image_path>')
    def thumbnail(image_path):
        """Serve thumbnail for an image."""
        active = get_active_root()
        full_image_path = validate_gallery_path(image_path, active)

        if not full_image_path.exists():
            abort(404)

        # Get image modification time for cache validation
        image_mtime = os.path.getmtime(str(full_image_path))
        last_modified = datetime.fromtimestamp(image_mtime, timezone.utc)

        # Check if client has a cached version
        if_modified_since = request.headers.get('If-Modified-Since')
        if if_modified_since:
            try:
                client_mtime = datetime.strptime(if_modified_since, '%a, %d %b %Y %H:%M:%S GMT')
                if last_modified <= client_mtime:
                    return make_response('', 304)
            except ValueError:
                pass

        # Generate or retrieve thumbnail
        try:
            thumbnail_data = active['thumbnail_service'].get_or_create_thumbnail(str(full_image_path))
            response = make_response(send_file(
                io.BytesIO(thumbnail_data),
                mimetype='image/jpeg',
                as_attachment=False
            ))

            response.headers['Last-Modified'] = last_modified.strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.headers['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'

            return response
        except Exception as e:
            app.logger.error(f"Error generating thumbnail: {e}")
            abort(500)

    @app.route('/image/<path:image_path>')
    def image(image_path):
        """Serve full-size image."""
        active = get_active_root()
        preload = request.args.get('preload', 'false') == 'true'
        full_image_path = validate_gallery_path(image_path, active)

        if not full_image_path.exists():
            abort(404)

        # Record view only if not preloading
        if not preload:
            active['db'].record_view(str(full_image_path))

        return send_file(str(full_image_path))

    @app.route('/carousel')
    def carousel():
        """Carousel page."""
        relative_path = request.args.get('path', '')
        root_index = get_root_param()

        return render_template(
            'carousel.html',
            current_path=relative_path,
            roots=_roots_with_availability(),
            root_index=root_index,
        )

    @app.route('/carousel/next')
    def carousel_next():
        """Get next image for carousel (slideshow mode)."""
        active = get_active_root()
        gallery_root = active['path']
        db = active['db']

        relative_path = request.args.get('path', '')
        preload = request.args.get('preload', 'false') == 'true'

        current_dir = validate_gallery_path(relative_path, active)
        gallery_images = _collect_all_image_paths_in_dir(current_dir, exclude_dirs={'trash'})
        images = sorted(list(gallery_images))

        if not images:
            return jsonify({'error': 'No images found'}), 404

        db.sync_images(images)
        selected_image = db.get_least_recently_viewed(images)

        if not preload:
            db.record_view(selected_image)

        selected_path = Path(selected_image)
        gallery_root_path = Path(gallery_root).resolve()
        relative_to_gallery = selected_path.relative_to(gallery_root_path)

        image_name = relative_to_gallery.name

        return jsonify({
            'image_url': f'/image/{relative_to_gallery}?root={get_root_param()}',
            'image_name': image_name,
            'image_path': str(relative_to_gallery)
        })

    @app.route('/carousel/random')
    def carousel_random():
        """Get random image for carousel (random mode)."""
        active = get_active_root()
        gallery_root = active['path']
        db = active['db']

        relative_path = request.args.get('path', '')
        preload = request.args.get('preload', 'false') == 'true'

        current_dir = validate_gallery_path(relative_path, active)
        gallery_images = _collect_all_image_paths_in_dir(current_dir, exclude_dirs={'trash'})
        images = sorted(list(gallery_images))

        if not images:
            return jsonify({'error': 'No images found'}), 404

        db.sync_images(images)
        selected_image = db.get_random_image(images)

        if not preload:
            db.record_view(selected_image)

        selected_path = Path(selected_image)
        gallery_root_path = Path(gallery_root).resolve()
        relative_to_gallery = selected_path.relative_to(gallery_root_path)

        image_name = relative_to_gallery.name

        return jsonify({
            'image_url': f'/image/{relative_to_gallery}?root={get_root_param()}',
            'image_name': image_name,
            'image_path': str(relative_to_gallery)
        })

    @app.route('/trash', methods=['POST'])
    def trash():
        """Move image to trash."""
        active = get_active_root()
        gallery_root = active['path']
        db = active['db']

        data = request.get_json()
        image_name = data.get('image_name')
        relative_path = request.args.get('path', '')

        if not image_name:
            return jsonify({'error': 'No image specified'}), 400

        current_dir = validate_gallery_path(relative_path, active)

        file_ops = FileOperations(str(current_dir), gallery_root=gallery_root)
        image_path = current_dir / image_name

        if not image_path.exists():
            return jsonify({'error': 'Image not found'}), 404

        try:
            trash_path = file_ops.move_to_trash(str(image_path))
            db.add_to_trash(trash_path, str(image_path))
            return jsonify({'success': True})
        except Exception as e:
            app.logger.error(f"Error moving to trash: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/trash-view')
    def trash_view():
        """View images in trash."""
        active = get_active_root()
        gallery_root = active['path']
        db = active['db']
        root_index = get_root_param()

        trash_dir = Path(gallery_root) / "trash"
        db.sync_trash_folder(str(trash_dir), gallery_root)

        trashed_images = db.list_trashed_images()

        trash_items = []
        for item in trashed_images:
            trash_path = Path(item['trash_path'])
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
            image_count=len(trash_items),
            roots=_roots_with_availability(),
            root_index=root_index,
        )

    @app.route('/trash/thumbnail/<path:relative_path>')
    def trash_thumbnail(relative_path):
        """Serve thumbnail for a trashed image."""
        active = get_active_root()
        trash_dir = Path(active['path']) / "trash"
        image_path = trash_dir / relative_path

        if not image_path.exists():
            abort(404)

        image_mtime = os.path.getmtime(str(image_path))
        last_modified = datetime.fromtimestamp(image_mtime, timezone.utc)

        if_modified_since = request.headers.get('If-Modified-Since')
        if if_modified_since:
            try:
                client_mtime = datetime.strptime(if_modified_since, '%a, %d %b %Y %H:%M:%S GMT')
                if last_modified <= client_mtime:
                    return make_response('', 304)
            except ValueError:
                pass

        try:
            thumbnail_data = active['thumbnail_service'].get_or_create_thumbnail(str(image_path))
            response = make_response(send_file(
                io.BytesIO(thumbnail_data),
                mimetype='image/jpeg',
                as_attachment=False
            ))

            response.headers['Last-Modified'] = last_modified.strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.headers['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'

            return response
        except Exception as e:
            app.logger.error(f"Error generating thumbnail: {e}")
            abort(500)

    @app.route('/trash/image/<path:relative_path>')
    def trash_image(relative_path):
        """Serve full-size trashed image."""
        active = get_active_root()
        trash_dir = Path(active['path']) / "trash"
        image_path = trash_dir / relative_path

        if not image_path.exists():
            abort(404)

        return send_file(str(image_path))

    @app.route('/trash/restore', methods=['POST'])
    def restore_from_trash():
        """Restore an image from trash to its original location."""
        active = get_active_root()
        gallery_root = active['path']
        db = active['db']

        try:
            data = request.get_json()
            relative_trash_path = data.get('trash_path')

            if not relative_trash_path:
                return jsonify({'error': 'No trash path provided'}), 400

            trash_path = str((Path(gallery_root) / "trash" / relative_trash_path).resolve())

            trash_item = db.get_trash_item(trash_path)
            if not trash_item:
                return jsonify({'error': 'Image not found in trash database'}), 404

            original_path = trash_item['original_path']

            if not Path(trash_path).exists():
                return jsonify({'error': 'Trash file not found on disk'}), 404

            Path(original_path).parent.mkdir(parents=True, exist_ok=True)

            import shutil
            shutil.move(trash_path, original_path)

            db.remove_from_trash(trash_path)

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
        active = get_active_root()
        gallery_root = active['path']
        db = active['db']

        try:
            trashed_images = db.list_trashed_images()

            for item in trashed_images:
                trash_path = item['trash_path']

                if Path(trash_path).exists():
                    Path(trash_path).unlink()

                db.delete_thumbnail_record(trash_path)
                db.delete_metadata_record(trash_path)
                db.remove_from_trash(trash_path)

            deleted_count = len(trashed_images)

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
        active = get_active_root()

        try:
            db_path_obj = Path(active['db_path'])

            if db_path_obj.exists():
                db_path_obj.unlink()
                return jsonify({'success': True, 'message': 'Database deleted successfully'})
            else:
                return jsonify({'success': True, 'message': 'Database file does not exist'})
        except Exception as e:
            app.logger.error(f"Error deleting database: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/folder/delete', methods=['POST'])
    def delete_folder():
        """Delete an empty folder from the gallery."""
        active = get_active_root()

        try:
            data = request.get_json()
            folder_name = data.get('folder_name')
            relative_path = request.args.get('path', '')

            if not folder_name:
                return jsonify({'error': 'No folder specified'}), 400

            current_dir = validate_gallery_path(relative_path, active)
            folder_path = current_dir / folder_name

            if not folder_path.exists():
                return jsonify({'error': 'Folder not found'}), 404

            if not folder_path.is_dir():
                return jsonify({'error': 'Not a directory'}), 400

            try:
                items = list(folder_path.iterdir())
                if items:
                    return jsonify({'error': 'Folder is not empty'}), 400
            except PermissionError:
                return jsonify({'error': 'Permission denied'}), 403

            folder_path.rmdir()

            return jsonify({'success': True})
        except Exception as e:
            app.logger.error(f"Error deleting folder: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/move-up', methods=['POST'])
    def move_up():
        """Move an image up one folder in the directory tree."""
        active = get_active_root()
        gallery_root = active['path']
        db = active['db']

        try:
            data = request.get_json()
            image_path = data.get('image_path')

            if not image_path:
                return jsonify({'error': 'No image path specified'}), 400

            full_image_path = validate_gallery_path(image_path, active)

            if not full_image_path.exists():
                return jsonify({'error': 'Image not found'}), 404

            if not full_image_path.is_file():
                return jsonify({'error': 'Not a file'}), 400

            file_ops = FileOperations(str(full_image_path.parent), gallery_root=gallery_root)
            new_path, success = file_ops.move_up_folder(str(full_image_path))

            if not success:
                return jsonify({'error': 'Image is already at gallery root'}), 400

            old_path_str = str(full_image_path.resolve())
            db.update_image_path(old_path_str, new_path)

            return jsonify({'success': True, 'new_path': new_path})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            app.logger.error(f"Error moving file up: {e}")
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
        action='append',
        default=None,
        help='Root directory for image gallery (can be specified multiple times)'
    )

    args = parser.parse_args()

    gallery_root_list = args.gallery_root or ['.']
    gallery_roots = [str(Path(r).resolve()) for r in gallery_root_list]
    db_paths = [str(Path(r) / '.igallery.db') for r in gallery_roots]

    app = create_app(
        gallery_roots=gallery_roots,
        db_paths=db_paths,
    )

    print(f"Starting Image Trashing Service on http://{args.host}:{args.port}")
    if len(gallery_roots) == 1:
        print(f"Gallery root: {gallery_roots[0]}")
    else:
        print(f"Gallery roots ({len(gallery_roots)}):")
        for i, r in enumerate(gallery_roots):
            print(f"  [{i}] {r}")
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
