"""
Tools module for the Research Planning AI Laboratory.
Provides functionality for web search and file operations.
"""
try:
    # Local PDF workflows should not require the optional online-search stack.
    from .web_search import (
        ArxivSearch,
        fetch_webpage_content
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"arxiv", "feedparser", "bs4"}:
        raise
    ArxivSearch = None
    fetch_webpage_content = None

from .file_operations import (
    safe_read_file,
    safe_write_file,
    load_json_file,
    save_json_file,
    load_yaml_file,
    save_yaml_file,
    load_csv_file,
    save_csv_file,
    create_timestamped_file,
    search_files,
    get_file_info
)

from .pdf_loader import (
    PDFLoaderError,
    PaperChunk,
    load_pdf,
    load_pdf_pages,
    load_papers,
)

__all__ = [
    # Web search
    'ArxivSearch',
    'fetch_webpage_content',
    
    # File operations
    'safe_read_file',
    'safe_write_file',
    'load_json_file',
    'save_json_file',
    'load_yaml_file',
    'save_yaml_file',
    'load_csv_file',
    'save_csv_file',
    'create_timestamped_file',
    'search_files',
    'get_file_info',

    # Local paper loading
    'PDFLoaderError',
    'PaperChunk',
    'load_pdf',
    'load_pdf_pages',
    'load_papers',
]
