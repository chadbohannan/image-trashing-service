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
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Quick Start

The `run.py` script automatically sets up the virtual environment and dependencies:

```bash
# Clone the repository
git clone <repository-url>
cd image-trashing-service

# Run with default settings (current directory)
python3 run.py

# Or specify a gallery directory
python3 run.py /path/to/your/photos
```

The script will:
1. Create a `.venv` virtual environment (if needed)
2. Install dependencies automatically
3. Start the web server
4. Display local and network access URLs

### Manual Installation

If you prefer manual setup:

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# Run the application
python -m igallery.app --gallery-root /path/to/photos
```

## Usage

### Starting the server

Simply run:

```bash
python3 run.py images/
```

You'll see output like:

```
============================================================
Image Trashing Service
============================================================
Gallery: /Users/you/photos

Access URLs:
  Local:   http://localhost:8000
  Network: http://192.168.1.17:8000

Press Ctrl+C to stop
============================================================
```

### Accessing the web interface

Open your browser and navigate to:
- **Gallery view**: `http://localhost:8000/`
- **Carousel view**: `http://localhost:8000/carousel`
- **Trash view**: `http://localhost:8000/trash-view`

For network access from other devices (phones, tablets):
- Use the Network URL shown at startup
- All devices must be on the same local network

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
image-trashing-service/
├── igallery/                   # Main application package
│   ├── __init__.py
│   ├── app.py                  # Flask application and routes
│   ├── database.py             # SQLite database management
│   ├── thumbnail_service.py    # Thumbnail generation and caching
│   ├── file_operations.py      # File system operations
│   └── templates/
│       ├── base.html           # Base template with navigation
│       ├── index.html          # Gallery view
│       ├── carousel.html       # Carousel view
│       └── trash.html          # Trash management view
├── tests/
│   ├── test_app.py
│   ├── test_database.py
│   ├── test_thumbnail_service.py
│   ├── test_file_operations.py
│   └── test_integration.py
├── run.py                      # Simple launcher script
├── pyproject.toml              # Python package configuration
├── REQUIREMENTS.md             # Detailed requirements and known issues
└── README.md
```

### Architecture

The application follows a modular architecture:

1. **Database Layer** (`database.py`): Handles all SQLite operations for caching and metadata
2. **Service Layer** (`thumbnail_service.py`, `file_operations.py`): Business logic for thumbnails and file operations
3. **Web Layer** (`app.py`): Flask routes and request handling
4. **Presentation Layer** (`templates/`): Jinja2 templates with embedded CSS and JavaScript

## Security Notes

⚠️ **This tool is designed for local/trusted network use only.**

- **No authentication**: Anyone with network access can view and trash images
- **No encryption**: All traffic is unencrypted HTTP
- Path traversal protection on all file operations
- Files are served only from within the configured gallery root
- Trash folder is excluded from directory listings

**Recommended Use:**
- Run on localhost only (use `127.0.0.1` instead of `0.0.0.0` in app.py if concerned)
- Use on trusted local networks only
- Do not expose to the internet

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
