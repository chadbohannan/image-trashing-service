# Image Trashing Service

A web-based image management tool for reviewing and organizing large image collections. Browse images in a gallery view or use the intelligent carousel mode to systematically review images and quickly trash unwanted ones.

## Features

- **Web Interface**: Clean, responsive web UI for browsing images
- **Subfolder Navigation**: Browse through nested directories with breadcrumb navigation
- **Paginated Thumbnails**: Efficient thumbnail generation with SQLite BLOB storage
- **Carousel Mode**: Intelligent slideshow that selects least recently viewed images (ensuring systematic review)
- **Image Trashing**: Move unwanted images to trash with one click from any view
- **Trash Management**: Review trashed images and permanently delete them
- **Keyboard Shortcuts**: Full keyboard support for carousel navigation
- **Database-Backed Thumbnails**: Thumbnails stored as BLOBs in SQLite (no filesystem clutter)
- **View Tracking**: Tracks which images you've viewed for intelligent slideshow ordering
- **Automatic Cleanup**: Removes orphaned database records on startup

## Installation

### Requirements

- Python 3.8 or higher
- pip

### Install from source

```bash
# Clone or navigate to the directory
cd igallery

# Install in development mode
pip install -e .
```

## Usage

### Starting the server

Run the image trashing service from your terminal:

```bash
python run.py
```

Or set a specific gallery directory:

```bash
GALLERY_ROOT=/path/to/your/photos python run.py
```

### Accessing the web interface

Open your browser and navigate to:
- Gallery view: `http://localhost:5001/`
- Carousel view: `http://localhost:5001/carousel`
- Trash view: `http://localhost:5001/trash-view`

For network access from other devices:
- Use your machine's IP: `http://192.168.1.x:5001/`

## Features in Detail

### Gallery View

- **Thumbnail Grid**: View all images in the current directory as thumbnails
- **Folder Navigation**: Click on folders to navigate into subdirectories
- **Parent Directory**: Navigate back up the directory tree
- **Pagination**: Automatically paginated for directories with many images
- **Lightbox**: Click any thumbnail to view the full-size image
- **Trash**: Hover over thumbnails and click the trash icon to move images to `./trash`

### Carousel View

The carousel provides a focused full-screen viewing experience for systematic image review.

#### Intelligent Image Selection
Automatically selects the least recently viewed image, ensuring you see all images in order before repeating. For unviewed images, older images (by file modification time) are shown first. Perfect for reviewing large collections without missing any images.

#### Controls
- **Next/Previous**: Navigate through image history or load new images
- **Autoplay**: Automatically advance images at a configurable interval (default: 3 seconds)
- **Trash**: Move the current image to trash and advance to the next

#### Keyboard Shortcuts
- `→` or `Space`: Next image
- `←`: Previous image (navigates back through history)
- `P`: Toggle autoplay
- `Backspace` or `Delete`: Move current image to trash
- `Esc`: Exit carousel (return to gallery view)

## Technical Details

### Database

The application uses SQLite to store:
- **Thumbnail cache**: Stores thumbnail image data as BLOBs with modification time tracking
- **View history**: Tracks when each image was last viewed (timestamp-based)
- **Trash records**: Tracks trashed images and their original locations
- **Automatic cleanup**: On startup, removes records for images that no longer exist

The database file `.igallery.db` is created in the gallery root directory.

### Thumbnail Generation

- Thumbnails are generated on-demand using Pillow
- Stored as JPEG data in SQLite database (no filesystem pollution)
- Automatically regenerated if source image is modified
- Default size: 300x300 pixels (maintains aspect ratio)
- All thumbnails converted to JPEG for consistent storage

### Supported Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- WebP (.webp)
- GIF (.gif)
- BMP (.bmp)

## Development

### Running Tests

```bash
pytest
```

With coverage:

```bash
pytest --cov=igallery --cov-report=html
```

### Project Structure

```
igallery/
├── igallery/
│   ├── __init__.py
│   ├── app.py                 # Flask application
│   ├── database.py            # SQLite database management
│   ├── thumbnail_service.py   # Thumbnail generation and caching
│   ├── file_operations.py     # File system operations
│   └── templates/
│       ├── base.html
│       ├── index.html         # Gallery view
│       └── carousel.html      # Carousel view
├── tests/
│   ├── test_app.py
│   ├── test_database.py
│   ├── test_thumbnail_service.py
│   ├── test_file_operations.py
│   └── test_integration.py
├── pyproject.toml
└── README.md
```

### Architecture

The application follows a modular architecture:

1. **Database Layer** (`database.py`): Handles all SQLite operations for caching and metadata
2. **Service Layer** (`thumbnail_service.py`, `file_operations.py`): Business logic for thumbnails and file operations
3. **Web Layer** (`app.py`): Flask routes and request handling
4. **Presentation Layer** (`templates/`): Jinja2 templates with embedded CSS and JavaScript

## Security

- Path traversal protection on all file operations
- Files are served only from within the configured gallery root
- Trash folder is excluded from directory listings

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please:
1. Write tests for new features
2. Follow the existing code style
3. Update documentation as needed

## Troubleshooting

### Thumbnails not generating
- Ensure Pillow is installed correctly
- Check that the source images are valid
- Verify write permissions for the gallery root directory (for database)

### Images not appearing
- Check that image files have supported extensions
- Verify file permissions
- Check browser console for errors

### Database errors
- Ensure write permissions for the gallery root directory
- Delete `.igallery.db` to reset (will lose view history and thumbnail cache)

### Large database file
- Thumbnails are stored as BLOBs in the database
- Database size will grow with the number of unique images
- Use SQLite VACUUM command to compact the database if needed:
  ```bash
  sqlite3 .igallery.db "VACUUM;"
  ```
