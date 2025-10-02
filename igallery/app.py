"""Flask web application for iGallery."""

import io
import os
import random
from pathlib import Path
from flask import Flask, render_template, send_file, request, jsonify, abort

from igallery.database import Database
from igallery.thumbnail_service import ThumbnailService
from igallery.file_operations import FileOperations


def _collect_all_image_paths(gallery_root: str) -> tuple[set[str], set[str]]:
    """Recursively collect all image paths in gallery and trash.

    Returns:
        Tuple of (gallery_images, trash_images)
    """
    gallery_images = set()
    trash_images = set()
    gallery_path = Path(gallery_root).resolve()
    trash_path = gallery_path / "trash"

    # Collect gallery images (excluding trash)
    for root, dirs, files in os.walk(gallery_path):
        # Skip trash directory
        dirs[:] = [d for d in dirs if d != 'trash']

        for file in files:
            file_path = Path(root) / file
            if ThumbnailService.is_image_file(str(file_path)):
                gallery_images.add(str(file_path.resolve()))

    # Collect trash images
    if trash_path.exists():
        for root, dirs, files in os.walk(trash_path):
            for file in files:
                file_path = Path(root) / file
                if ThumbnailService.is_image_file(str(file_path)):
                    trash_images.add(str(file_path.resolve()))

    return gallery_images, trash_images


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
    thumbnail_service = ThumbnailService(db_path)

    # Cleanup orphaned records on startup
    print("Cleaning up orphaned database records...")
    valid_gallery, valid_trash = _collect_all_image_paths(gallery_root)
    orphaned_thumbs, orphaned_meta, orphaned_trash = db.cleanup_orphaned_records(valid_gallery, valid_trash)
    if orphaned_thumbs or orphaned_meta or orphaned_trash:
        print(f"Removed {orphaned_thumbs} orphaned thumbnails, {orphaned_meta} orphaned metadata, and {orphaned_trash} orphaned trash records")

    @app.route('/')
    def index():
        """Gallery index page with thumbnail grid."""
        # Get path parameter for subdirectory navigation
        relative_path = request.args.get('path', '')
        current_dir = Path(gallery_root) / relative_path

        # Security check
        try:
            current_dir = current_dir.resolve()
            gallery_root_resolved = Path(gallery_root).resolve()
            if not str(current_dir).startswith(str(gallery_root_resolved)):
                abort(403)
        except Exception:
            abort(400)

        file_ops = FileOperations(str(current_dir), gallery_root=gallery_root)

        # Pagination
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))

        images, total_pages = file_ops.get_page(page, per_page)
        subdirectories = file_ops.list_subdirectories()

        # Build breadcrumbs
        breadcrumbs = []
        if relative_path:
            parts = Path(relative_path).parts
            for i, part in enumerate(parts):
                path = '/'.join(parts[:i+1])
                breadcrumbs.append({'name': part, 'path': path})

        return render_template(
            'index.html',
            images=[Path(img).name for img in images],
            subdirectories=subdirectories,
            page=page,
            total_pages=total_pages,
            current_path=relative_path,
            breadcrumbs=breadcrumbs,
            has_parent=relative_path != ''
        )

    @app.route('/thumbnail/<path:image_name>')
    def thumbnail(image_name):
        """Serve thumbnail for an image."""
        relative_path = request.args.get('path', '')
        current_dir = Path(gallery_root) / relative_path

        # Security check
        try:
            current_dir = current_dir.resolve()
            gallery_root_resolved = Path(gallery_root).resolve()
            if not str(current_dir).startswith(str(gallery_root_resolved)):
                abort(403)
        except Exception:
            abort(400)

        image_path = current_dir / image_name

        if not image_path.exists():
            abort(404)

        # Generate or retrieve thumbnail
        try:
            thumbnail_data = thumbnail_service.get_or_create_thumbnail(str(image_path))
            return send_file(
                io.BytesIO(thumbnail_data),
                mimetype='image/jpeg',
                as_attachment=False
            )
        except Exception as e:
            app.logger.error(f"Error generating thumbnail: {e}")
            abort(500)

    @app.route('/image/<path:image_name>')
    def image(image_name):
        """Serve full-size image."""
        relative_path = request.args.get('path', '')
        current_dir = Path(gallery_root) / relative_path

        # Security check
        try:
            current_dir = current_dir.resolve()
            gallery_root_resolved = Path(gallery_root).resolve()
            if not str(current_dir).startswith(str(gallery_root_resolved)):
                abort(403)
        except Exception:
            abort(400)

        image_path = current_dir / image_name

        if not image_path.exists():
            abort(404)

        # Record view
        db.record_view(str(image_path))

        return send_file(str(image_path))

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
        """Get next image for carousel (random or slideshow mode)."""
        mode = request.args.get('mode', 'random')

        # Get ALL images from entire gallery (not just current directory)
        gallery_images, _ = _collect_all_image_paths(gallery_root)
        images = sorted(list(gallery_images))

        if not images:
            return jsonify({'error': 'No images found'}), 404

        # Select image based on mode
        if mode == 'random':
            selected_image = random.choice(images)
        elif mode == 'slideshow':
            selected_image = db.get_least_recently_viewed(images)
        else:
            selected_image = images[0]

        # Record view
        db.record_view(selected_image)

        # Construct relative path from gallery root to image
        selected_path = Path(selected_image)
        gallery_root_path = Path(gallery_root).resolve()
        relative_to_gallery = selected_path.relative_to(gallery_root_path)

        # Split into directory path and filename
        image_name = relative_to_gallery.name
        if relative_to_gallery.parent != Path('.'):
            relative_dir = str(relative_to_gallery.parent)
        else:
            relative_dir = ''

        return jsonify({
            'image_url': f'/image/{image_name}?path={relative_dir}',
            'image_name': image_name,
            'image_path': relative_dir  # Directory path for trash operation
        })

    @app.route('/trash', methods=['POST'])
    def trash():
        """Move image to trash."""
        data = request.get_json()
        image_name = data.get('image_name')
        relative_path = request.args.get('path', '')

        if not image_name:
            return jsonify({'error': 'No image specified'}), 400

        current_dir = Path(gallery_root) / relative_path

        # Security check
        try:
            current_dir = current_dir.resolve()
            gallery_root_resolved = Path(gallery_root).resolve()
            if not str(current_dir).startswith(str(gallery_root_resolved)):
                abort(403)
        except Exception:
            abort(400)

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

        # Generate or retrieve thumbnail
        try:
            thumbnail_data = thumbnail_service.get_or_create_thumbnail(str(image_path))
            return send_file(
                io.BytesIO(thumbnail_data),
                mimetype='image/jpeg',
                as_attachment=False
            )
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

    return app


def main():
    """Main entry point for the application."""
    import argparse

    parser = argparse.ArgumentParser(description='iGallery - Image Gallery Service')
    parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='Host to bind to (default: 127.0.0.1)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Port to bind to (default: 5000)'
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

    print(f"Starting iGallery on http://{args.host}:{args.port}")
    print(f"Gallery root: {gallery_root}")

    app.run(host=args.host, port=args.port, debug=True)


if __name__ == '__main__':
    main()
