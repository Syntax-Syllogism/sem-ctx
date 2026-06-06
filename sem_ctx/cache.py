import os
import json
import hashlib
import tempfile
from pathlib import Path

def get_cache_dir() -> Path:
    """
    Returns the platform-appropriate global cache directory.
    Uses LOCALAPPDATA on Windows and ~/.cache/ on other platforms.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "sem-ctx" / "Cache"
    return Path.home() / ".cache" / "sem-ctx"

def get_cache_file_path(target_dir: Path) -> Path:
    """
    Computes a SHA-256 hash of the resolved absolute path of the target directory
    and returns the corresponding cache file path.
    """
    abs_path_str = str(target_dir.resolve())
    path_hash = hashlib.sha256(abs_path_str.encode("utf-8")).hexdigest()
    return get_cache_dir() / f"{path_hash}.json"

def load_cache(target_dir: Path) -> dict:
    """
    Loads and returns the cache dictionary for a given target directory.
    Returns an empty cache schema if the cache file does not exist or is invalid.
    """
    cache_file = get_cache_file_path(target_dir)
    default_schema = {
        "target_dir": str(target_dir.resolve()),
        "last_updated": None,
        "files": {}
    }
    
    if not cache_file.exists():
        return default_schema

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Ensure basic keys exist
            if "files" not in data or "target_dir" not in data:
                return default_schema
            return data
    except Exception:
        # If read/parse fails (e.g. corruption), return the default empty schema
        return default_schema

def save_cache(target_dir: Path, cache_data: dict) -> None:
    """
    Saves the cache dictionary to the appropriate global cache file.
    """
    cache_file = get_cache_file_path(target_dir)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    
    data_to_write = dict(cache_data)
    data_to_write["target_dir"] = str(target_dir.resolve())

    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{cache_file.stem}.",
        suffix=".tmp",
        dir=str(cache_file.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data_to_write, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, cache_file)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

def clear_cache(target_dir: Path) -> bool:
    """
    Deletes the cache file for the specified target directory if it exists.
    Returns True if the file was deleted, False otherwise.
    """
    cache_file = get_cache_file_path(target_dir)
    if cache_file.exists():
        try:
            cache_file.unlink()
            return True
        except Exception:
            pass
    return False
