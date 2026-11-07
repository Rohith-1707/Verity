"""Evidence retrieval. ChromaDB + Sentence Transformers in production; a keyword retriever for tests and offline use."""
from __future__ import annotations
from .engine import sentences, tokens


class KeywordRetriever:
    min_score, strong = 0.3, 0.5

    def __init__(self):
        self.items: list[dict] = []

    def index(self, org, doc_id, title, version, status, effective, review, text):
        self.items += [{"org": org, "doc": doc_id, "title": title, "version": version, "status": status,
                        "effective": effective, "review": review, "text": s} for s in sentences(text)]

    def set_status(self, org, doc_id, status):
        for i in self.items:
            if i["org"] == org and i["doc"] == doc_id:
                i["status"] = status

    def search(self, org, claim, status, k=3):
        ct, out = tokens(claim), []
        for i in self.items:
            if i["org"] == org and i["status"] == status:
                shared = len(ct & tokens(i["text"]))
                if shared >= 2:
                    out.append({**i, "score": shared / max(1, len(ct))})
        return sorted(out, key=lambda h: -h["score"])[:k]


class ChromaRetriever:
    """Persistent vector store. One collection per organisation keeps data isolated."""
    min_score, strong = 0.45, 0.65

    def __init__(self, path: str, model: str = "all-MiniLM-L6-v2"):
        import chromadb
        from sentence_transformers import SentenceTransformer
        self.client, self.model = chromadb.PersistentClient(path=path), SentenceTransformer(model)

    def _col(self, org):
        return self.client.get_or_create_collection(f"org_{org}", metadata={"hnsw:space": "cosine"})

    def index(self, org, doc_id, title, version, status, effective, review, text):
        ps = sentences(text)
        if ps:
            self._col(org).add(ids=[f"{doc_id}:{version}:{n}" for n in range(len(ps))], documents=ps,
                               embeddings=self.model.encode(ps).tolist(),
                               metadatas=[{"doc": str(doc_id), "title": title, "version": version, "status": status,
                                           "effective": str(effective or ""), "review": str(review or "")}] * len(ps))

    def set_status(self, org, doc_id, status):
        col = self._col(org)
        got = col.get(where={"doc": str(doc_id)})
        if got["ids"]:
            col.update(ids=got["ids"], metadatas=[{**m, "status": status} for m in got["metadatas"]])

    def search(self, org, claim, status, k=3):
        col = self._col(org)
        if col.count() == 0:
            return []
        r = col.query(query_embeddings=self.model.encode([claim]).tolist(), n_results=k, where={"status": status})
        return [{"text": d, "title": m["title"], "version": m["version"], "effective": m["effective"] or None,
                 "review": m["review"] or None, "score": 1 - dist}
                for d, m, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0])]
