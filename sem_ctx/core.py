import os
import hashlib
import sys
from pathlib import Path
from sem_ctx.embeddings import generate_embeddings

def compute_file_hash(file_path: Path) -> str:
    """
    Computes the SHA-256 content hash of a file.
    """
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
    except Exception:
        return ""
    return sha256.hexdigest()

def scan_markdown_files(target_dir: Path) -> list[Path]:
    """
    Recursively scans the target directory for markdown files (.md).
    Ignores hidden directories (like .git, .github).
    """
    md_files = []
    resolved_target_dir = target_dir.resolve()
    
    for root, dirs, files in os.walk(resolved_target_dir):
        # In-place modify dirs to skip hidden folders (like .git)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        
        for file in files:
            if file.endswith(".md"):
                md_files.append(Path(root) / file)
                
    return md_files

def incremental_update_index(target_dir: Path, cache_data: dict, return_dirty: bool = False):
    """
    Updates the cache data incrementally by scanning the target directory.
    - Removes deleted files from cache.
    - Identifies new or modified files.
    - Batches embedding generation for new/modified files for max CPU performance.
    """
    resolved_target_dir = target_dir.resolve()
    all_files = scan_markdown_files(resolved_target_dir)
    
    # Keep track of active relative paths on disk
    current_rel_paths = set()
    
    files_to_index = []  # List of tuples (relative_path, absolute_path, mtime, size, hash)
    changed = False
    
    for abs_path in all_files:
        rel_path = str(abs_path.relative_to(resolved_target_dir).as_posix())
        current_rel_paths.add(rel_path)
        
        stat = abs_path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
        
        cached_info = cache_data.get("files", {}).get(rel_path)

        # Fast path: unchanged mtime + size means we skip file reads/hashing.
        if cached_info and cached_info.get("mtime") == mtime and cached_info.get("size") == size:
            continue

        file_hash = compute_file_hash(abs_path)

        # Check if the file is new or modified.
        if not cached_info or cached_info.get("hash") != file_hash:
            files_to_index.append((rel_path, abs_path, mtime, size, file_hash))
        elif cached_info.get("mtime") != mtime or cached_info.get("size") != size:
            # Keep metadata fresh even when content hash is unchanged.
            cache_data["files"][rel_path]["mtime"] = mtime
            cache_data["files"][rel_path]["size"] = size
            changed = True

    # 1. Clean up deleted files from the cache
    cached_rel_paths = list(cache_data.get("files", {}).keys())
    deleted_count = 0
    for rel_path in cached_rel_paths:
        if rel_path not in current_rel_paths:
            del cache_data["files"][rel_path]
            deleted_count += 1
            changed = True
            
    if deleted_count > 0:
        print(f"Removed {deleted_count} deleted file(s) from index.", flush=True, file=sys.stderr)

    # 2. Batch-index new/modified files
    if files_to_index:
        print(f"Indexing {len(files_to_index)} new/modified file(s)...", flush=True, file=sys.stderr)
        
        # Read contents of all files to be indexed
        texts = []
        valid_files = []
        for rel_path, abs_path, mtime, size, file_hash in files_to_index:
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                # Use filename + header + main content to provide richer semantic context
                semantic_text = f"File: {rel_path}\n\n{content}"
                texts.append(semantic_text)
                valid_files.append((rel_path, mtime, size, file_hash))
            except Exception as e:
                print(f"Warning: Failed to read {rel_path}: {e}", flush=True, file=sys.stderr)
        
        # Generate embeddings in one batch
        if texts:
            embeddings = generate_embeddings(texts)
            
            # Map embeddings back to cache
            if "files" not in cache_data:
                cache_data["files"] = {}
                
            for (rel_path, mtime, size, file_hash), vector in zip(valid_files, embeddings):
                cache_data["files"][rel_path] = {
                    "mtime": mtime,
                    "size": size,
                    "hash": file_hash,
                    "embedding": vector
                }
            print("Indexing completed successfully.", flush=True, file=sys.stderr)
            changed = True
            
    if return_dirty:
        return cache_data, changed
    return cache_data

def get_snippet(file_path: Path, query: str, max_len: int = 160) -> str:
    """
    Extracts a concise, query-relevant snippet from a markdown file.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return ""
        
    # Standardize whitespace
    content_clean = " ".join(content.split())
    
    # Try finding query terms to build a relevant window
    query_terms = [term.lower() for term in query.split() if len(term) > 2]
    match_idx = -1
    
    for term in query_terms:
        idx = content_clean.lower().find(term)
        if idx != -1:
            match_idx = idx
            break
            
    if match_idx == -1:
        # Return beginning of file if no query terms found
        snippet = content_clean[:max_len]
        if len(content_clean) > max_len:
            snippet += "..."
        return snippet
        
    # Center window around query match
    start = max(0, match_idx - (max_len // 2))
    end = min(len(content_clean), start + max_len)
    
    # Adjust window if it got pushed
    if end - start < max_len:
        start = max(0, end - max_len)
        
    snippet = content_clean[start:end]
    
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content_clean) else ""
    
    return prefix + snippet.strip() + suffix
