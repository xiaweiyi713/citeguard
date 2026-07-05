"""Retrieval components."""

__all__ = [
    "BM25LikeRetriever",
    "DenseLikeRetriever",
    "HybridRetriever",
    "MetadataSourceRetriever",
    "RetrievedCitation",
]


def __getattr__(name: str):
    if name == "BM25LikeRetriever":
        from .bm25_retriever import BM25LikeRetriever

        return BM25LikeRetriever
    if name == "DenseLikeRetriever":
        from .dense_retriever import DenseLikeRetriever

        return DenseLikeRetriever
    if name == "HybridRetriever":
        from .hybrid_retriever import HybridRetriever

        return HybridRetriever
    if name == "MetadataSourceRetriever":
        from .metadata_source_retriever import MetadataSourceRetriever

        return MetadataSourceRetriever
    if name == "RetrievedCitation":
        from .types import RetrievedCitation

        return RetrievedCitation
    raise AttributeError(f"module 'src.retrieval' has no attribute {name!r}")
