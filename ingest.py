#!/usr/bin/env python3
"""
ContextCut — Qdrant ingest + file watcher

Embeds your markdown knowledge base into Qdrant using Voyage AI.

Usage:
  python ingest.py                        # one-shot ingest all .md files
  python ingest.py --watch                # ingest then watch for changes
  python ingest.py --query "your question" # test semantic search
  python ingest.py --clear                # wipe and recreate collection

Configuration via environment variables (all optional — defaults shown):
  CONTEXTCUT_QDRANT_HOST   localhost      Qdrant host
  CONTEXTCUT_QDRANT_PORT   6333           Qdrant port
  CONTEXTCUT_COLLECTION    contextcut     Qdrant collection name
  CONTEXTCUT_KB_DIR        ~/contextcut/knowledge  Directory to watch
  VOYAGE_API_KEY           (required)     Voyage AI API key

Notes:
  - Only .md files are ingested
  - Files matching EXCLUDE_FILES or containing .bak- are skipped
  - Voyage AI free tier: ~3 RPM — a 21s delay is added between embeds
  - First 4000 chars of each file are stored as payload text
  - First 8000 chars are embedded (Voyage model input limit)
"""

import os
import sys
import time
import json
import random
import hashlib
import urllib.request
import argparse
from pathlib import Path

VOYAGE_AVAILABLE = False
try:
    import voyageai
    VOYAGE_AVAILABLE = True
except ImportError:
    pass

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# ── Config ────────────────────────────────────────────────────────────────────
QDRANT_HOST  = os.getenv("CONTEXTCUT_QDRANT_HOST", "localhost")
QDRANT_PORT  = int(os.getenv("CONTEXTCUT_QDRANT_PORT", "6333"))
COLLECTION   = os.getenv("CONTEXTCUT_COLLECTION",  "contextcut")
KB_DIR       = Path(os.getenv("CONTEXTCUT_KB_DIR", str(Path.home() / "contextcut" / "knowledge"))).expanduser()
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "").strip().strip('"').strip("'")
OLLAMA_EMBED   = os.environ.get("CONTEXTCUT_EMBED_MODEL", "").strip().strip('"').strip("'")
OLLAMA_URL     = os.environ.get("CONTEXTCUT_UPSTREAM", "http://localhost:11434")
VOYAGE_MODEL = "voyage-3"

def _get_embed_dim():
    """Return embedding dimension based on active model."""
    if OLLAMA_EMBED:
        dims = {
            "nomic-embed-text": 768,
            "nomic-embed-text-v1.5": 768,
            "nomic-embed-text-v2-moe": 768,
            "mxbai-embed-large": 1024,
            "bge-m3": 1024,
            "qwen3-embedding:0.6b": 4096,
            "qwen3-embedding:4b": 4096,
            "qwen3-embedding:8b": 4096,
            "snowflake-arctic-embed-l": 1024,
            "all-minilm": 384,
        }
        base = OLLAMA_EMBED.split(":")[0]
        return dims.get(OLLAMA_EMBED, dims.get(base, 1024))
    return 1024

EMBED_DIM = _get_embed_dim()

# Files to never ingest
EXCLUDE_FILES = {"MEMORY.md"}

last_embed_time = 0

# ── Clients ───────────────────────────────────────────────────────────────────
vc = voyageai.Client(api_key=VOYAGE_API_KEY) if VOYAGE_API_KEY else None
qc = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

def _ollama_embed(texts, model):
    """Embed using Ollama's /api/embed endpoint."""
    payloads = []
    for t in texts:
        payload = json.dumps({"model": model, "input": t}).encode()
        req = urllib.request.Request(f"{OLLAMA_URL}/api/embed", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        embeddings = data.get("embeddings", [])
        if embeddings:
            payloads.append(embeddings[0])
    return payloads

# ── Collection ────────────────────────────────────────────────────────────────
def ensure_collection():
    existing = [c.name for c in qc.get_collections().collections]
    if COLLECTION not in existing:
        try:
            qc.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
            )
            print(f"[+] Created collection '{COLLECTION}' (dim={EMBED_DIM})")
        except Exception:
            # Already exists (race with another process)
            pass
    else:
        info = qc.get_collection(COLLECTION)
        actual_dim = info.config.params.vectors.size
        if actual_dim != EMBED_DIM:
            print(f"[!] Dimension mismatch: Qdrant has {actual_dim}, model needs {EMBED_DIM}")
            print(f"[!] Recreating collection '{COLLECTION}' with dim={EMBED_DIM}...")
            qc.delete_collection(COLLECTION)
            time.sleep(2)
            try:
                qc.create_collection(
                    collection_name=COLLECTION,
                    vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
                )
                print(f"[+] Recreated collection '{COLLECTION}'")
            except Exception:
                # Already exists (race with another ingest process)
                print(f"[+] Collection '{COLLECTION}' exists (dim={EMBED_DIM})")

# ── Ingest ────────────────────────────────────────────────────────────────────
def file_id(path: Path) -> str:
    return hashlib.md5(str(path).encode()).hexdigest()

def sanitize_text(text: str) -> str:
    # 1. Remove control characters or problematic formatting
    # 2. Ensure it's a clean string
    return text.replace('\r\n', '\n').replace('"', '\\"').strip()

processing_queue = set()

