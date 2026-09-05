"""Classify query intent and extract deterministic entities without an LLM call."""

from .models import QueryAnalysis, QueryIntent
from .path_normalizer import normalize_api_path
from .retrieval_patterns import (
    API_PATH_PATTERN, ENV_EXCLUDE_WORDS, FILE_NAME_PATTERN, HTTP_METHOD_PATTERN,
    QUALIFIED_SYMBOL_PATTERN, TEST_ID_PATTERN, TOKEN_PATTERN,
)


class QueryAnalyzer:
    """Rule-based analyzer. Ambiguous Chinese questions deliberately fall back to vectors."""

    _GENERATE_WORDS = ("生成", "设计", "编写", "测试用例", "测试脚本", "test case", "generate")
    _IMPACT_WORDS = ("影响", "调用链", "上下游", "关联流程", "会影响")
    _SIMILAR_WORDS = ("类似", "相似", "同类", "参考实现")
    _ANALYSIS_WORDS = ("风险", "边界", "异常", "缺陷", "分析", "缺少", "补充", "为什么")
    _LOCATE_WORDS = ("在哪里", "位置", "哪个文件", "查找", "定位", "定义")

    def analyze(self, query: str) -> QueryAnalysis:
        text = query.strip()
        lowered = text.lower()
        intent = self._classify_intent(lowered)
        methods = [item.upper() for item in HTTP_METHOD_PATTERN.findall(text)]
        paths = [normalize_api_path(item) for item in API_PATH_PATTERN.findall(text)]
        keywords = self._extract_keywords(text)
        symbols = QUALIFIED_SYMBOL_PATTERN.findall(text) + FILE_NAME_PATTERN.findall(text)
        return QueryAnalysis(
            query=text,
            intent=intent,
            test_ids=[item.upper() for item in TEST_ID_PATTERN.findall(text)],
            api_paths=paths,
            api_methods=methods,
            symbols=list(dict.fromkeys(symbols)),
            config_keys=[token for token in keywords if token.isupper() and token not in ENV_EXCLUDE_WORDS],
            keywords=keywords,
        )

    def _classify_intent(self, lowered: str) -> QueryIntent:
        if any(word in lowered for word in self._GENERATE_WORDS):
            return QueryIntent.GENERATE
        if any(word in lowered for word in self._IMPACT_WORDS):
            return QueryIntent.IMPACT
        if any(word in lowered for word in self._SIMILAR_WORDS):
            return QueryIntent.SIMILARITY
        if any(word in lowered for word in self._ANALYSIS_WORDS):
            return QueryIntent.ANALYSIS
        if any(word in lowered for word in self._LOCATE_WORDS):
            return QueryIntent.LOCATE
        return QueryIntent.FACT_LOOKUP

    def _extract_keywords(self, text: str) -> list[str]:
        tokens = [token.lower() for token in TOKEN_PATTERN.findall(text)]
        # Keep Chinese bi-grams to improve lightweight local matching without pretending to be semantic search.
        chinese_terms = []
        for token in tokens:
            if all("\u4e00" <= char <= "\u9fff" for char in token) and len(token) > 2:
                chinese_terms.extend(token[index:index + 2] for index in range(len(token) - 1))
        stop_words = {"如何", "什么", "这个", "那个", "项目", "功能", "一下", "帮我", "请问", "相关", "方面", "内容"}
        return list(dict.fromkeys(token for token in tokens + chinese_terms if token not in stop_words))
