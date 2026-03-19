"""
IronCore Optimizer Package
===========================
V2 — Claude 4.6 "The Optimizer"
"""

from ironcore.optimizer.semantic_cache import SemanticCache, CachedResponse, CacheStats
from ironcore.optimizer.prompt_kv_cache import PromptKVCacheManager, KVCacheStats
from ironcore.optimizer.token_compressor import (
    TokenCompressor,
    CompressionMethod,
    CompressedPayload,
    CompressionStats,
)
from ironcore.optimizer.reranker import Reranker, RerankResult, BM25Scorer
from ironcore.optimizer.cost_dashboard import CostDashboard, SessionCostReport, MetricPoint
from ironcore.optimizer.mcp_server import (
    MCPServer,
    MCPRequest,
    MCPResponse,
    MCPResource,
    MCPTool,
    MCPPrompt,
)
from ironcore.optimizer.sliding_window import SlidingWindowSummarizer, WindowState

__all__ = [
    # Phase 1
    "SemanticCache", "CachedResponse", "CacheStats",
    # Phase 2
    "PromptKVCacheManager", "KVCacheStats",
    # Phase 3
    "TokenCompressor", "CompressionMethod", "CompressedPayload", "CompressionStats",
    # Phase 4
    "Reranker", "RerankResult", "BM25Scorer",
    "CostDashboard", "SessionCostReport", "MetricPoint",
    # Phase 5
    "MCPServer", "MCPRequest", "MCPResponse", "MCPResource", "MCPTool", "MCPPrompt",
    # Phase 6
    "SlidingWindowSummarizer", "WindowState",
]

