# iGallery Requirements

## Overview
A web-based image gallery service with thumbnail viewing, pagination, lightbox display, carousel slideshow, and trash management.

## Core Features

### 1. Gallery View (Grid)
- Display images as thumbnails in a responsive grid
- Show subdirectories as folder icons
- Pagination support with configurable items per page
- Breadcrumb navigation for folder hierarchy
- Trash button on each thumbnail (visible on hover)
- Click thumbnail to open in lightbox

### 2. Lightbox (Image Viewer)
- Full-screen image display
- Navigation controls:
  - Previous/Next arrows for adjacent images
  - Close button (X) to exit lightbox
  - Trash button to move current image to trash
  - Keyboard shortcuts: Arrow keys, Space, Escape, Backspace/Delete
- Cross-page navigation:
  - **CRITICAL**: When on last image of page N and user clicks "next":
    - Load page N+1
    - Display first image of page N+1 in lightbox
    - Update gallery grid in background
  - **CRITICAL**: When on first image of page N and user clicks "previous":
    - Load page N-1
    - Display last image of page N-1 in lightbox
    - Update gallery grid in background
- Disable navigation buttons when at absolute boundaries (first image of first page, last image of last page)
- Record timestamp of image view when displayed

### 3. Carousel (Slideshow)
- Full-screen slideshow mode
- Select least-recently-viewed image from current folder hierarchy
- **CRITICAL**: Carousel must respect current gallery folder context
  - Only show images from current folder and its subdirectories
  - Do NOT show all images from entire gallery root
- Navigation:
  - Next/Previous buttons
  - Auto-play with configurable interval
  - Keyboard shortcuts
- Preloading:
  - Preload next image for faster display
  - **CRITICAL**: Do NOT record view for preloaded images
  - Only record view when user actually sees the image
- Trash support: Delete current image from carousel

### 4. View Tracking
- Track when images are viewed
- Database schema: `image_metadata` table
  - `image_path` (PRIMARY KEY)
  - `last_viewed_at` (REAL timestamp)
- Initialization behavior:
  - **CRITICAL**: New images get `last_viewed_at = file mtime`
  - This prioritizes viewing older files first
  - When actually viewed, update to current timestamp
- Least-recently-viewed algorithm:
  - Sort by `last_viewed_at ASC`
  - Oldest timestamps (including file mtimes) come first
  - Natural sorting handles both viewed and unviewed images

### 5. Trash Management
- Move images to trash (soft delete)
- Preserve folder structure in trash directory
- Database tracking: `trash` table
  - `trash_path` (PRIMARY KEY)
  - `original_path`
  - `trashed_at`
- Trash view page:
  - List all trashed images
  - Restore button to return image to original location
  - Delete all button for permanent deletion
- Cleanup:
  - Remove empty directories after restore/delete
  - Background cleanup of orphaned database records

### 6. Thumbnail Generation
- Generate thumbnails on-demand
- Cache in database as BLOB
- Invalidate on file modification (mtime check)
- Database schema: `thumbnails` table
  - `image_path` (PRIMARY KEY)
  - `thumbnail_data` (BLOB)
  - `created_at`
  - `image_mtime`
  - `image_size`

### 7. Pagination
- Configurable items per page (default: 20)
- Calculate optimal per_page based on screen size
- Page navigation: Previous/Next links
- Current page indicator
- AJAX loading for lightbox page changes (no full page reload)

## Technical Constraints

### Database
- SQLite database: `.igallery.db`
- Located in gallery root directory (same location as images)
- No migrations - clean schema on fresh install
- Tables: `thumbnails`, `image_metadata`, `trash`
- Foreign key relationships not enforced (file-based storage)

### Frontend
- Server-side rendering with Jinja2 templates
- Progressive enhancement with JavaScript
- No external JS frameworks
- AJAX for dynamic updates (lightbox page navigation, trash operations)

### Backend
- Flask web framework
- Python 3.x
- Path validation to prevent directory traversal
- Support for nested folder hierarchies

## User Workflows

### Viewing Images
1. User navigates to gallery (root or subfolder)
2. Grid displays thumbnails + subdirectories
3. User clicks thumbnail → opens lightbox
4. User navigates with arrows/keyboard
5. When reaching page boundary, load next/previous page seamlessly
6. User closes lightbox → returns to gallery grid

### Carousel Slideshow
1. User opens carousel from gallery
2. Carousel shows images only from current folder context
3. Shows least-recently-viewed first (oldest files prioritized)
4. User can trash images directly from carousel
5. Preloaded images don't pollute view tracking

### Managing Trash
1. User trashes image (from grid or lightbox/carousel)
2. Image moves to trash folder (preserving subfolder path)
3. Database records original location
4. User can visit trash view
5. User can restore or permanently delete

## Known Issues to Avoid

### Issue: Carousel showing duplicate images
- **Cause**: Preloading was recording views prematurely
- **Solution**: Add `preload=true` parameter to skip view recording

### Issue: Carousel showing all gallery images instead of subfolder
- **Cause**: Collecting images from gallery root instead of current path
- **Solution**: Use current directory context from `path` parameter

### Issue: Lightbox not loading next page
- **Cause**: Async function not awaited, scope issues with `optimalPerPage`
- **Solution**: Make navigation functions async, await page loads, global variables

### Issue: Using view_count instead of timestamp
- **Cause**: Unnecessary column that doesn't serve the requirements
- **Solution**: Remove `view_count`, use only `last_viewed_at` with mtime initialization
