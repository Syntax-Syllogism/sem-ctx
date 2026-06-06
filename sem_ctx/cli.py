import sys
import json
import argparse

from sem_ctx.config import (
    resolve_target_dir, 
    set_default_target_dir
)
from sem_ctx.cache import (
    load_cache, 
    save_cache, 
    clear_cache
)
from sem_ctx.core import (
    incremental_update_index, 
    get_snippet
)
from sem_ctx.creation import build_template_context
from sem_ctx.embeddings import semantic_search
from sem_ctx.protocol import install_protocol

def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("--limit must be >= 1")
    return parsed

def main():
    parser = argparse.ArgumentParser(
        description="Semantic Context: A lightweight local markdown semantic search utility and template lookup."
    )
    
    # Global directory override
    parser.add_argument(
        "--dir",
        help="Path to the target directory. Overrides configuration file and environment variables."
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")
    
    # Subcommand: set-default
    parser_set_default = subparsers.add_parser(
        "set-default", 
        help="Sets the default global target directory."
    )
    parser_set_default.add_argument(
        "path", 
        help="Absolute path to the default target directory."
    )

    # Subcommand: install-protocol
    parser_install_protocol = subparsers.add_parser(
        "install-protocol",
        help="Adds the Semantic Context agent protocol to AGENTS.md."
    )
    parser_install_protocol.add_argument(
        "path",
        nargs="?",
        help="Path to AGENTS.md or a directory containing it (default: ./AGENTS.md)."
    )
    
    # Subcommand: search
    parser_search = subparsers.add_parser(
        "search", 
        help="Performs a local semantic vector search in the target directory."
    )
    parser_search.add_argument(
        "query", 
        help="The search query or phrase."
    )
    parser_search.add_argument(
        "--json", 
        action="store_true",
        help="Format search results as raw JSON for script parsing."
    )
    parser_search.add_argument(
        "-n", "--limit", 
        type=_positive_int, 
        default=5,
        help="Maximum number of search results to return (default: 5)."
    )
    
    # Subcommand: template
    parser_template = subparsers.add_parser(
        "template",
        help="Finds the best template and target folder for a new item."
    )
    parser_template.add_argument(
        "query",
        help="The kind of item template to find, such as 'work item' or 'decision note'."
    )
    parser_template.add_argument(
        "--json",
        action="store_true",
        help="Format template context as raw JSON for agent parsing."
    )
    parser_template.add_argument(
        "-n", "--limit",
        type=_positive_int,
        default=5,
        help="Maximum number of template candidates to return (default: 5)."
    )
    
    # Subcommand: reindex
    subparsers.add_parser(
        "reindex", 
        help="Forces a full rebuild of the local semantic search index."
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(0)
        
    try:
        # Command: set-default
        if args.command == "set-default":
            resolved_path = set_default_target_dir(args.path)
            print(f"Success: Global default target directory set to: {resolved_path}")
            sys.exit(0)

        # Command: install-protocol
        if args.command == "install-protocol":
            try:
                agents_path, created = install_protocol(args.path)
            except Exception as e:
                print(f"Error installing protocol: {e}", file=sys.stderr)
                sys.exit(1)
            action = "created" if created else "updated"
            print(f"Success: {action} Semantic Context agent protocol in: {agents_path}")
            sys.exit(0)
            
        # All other commands require a resolved target directory
        try:
            target_dir = resolve_target_dir(args.dir)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
            
        # Command: search
        if args.command == "search":
            cache_data = load_cache(target_dir)
            # Run incremental update in background before searching to ensure fresh results
            cache_data, is_dirty = incremental_update_index(target_dir, cache_data, return_dirty=True)
            if is_dirty:
                save_cache(target_dir, cache_data)
            
            # Map files to their embeddings
            doc_embeddings = {
                rel_path: file_info["embedding"]
                for rel_path, file_info in cache_data.get("files", {}).items()
                if "embedding" in file_info
            }
            
            if not doc_embeddings:
                if args.json:
                    print(json.dumps([]))
                else:
                    print("The directory is empty or contains no indexed markdown files.")
                sys.exit(0)
                
            results = semantic_search(args.query, doc_embeddings, top_k=args.limit)
            
            search_results = []
            for rel_path, score in results:
                abs_path = (target_dir / rel_path).resolve()
                snippet = get_snippet(abs_path, args.query)
                search_results.append({
                    "path": str(abs_path),
                    "score": round(score, 4),
                    "snippet": snippet
                })
                
            if args.json:
                print(json.dumps(search_results, indent=2, ensure_ascii=False))
            else:
                print("=" * 60)
                print(f"Semantic search results for: \"{args.query}\"")
                print("=" * 60)
                for idx, res in enumerate(search_results, 1):
                    print(f"{idx}. {res['path']} (Score: {res['score']})")
                    print(f"   {res['snippet']}")
                    print("-" * 60)

        # Command: template
        elif args.command == "template":
            cache_data = load_cache(target_dir)
            cache_data, is_dirty = incremental_update_index(target_dir, cache_data, return_dirty=True)
            if is_dirty:
                save_cache(target_dir, cache_data)
            
            doc_embeddings = {
                rel_path: file_info["embedding"]
                for rel_path, file_info in cache_data.get("files", {}).items()
                if "embedding" in file_info
            }
            
            if not doc_embeddings:
                context = build_template_context(target_dir, args.query, [], limit=args.limit)
            else:
                search_limit = max(args.limit * 4, 20)
                results = semantic_search(f"{args.query} template", doc_embeddings, top_k=search_limit)
                context = build_template_context(target_dir, args.query, results, limit=args.limit)

            if args.json:
                print(json.dumps(context, indent=2, ensure_ascii=False))
            elif not context["template_path"]:
                print(f"No template candidates found for: \"{args.query}\"")
                sys.exit(1)
            else:
                print("=" * 60)
                print(f"Template context for: \"{args.query}\"")
                print("=" * 60)
                print(f"Template: {context['template_path']}")
                print(f"Target folder: {context['target_dir']}")
                print(f"Target reason: {context['target_dir_reason']}")
                print(f"Naming notes: {context['naming_notes']}")
                if context["nearby_files"]:
                    print("Nearby markdown files:")
                    for item in context["nearby_files"]:
                        print(f"- {item['name']}")
                print("-" * 60)
                print("Template candidates:")
                for idx, candidate in enumerate(context["candidates"], 1):
                    print(f"{idx}. {candidate['path']} (Score: {candidate['score']})")
                    print(f"   {candidate['snippet']}")
                    print(f"   Reasons: {', '.join(candidate['reasons'])}")
                    print("-" * 60)
                
        # Command: reindex
        elif args.command == "reindex":
            print(f"Forcing full index rebuild for: {target_dir.resolve()}")
            clear_cache(target_dir)
            
            # Load empty cache schema
            cache_data = load_cache(target_dir)
            # Rebuild index
            cache_data = incremental_update_index(target_dir, cache_data)
            save_cache(target_dir, cache_data)
            print("Full index rebuild completed successfully.")
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(130)

if __name__ == "__main__":
    main()
