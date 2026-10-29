import os
import sys
import shutil
import unittest
import tempfile
from contextlib import redirect_stdout
from importlib.metadata import version
from io import StringIO
from pathlib import Path

# Add project root to sys.path to allow imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sem_ctx.config as config_module
import sem_ctx.cache as cache_module
from sem_ctx.config import resolve_target_dir, set_default_target_dir, ContextDirectoryNotResolvedError
from sem_ctx.cache import load_cache, save_cache, clear_cache, get_cache_file_path
from sem_ctx.core import scan_markdown_files, incremental_update_index, get_snippet
from sem_ctx.creation import build_template_context, infer_target_dir
from sem_ctx.protocol import BEGIN_MARKER, END_MARKER, install_protocol
import sem_ctx.core as core_module
import sem_ctx
from sem_ctx.cli import main
from sem_ctx.embeddings import generate_embeddings, cosine_similarity, semantic_search

class TestSemCtx(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for the target directory
        self.test_dir = Path(tempfile.mkdtemp())

        # Save original environment and working directory to restore later
        self.original_env = dict(os.environ)
        self.original_cwd = Path.cwd()

        # Isolate config resolution from the host machine so tests are hermetic:
        # 1. Point the global config at a throwaway location inside test_dir.
        # 2. Run from an empty cwd so stray .env / .sem-ctx.json can't leak in.
        # 3. Drop any real SEM_CTX_DIR from the environment.
        self._isolated_cwd = Path(tempfile.mkdtemp())
        self._isolated_global_config = self.test_dir / "_global_config.json"
        self._original_get_global_config_path = config_module.get_global_config_path
        self._original_get_cache_dir = cache_module.get_cache_dir
        config_module.get_global_config_path = lambda: self._isolated_global_config
        cache_module.get_cache_dir = lambda: self.test_dir / "_cache"
        os.environ.pop("SEM_CTX_DIR", None)
        os.chdir(self._isolated_cwd)

    def tearDown(self):
        # Restore working directory before removing temp dirs
        os.chdir(self.original_cwd)

        # Clean up cache files generated for self.test_dir
        clear_cache(self.test_dir)

        # Restore patched config/cache paths
        config_module.get_global_config_path = self._original_get_global_config_path
        cache_module.get_cache_dir = self._original_get_cache_dir

        # Clean up temporary directories
        shutil.rmtree(self.test_dir, ignore_errors=True)
        shutil.rmtree(self._isolated_cwd, ignore_errors=True)

        # Restore environment variables
        os.environ.clear()
        os.environ.update(self.original_env)

    def write_markdown(self, rel_path: str, content: str) -> Path:
        file_path = self.test_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8", newline="\n")
        return file_path

    def test_version_flag_prints_installed_package_version(self):
        expected_version = version("sem-ctx")
        output = StringIO()
        original_argv = sys.argv
        try:
            sys.argv = ["sem-ctx", "--version"]
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as exit_info:
                    main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_info.exception.code, 0)
        self.assertEqual(output.getvalue(), f"sem-ctx {expected_version}\n")
        self.assertEqual(sem_ctx.__version__, expected_version)

    def test_scan_markdown_files(self):
        # Create nested directories and files
        self.write_markdown("file1.md", "# Heading 1")
        self.write_markdown("sub/file2.md", "# Heading 2")
        self.write_markdown("sub/deep/file3.md", "# Heading 3")
        self.write_markdown("sub/.hidden/file4.md", "# Hidden")
        text_path = self.test_dir / "file5.txt"
        text_path.write_text("Not a markdown file", encoding="utf-8")
        
        # Verify scanning only returns non-hidden markdown files
        scanned = scan_markdown_files(self.test_dir)
        rel_scanned = sorted([str(p.relative_to(self.test_dir).as_posix()) for p in scanned])
        
        self.assertEqual(
            rel_scanned, 
            ["file1.md", "sub/deep/file3.md", "sub/file2.md"]
        )

    def test_cache_operations(self):
        # Initialize some cache data
        cache_data = load_cache(self.test_dir)
        self.assertEqual(cache_data["target_dir"], str(self.test_dir.resolve()))
        self.assertEqual(cache_data["files"], {})
        
        # Save cache
        cache_data["files"]["note.md"] = {"mtime": 123.0, "hash": "h1", "embedding": [0.1, 0.2]}
        save_cache(self.test_dir, cache_data)
        
        # Reload cache and verify it persisted
        reloaded = load_cache(self.test_dir)
        self.assertEqual(reloaded["files"]["note.md"]["hash"], "h1")
        self.assertEqual(reloaded["files"]["note.md"]["embedding"], [0.1, 0.2])
        
        # Clear cache and verify it resets
        self.assertTrue(clear_cache(self.test_dir))
        cleared = load_cache(self.test_dir)
        self.assertEqual(cleared["files"], {})

    def test_resolve_target_dir_hierarchy(self):
        # 1. CLI arg priority
        resolved = resolve_target_dir(str(self.test_dir))
        self.assertEqual(resolved.resolve(), self.test_dir.resolve())

        # 2. Env variable priority
        os.environ["SEM_CTX_DIR"] = str(self.test_dir)
        resolved = resolve_target_dir(None)
        self.assertEqual(resolved.resolve(), self.test_dir.resolve())
        
        # Cleanup env
        del os.environ["SEM_CTX_DIR"]
        
        # 3. Failing resolution
        with self.assertRaises(ContextDirectoryNotResolvedError):
            resolve_target_dir(None)

    def test_resolve_target_dir_global_config(self):
        # set-default writes to the (isolated) global config, and resolution
        # should then fall through to it when nothing else is configured.
        set_default_target_dir(str(self.test_dir))
        resolved = resolve_target_dir(None)
        self.assertEqual(resolved.resolve(), self.test_dir.resolve())

    def test_semantic_search_ranking(self):
        # Orthogonal/opposite unit vectors with a clear ranking.
        doc_embeddings = {
            "match.md": [1.0, 0.0, 0.0],
            "orthogonal.md": [0.0, 1.0, 0.0],
            "opposite.md": [-1.0, 0.0, 0.0],
            "zero.md": [0.0, 0.0, 0.0],
        }
        # semantic_search calls generate_embeddings via the embeddings module,
        # so patch it there for the query vector.
        import sem_ctx.embeddings as emb_module
        emb_original = emb_module.generate_embeddings
        emb_module.generate_embeddings = lambda texts: [[1.0, 0.0, 0.0]]
        self.addCleanup(setattr, emb_module, "generate_embeddings", emb_original)

        results = semantic_search("anything", doc_embeddings, top_k=2)
        self.assertEqual(len(results), 2)
        # Best match first, then orthogonal (score 0) ahead of the opposite (-1).
        self.assertEqual(results[0][0], "match.md")
        self.assertAlmostEqual(results[0][1], 1.0, places=5)

        # A zero-norm document must score 0.0 rather than NaN.
        all_results = dict(semantic_search("anything", doc_embeddings, top_k=10))
        self.assertAlmostEqual(all_results["zero.md"], 0.0, places=5)

        # top_k < 1 returns nothing.
        self.assertEqual(semantic_search("anything", doc_embeddings, top_k=0), [])

    def test_cosine_similarity(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]
        v3 = [0.0, 1.0, 0.0]
        v4 = [-1.0, 0.0, 0.0]
        
        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0)
        self.assertAlmostEqual(cosine_similarity(v1, v3), 0.0)
        self.assertAlmostEqual(cosine_similarity(v1, v4), -1.0)

    def test_get_snippet_extraction(self):
        text = "This is a simple markdown document that supports local semantic search queries about auth tokens."
        file_path = self.write_markdown("auth_notes.md", text)
        
        # Searching for 'auth' should find it and return a snippet containing 'auth tokens'
        snippet = get_snippet(file_path, "auth tokens", max_len=60)
        self.assertIn("auth tokens", snippet.lower())
        
        # Non-matching query should return the start of the file
        snippet_fallback = get_snippet(file_path, "something completely missing", max_len=20)
        self.assertTrue(snippet_fallback.startswith("This is a simple"))

    def test_incremental_update_index_logic(self):
        original_generate_embeddings = core_module.generate_embeddings
        core_module.generate_embeddings = lambda texts: [[0.0] * 384 for _ in texts]
        self.addCleanup(setattr, core_module, "generate_embeddings", original_generate_embeddings)

        # Create initial notes
        self.write_markdown("apple.md", "Apples are delicious red or green fruits.")
        
        cache_data = load_cache(self.test_dir)
        cache_data = incremental_update_index(self.test_dir, cache_data)
        
        self.assertIn("apple.md", cache_data["files"])
        self.assertEqual(cache_data["files"]["apple.md"]["size"], (self.test_dir / "apple.md").stat().st_size)
        self.assertEqual(len(cache_data["files"]["apple.md"]["embedding"]), 384) # BAAI/bge-small-en embedding dimension is 384
        
        # Capture initial apple hash
        apple_hash = cache_data["files"]["apple.md"]["hash"]
        
        # Modify file and re-run incremental index
        self.write_markdown("apple.md", "Apples can also be baked into warm delicious pies.")
        cache_data = incremental_update_index(self.test_dir, cache_data)
        
        # Verify the hash has changed
        self.assertNotEqual(cache_data["files"]["apple.md"]["hash"], apple_hash)
        
        # Add another file
        self.write_markdown("banana.md", "Bananas are nutritious long yellow fruits.")
        cache_data = incremental_update_index(self.test_dir, cache_data)
        
        self.assertIn("apple.md", cache_data["files"])
        self.assertIn("banana.md", cache_data["files"])
        
        # Delete banana file and verify incremental cleanup
        (self.test_dir / "banana.md").unlink()
        cache_data = incremental_update_index(self.test_dir, cache_data)
        
        self.assertIn("apple.md", cache_data["files"])
        self.assertNotIn("banana.md", cache_data["files"])

    def test_build_template_context_prefers_template_and_includes_siblings(self):
        template = self.write_markdown(
            "work-items/work-item-template.md",
            "# Work Item\n\n## Context\n\n## Acceptance Criteria\n",
        )
        self.write_markdown("work-items/fix-login.md", "# Fix Login\n")
        self.write_markdown("work-items/refactor-cache.md", "# Refactor Cache\n")
        self.write_markdown("work-items/archive/old-work-item-template.md", "# Old Template\n")

        context = build_template_context(
            self.test_dir,
            "work item",
            [
                ("work-items/fix-login.md", 0.84),
                ("work-items/work-item-template.md", 0.72),
                ("work-items/archive/old-work-item-template.md", 0.9),
            ],
            limit=3,
        )

        self.assertEqual(Path(context["template_path"]), template.resolve())
        self.assertEqual(Path(context["target_dir"]), (self.test_dir / "work-items").resolve())
        self.assertIn("Acceptance Criteria", context["template"])
        self.assertEqual(context["candidates"][0]["relative_path"], "work-items/work-item-template.md")
        self.assertIn("path looks like a template", context["candidates"][0]["reasons"])
        self.assertEqual(
            sorted(item["name"] for item in context["nearby_files"]),
            ["fix-login.md", "refactor-cache.md"],
        )
        self.assertEqual(
            context["naming_notes"],
            "Nearby files mostly use lowercase kebab-case markdown filenames.",
        )

    def test_infer_target_dir_uses_parent_of_templates_folder(self):
        self.write_markdown("templates/decision-note.md", "# Decision Note\n")

        target_dir, reason = infer_target_dir(self.test_dir, "templates/decision-note.md")

        self.assertEqual(target_dir, self.test_dir.resolve())
        self.assertIn("template folder", reason)

    def test_build_template_context_handles_no_candidates(self):
        context = build_template_context(self.test_dir, "meeting note", [], limit=3)

        self.assertIsNone(context["template_path"])
        self.assertEqual(context["candidates"], [])
        self.assertEqual(context["nearby_files"], [])
        self.assertEqual(
            context["naming_notes"],
            "No nearby markdown files found to infer naming conventions.",
        )

    def test_install_protocol_creates_agents_file(self):
        agents_path = self.test_dir / "AGENTS.md"

        written_path, created = install_protocol(
            str(agents_path),
            protocol_text="# Protocol\n\nUse `sem-ctx search`.",
        )

        self.assertTrue(created)
        self.assertEqual(written_path, agents_path.resolve())
        content = agents_path.read_text(encoding="utf-8")
        self.assertIn(BEGIN_MARKER, content)
        self.assertIn("# Protocol", content)
        self.assertIn(END_MARKER, content)

    def test_install_protocol_replaces_existing_block(self):
        agents_path = self.test_dir / "AGENTS.md"
        agents_path.write_text(
            "# Project Agents\n\n"
            f"{BEGIN_MARKER}\nold protocol\n{END_MARKER}\n\n"
            "Keep this footer.\n",
            encoding="utf-8",
        )

        written_path, created = install_protocol(
            str(agents_path),
            protocol_text="# New Protocol\n",
        )

        self.assertFalse(created)
        self.assertEqual(written_path, agents_path.resolve())
        content = agents_path.read_text(encoding="utf-8")
        self.assertIn("# Project Agents", content)
        self.assertIn("# New Protocol", content)
        self.assertIn("Keep this footer.", content)
        self.assertNotIn("old protocol", content)
        self.assertEqual(content.count(BEGIN_MARKER), 1)
        self.assertEqual(content.count(END_MARKER), 1)

if __name__ == "__main__":
    unittest.main()
