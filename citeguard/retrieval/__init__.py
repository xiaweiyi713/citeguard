"""Public retrieval interfaces."""

__all__ = [
    "BM25LikeRetriever",
    "DenseLikeRetriever",
    "HybridRetriever",
    "MetadataSourceRetriever",
    "RetrievedCitation",
]


def __getattr__(name: str):
    if name == "BM25LikeRetriever":
        from citeguard.retrieval.bm25_retriever import BM25LikeRetriever

        return BM25LikeRetriever
    if name == "DenseLikeRetriever":
        from citeguard.retrieval.dense_retriever import DenseLikeRetriever

        return DenseLikeRetriever
    if name == "HybridRetriever":
        from citeguard.retrieval.hybrid_retriever import HybridRetriever

        return HybridRetriever
    if name == "MetadataSourceRetriever":
        from citeguard.retrieval.metadata_source_retriever import MetadataSourceRetriever

        return MetadataSourceRetriever
    if name == "RetrievedCitation":
        from citeguard.retrieval.types import RetrievedCitation

        return RetrievedCitation
    raise AttributeError(f"module 'citeguard.retrieval' has no attribute {name!r}")
