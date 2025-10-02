# iGallery

A web-based image gallery service with intelligent slideshow features, thumbnail caching, and image organization capabilities.

## Features

- **Web Interface**: Clean, responsive web UI for browsing images
- **Subfolder Navigation**: Browse through nested directories with breadcrumb navigation
- **Paginated Thumbnails**: Efficient thumbnail generation with SQLite BLOB storage
- **Carousel Modes**:
  - **Random**: Select next image randomly
  - **Slideshow**: Select least recently viewed image (intelligent progression)
- **Image Management**: Move unwanted images to trash with one click
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

Run iGallery in any directory containing images:

```bash
igallery
```

Or specify a directory:

```bash
igallery --gallery-root /path/to/your/photos
```

### Command-line options

```bash
igallery --help
```

Options:
- `--host`: Host to bind to (default: 127.0.0.1)
- `--port`: Port to bind to (default: 5000)
- `--gallery-root`: Root directory for image gallery (default: current directory)

### Accessing the gallery

Open your browser and navigate to:
- Gallery view: `http://127.0.0.1:5000/`
- Carousel view: `http://127.0.0.1:5000/carousel`
- Trash view: `http://127.0.0.1:5000/trash-view`

## Features in Detail

### Gallery View

- **Thumbnail Grid**: View all images in the current directory as thumbnails
- **Folder Navigation**: Click on folders to navigate into subdirectories
- **Parent Directory**: Navigate back up the directory tree
- **Pagination**: Automatically paginated for directories with many images
- **Lightbox**: Click any thumbnail to view the full-size image
- **Trash**: Hover over thumbnails and click the trash icon to move images to `./trash`

### Carousel View

The carousel provides a focused viewing experience with two modes:

#### Random Mode
Selects the next image randomly from the current directory.

#### Slideshow Mode
Intelligently selects the least recently viewed image, ensuring you see all images before repeating. Perfect for reviewing large collections without missing any images.

#### Controls
- **Next Image**: Load the next image based on selected mode
- **Autoplay**: Automatically advance images at a configurable interval
- **Mode Toggle**: Switch between Random and Slideshow modes
- **Trash**: Move the current image to trash and advance to the next

#### Keyboard Shortcuts
- `→` or `Space`: Next image
- `P`: Toggle autoplay
- `R`: Switch to random mode
- `S`: Switch to slideshow mode
- `Delete`: Move current image to trash
- `Esc`: Close lightbox (in gallery view)

## Technical Details

### Database

iGallery uses SQLite to store:
- **Thumbnail cache**: Stores thumbnail image data as BLOBs with modification time tracking
- **View history**: Tracks when each image was last viewed and total view count
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
