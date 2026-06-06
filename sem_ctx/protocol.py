from pathlib import Path
from typing import Optional


BEGIN_MARKER = "<!-- SEM-CTX-PROTOCOL:BEGIN -->"
END_MARKER = "<!-- SEM-CTX-PROTOCOL:END -->"

FALLBACK_PROTOCOL = """# Semantic Context Agent Protocol

`sem-ctx` is a discovery tool for markdown documents. Use it to find relevant notes, locate templates, and understand where new items belong. Do not use `sem-ctx` to write files; create or edit markdown with your normal filesystem tools after you have gathered enough context.

## When To Use It

Use `sem-ctx search` when the user asks a question that may already be answered in their documents, asks you to update existing knowledge, or refers to a project, note, person, workflow, decision, work item, or template that may live in the context directory.

Use `sem-ctx template` when the user asks you to create a new item from an existing template, such as a work item, decision note, meeting note, project note, runbook, or similar structured document.

Use normal filesystem tools after `sem-ctx` has identified the relevant files, template contents, target folder, and nearby examples.

## Commands

### Search Existing Notes

```bash
sem-ctx search "authentication workflow"
```

Use JSON when another tool or script needs structured results:

```bash
sem-ctx search "authentication workflow" --json
```

Read the returned files with your normal file-reading tools before making claims or edits. Search results include snippets, but snippets are not a substitute for the full file.

### Find A Template

```bash
sem-ctx template "work item" --json
```

Use the JSON response to identify:

- `template_path`: the template file to read or apply.
- `target_dir`: the folder where a new item probably belongs.
- `template`: the template text.
- `nearby_files`: sibling markdown files that show local naming and formatting conventions.
- `naming_notes`: inferred filename style for the target folder.
- `candidates`: alternate template matches if the best result looks wrong.

After selecting the appropriate template and target folder, choose the final filename and content from the user's request, the template, and nearby examples. Then create the file with your normal filesystem tools.

## Expected Agent Workflow

1. Resolve context with `sem-ctx search` or `sem-ctx template`.
2. Read the relevant markdown files returned by the command.
3. Infer the right destination, filename, and content from the user's request and the resolved context.
4. Write or edit markdown using your normal file tools.
5. Re-run `sem-ctx search` if you need to verify the new or changed note is discoverable.

## Important Constraints

- Do not call removed or legacy write commands.
- Do not assume a template path or target folder when `sem-ctx template` can find it.
- Do not rely only on snippets for edits; read the full files you plan to use.
- Prefer `--json` when acting as an automated agent.
- If template candidates are ambiguous, inspect the candidates and nearby files before choosing.
"""


def get_protocol_file_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".sem-ctx-protocol.md"


def load_protocol_text() -> str:
    protocol_path = get_protocol_file_path()
    try:
        return protocol_path.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_PROTOCOL.strip()


def resolve_agents_path(path: Optional[str] = None) -> Path:
    if path:
        target = Path(path).expanduser()
        if target.exists() and target.is_dir():
            target = target / "AGENTS.md"
    else:
        target = Path.cwd() / "AGENTS.md"

    return target.resolve()


def render_agents_block(protocol_text: str) -> str:
    return f"{BEGIN_MARKER}\n{protocol_text.strip()}\n{END_MARKER}"


def install_protocol(path: Optional[str] = None, protocol_text: Optional[str] = None) -> tuple[Path, bool]:
    agents_path = resolve_agents_path(path)
    protocol = protocol_text if protocol_text is not None else load_protocol_text()
    block = render_agents_block(protocol)

    if agents_path.exists():
        existing = agents_path.read_text(encoding="utf-8", errors="replace")
    else:
        existing = ""

    start = existing.find(BEGIN_MARKER)
    end = existing.find(END_MARKER)

    if start != -1 and end != -1 and end > start:
        end += len(END_MARKER)
        updated = existing[:start].rstrip() + "\n\n" + block + "\n" + existing[end:].lstrip()
        created = False
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + block + "\n"
        created = False
    else:
        updated = block + "\n"
        created = not agents_path.exists()

    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_path.write_text(updated, encoding="utf-8", newline="\n")
    return agents_path, created
