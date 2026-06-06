# Semantic Context CLI

`sem-ctx` is a lightweight, local, location-agnostic semantic search utility written in Python. It provides fast semantic search using a local vector embedding engine and template lookup for agent workflows.

## Installation

`sem-ctx` can be installed in editable mode, which keeps the command pointed at
this checkout while you work on the code.

### Windows

On Windows, install from the project directory:

```powershell
cd C:\Users\USER\syntax-syllogism\sem-ctx
py -m pip install -e .
```

This registers the `sem-ctx` command in the active Python environment.

### Ubuntu Linux

On recent Ubuntu/Python installations, running `pip install -e .` against the
system Python may fail with an "externally managed environment" warning. That is
Python protecting packages managed by Ubuntu's package manager.

If you use `uv`, install the CLI as an isolated editable tool:

```bash
cd sem-ctx
uv tool install --editable .
```

If you prefer a local virtual environment:

```bash
cd sem-ctx
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Avoid `pip install -e . --break-system-packages` unless you intentionally want to
modify the OS-managed Python environment.

## Configuration & Target Directory Resolution

You don't need to specify the `--dir` argument on every invocation. The tool resolves the active target directory by checking the following hierarchy:

1. **Explicit argument:** `sem-ctx --dir ~/notes/my-docs search "login issues"`
2. **Environment variable:** The `SEM_CTX_DIR` env var.
3. **Local configuration:** A `.env` or `.sem-ctx.json` containing `SEM_CTX_DIR` in the current working directory.
4. **Global configuration:** A path set in your user config file (`~/.config/sem-ctx/config.json`).

### Setting the Global Default

To set a global default target folder, run:

```bash
sem-ctx set-default path/to/your/directory
```

---

## Core Commands

### 1. Semantic Search

Perform semantic vector search using a highly optimized, local embedding model (`BAAI/bge-small-en-v1.5` running via `fastembed`):

```bash
sem-ctx search "authentication workflow"
```

To output raw structured JSON for scripts or automation:

```bash
sem-ctx search "authentication workflow" --json
```

### 2. Template Lookup

Find the best template and target folder for a new item:

```bash
sem-ctx template "work item"
```

For agent workflows, use JSON output. The command does not write files; it returns the template, target folder, nearby markdown files, and ranked candidates so the agent can create the final note with its own filesystem tools.

```bash
sem-ctx template "work item" --json
```

### 3. Installing Agent Instructions

Add the Semantic Context agent protocol to `AGENTS.md` in the current directory:

```bash
sem-ctx install-protocol
```

You can also pass a specific `AGENTS.md` path or a directory containing one:

```bash
sem-ctx install-protocol path/to/project/AGENTS.md
```

The command creates or updates a marked Semantic Context protocol block, so it is safe to run again when the protocol changes.

### 4. Reindexing Cache

Re-scan the directory and force-rebuild the embedding index from scratch:

```bash
sem-ctx reindex
```