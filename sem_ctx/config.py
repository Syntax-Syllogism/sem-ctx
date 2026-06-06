import os
import json
import sys
from pathlib import Path

# Try importing dotenv, fallback to manual parsing if not installed yet
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

class ContextDirectoryNotResolvedError(Exception):
    """Raised when the active target directory cannot be determined."""
    pass

def get_global_config_path() -> Path:
    """Returns the path to the global sem-ctx configuration file."""
    return Path.home() / ".config" / "sem-ctx" / "config.json"

def set_default_target_dir(path: str) -> Path:
    """Sets the default target directory in the global configuration file."""
    resolved_path = Path(path).resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"The path '{path}' does not exist.")
    if not resolved_path.is_dir():
        raise NotADirectoryError(f"The path '{path}' is not a directory.")

    config_path = get_global_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config_data = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception:
            pass

    config_data["default_dir"] = str(resolved_path)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    return resolved_path

def _read_env_file_manually(env_path: Path) -> str:
    """Reads SEM_CTX_DIR from a .env file manually if dotenv is missing."""
    if not env_path.exists():
        return ""
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip() == "SEM_CTX_DIR":
                    # Remove quotes if present
                    return val.strip().strip("'\"")
    except Exception:
        pass
    return ""

def resolve_target_dir(cli_dir: str = None) -> Path:
    """
    Resolves the active target directory based on the hierarchy:
    1. CLI Argument
    2. SEM_CTX_DIR environment variable
    3. Local .sem-ctx.json in current directory
    4. Local .env in current directory
    5. Global config (~/.config/sem-ctx/config.json)
    """
    # 1. CLI Argument
    if cli_dir:
        resolved = Path(cli_dir).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"CLI specified target directory '{cli_dir}' does not exist.")
        if not resolved.is_dir():
            raise NotADirectoryError(f"CLI specified path '{cli_dir}' is not a directory.")
        return resolved

    # Load dotenv if available to populate os.environ
    if HAS_DOTENV:
        load_dotenv()

    # 2. Environment Variable
    env_dir = os.environ.get("SEM_CTX_DIR")
    if env_dir:
        resolved = Path(env_dir).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Environment variable SEM_CTX_DIR path '{env_dir}' does not exist.")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Environment variable SEM_CTX_DIR path '{env_dir}' is not a directory.")
        return resolved

    # 3. Local Workspace JSON Config
    local_json = Path.cwd() / ".sem-ctx.json"
    if local_json.exists():
        try:
            with open(local_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = data.get("SEM_CTX_DIR")
                if val:
                    resolved = Path(val).resolve()
                    if not resolved.exists():
                        raise FileNotFoundError(f"Local config '.sem-ctx.json' specified path '{val}' does not exist.")
                    if not resolved.is_dir():
                        raise NotADirectoryError(f"Local config '.sem-ctx.json' specified path '{val}' is not a directory.")
                    return resolved
        except Exception as e:
            if isinstance(e, (FileNotFoundError, NotADirectoryError)):
                raise e
            print(f"Warning: Ignoring malformed local config '{local_json}': {e}", file=sys.stderr)

    # 4. Local Workspace .env Config (Manual check in case HAS_DOTENV is False or not loaded)
    local_env = Path.cwd() / ".env"
    manual_env_val = _read_env_file_manually(local_env)
    if manual_env_val:
        resolved = Path(manual_env_val).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Local '.env' specified path '{manual_env_val}' does not exist.")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Local '.env' specified path '{manual_env_val}' is not a directory.")
        return resolved

    # 5. Global Config
    global_config = get_global_config_path()
    if global_config.exists():
        try:
            with open(global_config, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = data.get("default_dir")
                if val:
                    resolved = Path(val).resolve()
                    if not resolved.exists():
                        raise FileNotFoundError(f"Global config 'default_dir' path '{val}' does not exist.")
                    if not resolved.is_dir():
                        raise NotADirectoryError(f"Global config 'default_dir' path '{val}' is not a directory.")
                    return resolved
        except Exception as e:
            if isinstance(e, (FileNotFoundError, NotADirectoryError)):
                raise e
            print(f"Warning: Ignoring malformed global config '{global_config}': {e}", file=sys.stderr)

    # If we got here, we failed to resolve
    raise ContextDirectoryNotResolvedError(
        "Could not resolve the target directory.\n"
        "Please provide it using one of the following methods:\n"
        "1. Pass the path explicitly: sem-ctx --dir <path> <command>\n"
        "2. Set the global default:  sem-ctx set-default <path>\n"
        "3. Set the environment variable: export SEM_CTX_DIR=<path>\n"
        "4. Place a '.env' or '.sem-ctx.json' file containing SEM_CTX_DIR in your active workspace."
    )