def ingest_file(path: Path):
    if path.name in processing_queue:
        return # Skip if already being processed
    processing_queue.add(path.name)
    
    try:
        if not path.exists:
            return # Skip if it's been removed
        raw_text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not raw_text:
            return
        
        # Sanitize before embedding
        clean_text = sanitize_text(raw_text[:8000])
        
        # Pass the sanitized list to your safe_embed function
        # clean_text is a string
        result = safe_embed([clean_text], model=VOYAGE_MODEL, input_type="document")

        vector = result.embeddings[0]
        fid = file_id(path)
        
        qc.upsert(
            collection_name=COLLECTION,
            points=[PointStruct(
                id=int(fid[:8], 16),
                vector=vector,
                payload={
                    "filename": path.name,
                    "path": str(path),
                    "text": clean_text[:4000],
                }
            )]
        )
        print(f"  [ok] {path.name}")
    finally:
        processing_queue.remove(path.name)


def safe_embed(texts, model, input_type):
    global last_embed_time

    if OLLAMA_EMBED and not VOYAGE_API_KEY:
        try:
            vectors = _ollama_embed(texts, OLLAMA_EMBED)
            class EmbedResult:
                pass
            result = EmbedResult()
            result.embeddings = vectors
            return result
        except Exception as e:
            print(f" [!] Ollama embed error: {e}")
            raise

    elapsed = time.time() - last_embed_time
    if elapsed < 22:
        time.sleep(22 - elapsed)

    try:
        result = vc.embed(texts, model=model, input_type=input_type)
        last_embed_time = time.time()
        return result
    except voyageai.error.RateLimitError:
        wait_time = 60 + random.uniform(5, 15)
        print(f" [!] Rate limit hit, backing off for {wait_time:.1f}s...")
        time.sleep(wait_time)
        return safe_embed(texts, model, input_type)

def should_ingest(path: Path) -> bool:
    return (
        path.suffix == ".md"
        and path.name not in EXCLUDE_FILES
        and ".bak-" not in path.name
    )

def ingest_all():
    ensure_collection()
    md_files = [f for f in KB_DIR.glob("*.md") if should_ingest(f)]
    if not md_files:
        print(f"No eligible .md files found in {KB_DIR}")
        return
    print(f"[*] Ingesting {len(md_files)} files from {KB_DIR} ...")
    for f in md_files:
        ingest_file(f)
    print("[*] Done.")

# ── Query ─────────────────────────────────────────────────────────────────────
def query(q: str, top_k: int = 5):
    ensure_collection()
    result = vc.embed([q], model=VOYAGE_MODEL, input_type="query")
    vector = result.embeddings[0]
    hits   = qc.query_points(collection_name=COLLECTION, query=vector, limit=top_k).points
    print(f"\nTop {top_k} results for: \"{q}\"\n")
    for i, hit in enumerate(hits, 1):
        print(f"  {i}. [{hit.score:.3f}] {hit.payload.get('filename','?')}")
        print(f"     {hit.payload.get('text','')[:200].strip()}\n")

# ── Clear ─────────────────────────────────────────────────────────────────────
def clear():
    qc.delete_collection(COLLECTION)
    print(f"[+] Collection '{COLLECTION}' deleted.")

# ── Watch ─────────────────────────────────────────────────────────────────────
def watch():
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("ERROR: watchdog not installed. Run: pip install watchdog")
        sys.exit(1)

    class Handler(FileSystemEventHandler):
        def __init__(self):
            self._last = {}

        def _debounce(self, path, secs=30) -> bool:
            now = time.time()
            if now - self._last.get(path, 0) < secs:
                return False
            self._last[path] = now
            return True

        def on_modified(self, event):
            p = Path(event.src_path)
            if should_ingest(p) and self._debounce(event.src_path):
                ingest_file(p)

        def on_created(self, event):
            p = Path(event.src_path)
            if should_ingest(p) and self._debounce(event.src_path):
                ingest_file(p)

    ensure_collection()
    ingest_all()
    observer = Observer()
    observer.schedule(Handler(), str(KB_DIR), recursive=False)
    observer.start()
    print(f"[*] Watching {KB_DIR} for changes. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not VOYAGE_API_KEY and not OLLAMA_EMBED:
        print("ERROR: Neither VOYAGE_API_KEY nor CONTEXTCUT_EMBED_MODEL set.")
        print("  export VOYAGE_API_KEY=your-key-here")
        print("  export CONTEXTCUT_EMBED_MODEL=nomic-embed-text")
        sys.exit(1)

    if VOYAGE_API_KEY:
        print(f"[ingest] Embedding: Voyage AI (voyage-3)")
    else:
        print(f"[ingest] Embedding: Ollama ({OLLAMA_EMBED})")

    if not KB_DIR.exists():
        print(f"ERROR: Knowledge base directory not found: {KB_DIR}")
        print(f"  Create it: mkdir -p {KB_DIR}")
        print(f"  Or set: export CONTEXTCUT_KB_DIR=/path/to/your/markdown/files")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="ContextCut ingest tool")
    parser.add_argument("--watch", action="store_true", help="Watch KB_DIR for changes")
    parser.add_argument("--query", type=str,            help="Test semantic search")
    parser.add_argument("--clear", action="store_true", help="Wipe Qdrant collection")
    args = parser.parse_args()

    if args.clear:
        clear()
    elif args.query:
        query(args.query)
    elif args.watch:
        watch()
    else:
        ingest_all()
