import sys
import numpy as np

# We lazy-import fastembed inside the functions to ensure that CLI commands
# like "set-default" that do not need embeddings load instantly.
_MODEL_INSTANCE = None

def get_model():
    """
    Lazy-loads and returns the singleton FastEmbed TextEmbedding model.
    Downloads the model (~130MB) on the first execution.
    """
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is None:
        try:
            from fastembed import TextEmbedding
        except ImportError:
            print("Error: 'fastembed' is not installed. Please install dependencies.", file=sys.stderr)
            sys.exit(1)
            
        # Notify the user since the first loading/downloading might take a few seconds
        print("Loading local semantic model (BAAI/bge-small-en-v1.5)...", end="", flush=True, file=sys.stderr)
        # BAAI/bge-small-en-v1.5 is the default model in FastEmbed: very small, highly accurate, and extremely fast.
        _MODEL_INSTANCE = TextEmbedding()
        print(" Done.", flush=True, file=sys.stderr)
    return _MODEL_INSTANCE

def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generates semantic vector embeddings for a list of string contents.
    Returns a list of list of floats (ready for JSON serialization).
    """
    if not texts:
        return []
    
    model = get_model()
    # model.embed returns a generator of numpy arrays
    embeddings_gen = model.embed(texts)
    return [arr.tolist() for arr in embeddings_gen]

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """
    Computes the cosine similarity between two numeric vectors.
    """
    arr1 = np.array(v1, dtype=np.float32)
    arr2 = np.array(v2, dtype=np.float32)
    
    dot_product = np.dot(arr1, arr2)
    norm_1 = np.linalg.norm(arr1)
    norm_2 = np.linalg.norm(arr2)
    
    if norm_1 == 0.0 or norm_2 == 0.0:
        return 0.0
    return float(dot_product / (norm_1 * norm_2))

def semantic_search(query: str, doc_embeddings: dict[str, list[float]], top_k: int = 5) -> list[tuple[str, float]]:
    """
    Compares a text query against a dictionary of document path -> vector embedding.
    Returns the top_k best matching document paths and their similarity scores.
    """
    if not doc_embeddings or top_k < 1:
        return []
    
    # Generate embedding for the query string
    query_vector = generate_embeddings([query])[0]
    
    query_arr = np.array(query_vector, dtype=np.float32)
    query_norm = np.linalg.norm(query_arr)
    if query_norm == 0.0:
        return []

    doc_paths = list(doc_embeddings.keys())
    doc_matrix = np.array([doc_embeddings[path] for path in doc_paths], dtype=np.float32)
    doc_norms = np.linalg.norm(doc_matrix, axis=1)

    # Avoid division by zero for malformed/empty vectors.
    safe_doc_norms = np.where(doc_norms == 0.0, 1.0, doc_norms)
    scores = (doc_matrix @ query_arr) / (safe_doc_norms * query_norm)
    scores = np.where(doc_norms == 0.0, 0.0, scores)

    results = list(zip(doc_paths, scores.astype(float).tolist()))
        
    # Sort by similarity score in descending order
    results.sort(key=lambda x: x[1], reverse=True)
    
    return results[:top_k]
