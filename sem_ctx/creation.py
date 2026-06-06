import re
from pathlib import Path

from sem_ctx.core import get_snippet


TEMPLATE_MARKERS = ("template", "templates", "boilerplate", "scaffold")
ARCHIVE_MARKERS = ("archive", "archived", "done", "completed", "old")


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _normalized_path(rel_path: str) -> str:
    return " ".join(_tokenize(rel_path))


def _rerank_score(query: str, rel_path: str, semantic_score: float) -> tuple[float, list[str]]:
    normalized = _normalized_path(rel_path)
    path_obj = Path(rel_path)
    filename = " ".join(_tokenize(path_obj.name))
    query_tokens = _tokenize(query)
    reasons = []
    score = semantic_score

    if any(marker in normalized for marker in TEMPLATE_MARKERS):
        score += 0.35
        reasons.append("path looks like a template")

    if path_obj.parent.name.lower() in TEMPLATE_MARKERS:
        score += 0.15
        reasons.append("file is inside a template folder")

    matched_tokens = [token for token in query_tokens if token in normalized]
    if matched_tokens:
        token_bonus = min(0.2, 0.05 * len(set(matched_tokens)))
        score += token_bonus
        reasons.append("path matches requested kind")

    filename_matches = [token for token in query_tokens if token in filename]
    if filename_matches:
        score += 0.05
        reasons.append("filename matches requested kind")

    if any(marker in normalized for marker in ARCHIVE_MARKERS):
        score -= 0.25
        reasons.append("path looks archived or completed")

    if not reasons:
        reasons.append("semantic match")

    return score, reasons


def infer_target_dir(target_dir: Path, template_rel_path: str) -> tuple[Path, str]:
    template_path = (target_dir / template_rel_path).resolve()
    parent = template_path.parent

    if parent.name.lower() in TEMPLATE_MARKERS:
        return parent.parent, "template is inside a template folder, so using its parent folder"

    return parent, "using the template file's folder"


def list_sibling_markdown_files(target_dir: Path, template_path: Path, limit: int = 8) -> list[dict]:
    if not target_dir.exists() or not target_dir.is_dir():
        return []

    siblings = []
    for child in target_dir.iterdir():
        if child.name.startswith(".") or child.suffix.lower() != ".md":
            continue
        if child.resolve() == template_path.resolve():
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        siblings.append((stat.st_mtime, child))

    siblings.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "path": str(path.resolve()),
            "name": path.name,
        }
        for _, path in siblings[:limit]
    ]


def infer_naming_notes(nearby_files: list[dict]) -> str:
    names = [item["name"] for item in nearby_files]
    if not names:
        return "No nearby markdown files found to infer naming conventions."

    stems = [Path(name).stem for name in names]
    date_prefixed = sum(1 for stem in stems if re.match(r"^\d{4}-\d{2}-\d{2}-", stem))
    kebab_case = sum(1 for stem in stems if re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", stem))
    snake_case = sum(1 for stem in stems if re.match(r"^[a-z0-9]+(_[a-z0-9]+)*$", stem))
    spaced = sum(1 for stem in stems if " " in stem)

    majority = max(1, len(stems) // 2 + 1)
    if date_prefixed >= majority:
        return "Nearby files mostly use date-prefixed kebab-case markdown filenames."
    if kebab_case >= majority:
        return "Nearby files mostly use lowercase kebab-case markdown filenames."
    if snake_case >= majority:
        return "Nearby files mostly use lowercase snake_case markdown filenames."
    if spaced >= majority:
        return "Nearby files mostly use spaces in markdown filenames."
    return "Nearby files use mixed naming conventions."


def build_template_context(
    target_dir: Path,
    query: str,
    semantic_results: list[tuple[str, float]],
    limit: int = 5,
    sibling_limit: int = 8,
) -> dict:
    candidates = []

    for rel_path, semantic_score in semantic_results:
        abs_path = (target_dir / rel_path).resolve()
        if not abs_path.exists():
            continue

        reranked_score, reasons = _rerank_score(query, rel_path, semantic_score)
        candidates.append({
            "path": str(abs_path),
            "relative_path": rel_path,
            "semantic_score": round(semantic_score, 4),
            "score": round(reranked_score, 4),
            "snippet": get_snippet(abs_path, query),
            "reasons": reasons,
        })

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    candidates = candidates[:limit]

    context = {
        "target_dir": str(target_dir.resolve()),
        "query": query,
        "template_path": None,
        "template_relative_path": None,
        "target_dir_reason": None,
        "template": None,
        "nearby_files": [],
        "naming_notes": "No nearby markdown files found to infer naming conventions.",
        "candidates": candidates,
    }

    if not candidates:
        return context

    best = candidates[0]
    template_path = Path(best["path"])
    target_folder, target_folder_reason = infer_target_dir(target_dir, best["relative_path"])

    try:
        template = template_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        template = None

    context.update({
        "template_path": str(template_path),
        "template_relative_path": best["relative_path"],
        "target_dir": str(target_folder.resolve()),
        "target_dir_reason": target_folder_reason,
        "template": template,
    })
    context["nearby_files"] = list_sibling_markdown_files(target_folder, template_path, sibling_limit)
    context["naming_notes"] = infer_naming_notes(context["nearby_files"])

    return context
