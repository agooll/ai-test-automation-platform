"""
Application context discovery and management for RAG-enhanced test automation.

This module provides functionality to extract real application knowledge from
vector stores containing product documentation and code.
"""

import re
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from ..core.vector_store.chromadb_manager import ChromaDBManager
from ..core.llm.llm_manager import LLMManager
from .parser.markdown_parser import TestCase

logger = logging.getLogger(__name__)


@dataclass
class APIEndpoint:
    """Represents a discovered API endpoint."""
    path: str
    method: str
    description: Optional[str] = None
    request_schema: Optional[Dict] = None
    response_schema: Optional[Dict] = None
    auth_required: bool = False
    source_refs: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class UIPattern:
    """Represents a discovered UI pattern or selector."""
    selector: str
    element_type: str
    description: Optional[str] = None
    page_context: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class AuthPattern:
    """Represents discovered authentication patterns."""
    auth_type: str  # jwt, session, basic, oauth
    login_endpoint: Optional[str] = None
    token_header: Optional[str] = None
    login_selectors: Dict[str, str] = field(default_factory=dict)
    source_refs: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class DataSchema:
    """Represents discovered data schemas."""
    model_name: str
    fields: Dict[str, str] = field(default_factory=dict)
    required_fields: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class ApplicationContext:
    """Complete application context extracted from vector store."""
    base_url: Optional[str] = None
    api_endpoints: Dict[str, APIEndpoint] = field(default_factory=dict)
    ui_selectors: Dict[str, UIPattern] = field(default_factory=dict)
    auth_patterns: Optional[AuthPattern] = None
    data_schemas: Dict[str, DataSchema] = field(default_factory=dict)
    existing_test_patterns: List[str] = field(default_factory=list)
    framework_patterns: Dict[str, Any] = field(default_factory=dict)

    def to_evidence_items(self) -> List[Any]:
        """Convert discovered application knowledge into canonical EvidenceItems for Stage 4 Grounding."""
        from ..quality_gate.code_models import EvidenceItem

        items: List[EvidenceItem] = []

        # 1. API endpoints
        for key, ep in self.api_endpoints.items():
            val = f"{ep.method.upper()} {ep.path}"
            src = ep.source_refs[0] if ep.source_refs else "discovered:api"
            eid = ep.evidence_ids[0] if ep.evidence_ids else f"E-API-{len(items)+1:03d}"
            items.append(
                EvidenceItem(
                    evidence_id=eid,
                    kind="api_endpoint",
                    value=val,
                    source=src,
                    confidence=1.0,
                )
            )

        # 2. UI selectors
        for key, ui in self.ui_selectors.items():
            src = ui.source_refs[0] if ui.source_refs else "discovered:ui"
            eid = ui.evidence_ids[0] if ui.evidence_ids else f"E-UI-{len(items)+1:03d}"
            items.append(
                EvidenceItem(
                    evidence_id=eid,
                    kind="ui_selector",
                    value=ui.selector,
                    source=src,
                    confidence=1.0,
                )
            )

        # 3. Data schemas
        for model_name, schema in self.data_schemas.items():
            src = schema.source_refs[0] if schema.source_refs else "discovered:model"
            for field_name in schema.fields:
                items.append(
                    EvidenceItem(
                        evidence_id=f"E-SCHEMA-{model_name}-{field_name}",
                        kind="model_field",
                        value=f"{model_name}.{field_name}",
                        source=src,
                        confidence=1.0,
                    )
                )

        # 4. Auth patterns
        if self.auth_patterns and self.auth_patterns.login_endpoint:
            src = self.auth_patterns.source_refs[0] if self.auth_patterns.source_refs else "discovered:auth"
            eid = (
                self.auth_patterns.evidence_ids[0]
                if self.auth_patterns.evidence_ids
                else f"E-AUTH-{len(items)+1:03d}"
            )
            items.append(
                EvidenceItem(
                    evidence_id=eid,
                    kind="auth_pattern",
                    value=self.auth_patterns.login_endpoint,
                    source=src,
                    confidence=1.0,
                )
            )

        return items


class ApplicationKnowledgeExtractor:
    """Extracts real application knowledge from vector store."""
    
    def __init__(self, vector_store: ChromaDBManager, llm_manager: Optional[LLMManager] = None,
                 num_context_docs: int = 5):
        self.vector_store = vector_store
        self.llm_manager = llm_manager or LLMManager()
        self.num_context_docs = num_context_docs
        
    def extract_app_context(self, test_cases: List[TestCase]) -> ApplicationContext:
        """Extract comprehensive application context from vector store."""
        logger.info("Extracting application context from vector store...")
        
        try:
            # 1. Discover API endpoints
            api_endpoints = self._discover_api_endpoints(test_cases)
            logger.info(f"Found {len(api_endpoints)} API endpoints")
            
            # 2. Discover UI patterns and selectors
            ui_selectors = self._discover_ui_patterns(test_cases)
            logger.info(f"Found {len(ui_selectors)} UI patterns")
            
            # 3. Discover authentication patterns
            auth_patterns = self._discover_auth_patterns()
            logger.info(f"Authentication pattern: {auth_patterns.auth_type if auth_patterns else 'None'}")
            
            # 4. Discover data schemas
            data_schemas = self._discover_data_schemas(test_cases)
            logger.info(f"Found {len(data_schemas)} data schemas")
            
            # 5. Find existing test patterns
            existing_patterns = self._find_existing_test_patterns(test_cases)
            logger.info(f"Found {len(existing_patterns)} existing test patterns")
            
            # 6. Discover framework-specific patterns
            framework_patterns = self._discover_framework_patterns()
            
            return ApplicationContext(
                base_url=self._infer_base_url(),
                api_endpoints=api_endpoints,
                ui_selectors=ui_selectors,
                auth_patterns=auth_patterns,
                data_schemas=data_schemas,
                existing_test_patterns=existing_patterns,
                framework_patterns=framework_patterns
            )
            
        except Exception as e:
            logger.error(f"Failed to extract application context: {e}")
            return ApplicationContext()  # Return empty context
    
    @staticmethod
    def _extract_source_ref(metadatas: Optional[List[Any]], idx: int) -> str:
        """Extract source reference string from vector store metadata."""
        if not metadatas or idx >= len(metadatas):
            return ""
        meta = metadatas[idx]
        if isinstance(meta, dict):
            return str(meta.get("source") or meta.get("file_path") or meta.get("path") or "")
        elif isinstance(meta, str):
            return meta
        return ""

    def _discover_api_endpoints(self, test_cases: List[TestCase]) -> Dict[str, APIEndpoint]:
        """Find real API endpoints from product docs and code."""
        endpoints = {}
        
        try:
            # Build comprehensive query from test cases
            query_parts = []
            for test_case in test_cases:
                query_parts.extend([
                    test_case.feature,
                    test_case.objective,
                    *[step.action for step in test_case.test_steps if step.action]
                ])
            
            query = f"API endpoint route controller service {' '.join(filter(None, query_parts))}"
            
            # Query vector store for API-related content
            results = self.vector_store.query_similar(
                query_text=query,
                n_results=self.num_context_docs,
                metadata_filter={"type": ["code", "documentation"], "document_type": ["api_docs", "specifications"]}
            )
            
            if results and results.get('documents'):
                docs = results['documents'][0]
                metas = results.get('metadatas', [[]])[0] if results.get('metadatas') else []
                for i, doc in enumerate(docs):
                    src_ref = self._extract_source_ref(metas, i)
                    discovered_endpoints = self._parse_endpoints_from_content(doc, source_ref=src_ref)
                    endpoints.update(discovered_endpoints)
                    
            # Also search specifically for OpenAPI/Swagger documentation
            swagger_results = self.vector_store.query_similar(
                query_text="swagger openapi API documentation endpoints routes",
                n_results=min(5, self.num_context_docs),
                metadata_filter={"type": "documentation", "file_type": [".json", ".yaml", ".yml"]}
            )
            
            if swagger_results and swagger_results.get('documents'):
                docs = swagger_results['documents'][0]
                metas = swagger_results.get('metadatas', [[]])[0] if swagger_results.get('metadatas') else []
                for i, doc in enumerate(docs):
                    src_ref = self._extract_source_ref(metas, i)
                    swagger_endpoints = self._parse_openapi_spec(doc, source_ref=src_ref)
                    endpoints.update(swagger_endpoints)
                    
        except Exception as e:
            logger.warning(f"Failed to discover API endpoints: {e}")
            
        return endpoints
    
    def _discover_ui_patterns(self, test_cases: List[TestCase]) -> Dict[str, UIPattern]:
        """Find real UI selectors from existing test code and component definitions."""
        ui_patterns = {}
        
        try:
            # Query for existing test files with UI interactions
            test_query = "selenium playwright cypress test automation UI selectors page elements"
            test_results = self.vector_store.query_similar(
                query_text=test_query,
                n_results=self.num_context_docs,
                metadata_filter={"file_type": [".py", ".js", ".ts"], "type": "code"}
            )
            
            if test_results and test_results.get('documents'):
                docs = test_results['documents'][0]
                metas = test_results.get('metadatas', [[]])[0] if test_results.get('metadatas') else []
                for i, doc in enumerate(docs):
                    src_ref = self._extract_source_ref(metas, i)
                    test_patterns = self._extract_ui_selectors_from_test_code(doc, source_ref=src_ref)
                    ui_patterns.update(test_patterns)
            
            # Query for UI component definitions
            ui_query = "React Vue Angular component JSX TSX HTML form input button"
            ui_results = self.vector_store.query_similar(
                query_text=ui_query,
                n_results=self.num_context_docs,
                metadata_filter={"file_type": [".jsx", ".tsx", ".vue", ".html"], "type": "code"}
            )
            
            if ui_results and ui_results.get('documents'):
                docs = ui_results['documents'][0]
                metas = ui_results.get('metadatas', [[]])[0] if ui_results.get('metadatas') else []
                for i, doc in enumerate(docs):
                    src_ref = self._extract_source_ref(metas, i)
                    component_patterns = self._extract_ui_selectors_from_components(doc, source_ref=src_ref)
                    ui_patterns.update(component_patterns)
                    
        except Exception as e:
            logger.warning(f"Failed to discover UI patterns: {e}")
            
        return ui_patterns
    
    def _discover_auth_patterns(self) -> Optional[AuthPattern]:
        """Discover authentication patterns from codebase."""
        try:
            # Query for authentication-related code
            auth_results = self.vector_store.query_similar(
                query_text="authentication login JWT token session auth middleware",
                n_results=self.num_context_docs,
                metadata_filter={"type": "code"}
            )
            
            if not auth_results or not auth_results.get('documents'):
                return None
                
            docs = auth_results['documents'][0]
            metas = auth_results.get('metadatas', [[]])[0] if auth_results.get('metadatas') else []
            src_ref = self._extract_source_ref(metas, 0)
            auth_info = self._analyze_auth_patterns(docs)
            
            if auth_info:
                endpoint = auth_info.get('endpoint')
                return AuthPattern(
                    auth_type=auth_info.get('type', 'unknown'),
                    login_endpoint=endpoint,
                    token_header=auth_info.get('token_header'),
                    login_selectors=auth_info.get('login_selectors', {}),
                    source_refs=[src_ref] if src_ref else [],
                    evidence_ids=[f"E-AUTH-{endpoint}"] if endpoint else ["E-AUTH-login"]
                )
                
        except Exception as e:
            logger.warning(f"Failed to discover auth patterns: {e}")
            
        return None
    
    def _discover_data_schemas(self, test_cases: List[TestCase]) -> Dict[str, DataSchema]:
        """Discover data models and schemas from codebase."""
        schemas = {}
        
        try:
            # Build query from test case features
            features = [tc.feature for tc in test_cases if tc.feature]
            query = f"model schema database entity {' '.join(features)}"
            
            # Query for model definitions
            model_results = self.vector_store.query_similar(
                query_text=query,
                n_results=self.num_context_docs,
                metadata_filter={"type": "code"}
            )
            
            if model_results and model_results.get('documents'):
                docs = model_results['documents'][0]
                metas = model_results.get('metadatas', [[]])[0] if model_results.get('metadatas') else []
                for i, doc in enumerate(docs):
                    src_ref = self._extract_source_ref(metas, i)
                    discovered_schemas = self._extract_data_schemas_from_code(doc, source_ref=src_ref)
                    schemas.update(discovered_schemas)
                    
        except Exception as e:
            logger.warning(f"Failed to discover data schemas: {e}")
            
        return schemas
    
    def _find_existing_test_patterns(self, test_cases: List[TestCase]) -> List[str]:
        """Find similar test implementations from vector store."""
        patterns = []
        
        try:
            for test_case in test_cases:
                # Build query from test case details
                query_parts = [
                    test_case.feature,
                    test_case.type,
                    test_case.category,
                    " ".join([step.action for step in test_case.test_steps if step.action])
                ]
                query = " ".join(filter(None, query_parts))
                
                # Query for similar test implementations
                results = self.vector_store.query_similar(
                    query_text=query,
                    n_results=min(3, self.num_context_docs),
                    metadata_filter={
                        "type": "code",
                        "file_type": [".py", ".js", ".ts"],
                        "document_type": "test_cases"
                    }
                )
                
                if results and results.get('documents'):
                    patterns.extend(results['documents'][0])
                    
        except Exception as e:
            logger.warning(f"Failed to find existing test patterns: {e}")
            
        return patterns[:10]  # Limit to top 10 patterns
    
    def _discover_framework_patterns(self) -> Dict[str, Any]:
        """Discover framework-specific patterns and configurations."""
        patterns = {}
        
        try:
            # Query for framework configuration files
            config_results = self.vector_store.query_similar(
                query_text="pytest.ini setup.cfg jest.config playwright.config cypress.json",
                n_results=min(5, self.num_context_docs),
                metadata_filter={"file_type": [".json", ".js", ".ini", ".cfg", ".yaml"]}
            )
            
            if config_results and config_results.get('documents'):
                for doc in config_results['documents'][0]:
                    framework_config = self._extract_framework_config(doc)
                    patterns.update(framework_config)
                    
        except Exception as e:
            logger.warning(f"Failed to discover framework patterns: {e}")
            
        return patterns
    
    def _parse_endpoints_from_content(self, content: str, source_ref: str = "") -> Dict[str, APIEndpoint]:
        """Parse API endpoints from code content."""
        endpoints = {}
        
        try:
            # Common patterns for API endpoints
            patterns = [
                r'@app\.route\([\'"]([^\'\"]+)[\'"](?:.*methods=\[([^\]]+)\])?',  # Flask
                r'@router\.(get|post|put|delete|patch)\([\'"]([^\'\"]+)[\'"]',     # FastAPI
                r'app\.(get|post|put|delete|patch)\([\'"]([^\'\"]+)[\'"]',        # Express
                r'Route::(get|post|put|delete|patch)\([\'"]([^\'\"]+)[\'"]',      # Laravel
                r'@(GET|POST|PUT|DELETE|PATCH)\([\'"]([^\'\"]+)[\'"]',            # Spring Boot
            ]
            
            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    if len(match.groups()) >= 2:
                        if match.group(1).upper() in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                            method = match.group(1).upper()
                            path = match.group(2)
                        else:
                            path = match.group(1)
                            method = match.group(2).upper() if match.group(2) else 'GET'
                        
                        endpoint_key = f"{method}:{path}"
                        endpoints[endpoint_key] = APIEndpoint(
                            path=path,
                            method=method,
                            description=f"Discovered from code",
                            source_refs=[source_ref] if source_ref else [],
                            evidence_ids=[f"E-API-{method}-{path}"],
                        )
                        
        except Exception as e:
            logger.warning(f"Failed to parse endpoints from content: {e}")
            
        return endpoints
    
    def _parse_openapi_spec(self, content: str, source_ref: str = "") -> Dict[str, APIEndpoint]:
        """Parse endpoints from OpenAPI/Swagger specification."""
        endpoints = {}
        
        try:
            # Try to parse as JSON first
            try:
                spec = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from content if it's embedded
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    spec = json.loads(json_match.group())
                else:
                    return endpoints
            
            # Extract paths from OpenAPI spec
            paths = spec.get('paths', {})
            for path, path_info in paths.items():
                for method, method_info in path_info.items():
                    if method.upper() in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                        endpoint_key = f"{method.upper()}:{path}"
                        endpoints[endpoint_key] = APIEndpoint(
                            path=path,
                            method=method.upper(),
                            description=method_info.get('summary', ''),
                            request_schema=method_info.get('requestBody'),
                            response_schema=method_info.get('responses'),
                            auth_required='security' in method_info,
                            source_refs=[source_ref] if source_ref else [],
                            evidence_ids=[f"E-API-{method.upper()}-{path}"],
                        )
                        
        except Exception as e:
            logger.warning(f"Failed to parse OpenAPI spec: {e}")
            
        return endpoints
    
    def _extract_ui_selectors_from_test_code(self, content: str, source_ref: str = "") -> Dict[str, UIPattern]:
        """Extract UI selectors from existing test code."""
        patterns = {}
        
        try:
            # Common selector patterns in test code
            selector_patterns = [
                r'page\.click\([\'"]([^\'\"]+)[\'"]',                    # Playwright
                r'page\.fill\([\'"]([^\'\"]+)[\'"]',                     # Playwright
                r'driver\.find_element\(By\.([A-Z_]+),\s*[\'"]([^\'\"]+)[\'"]',  # Selenium
                r'cy\.get\([\'"]([^\'\"]+)[\'"]',                        # Cypress
                r'await.*?\$\([\'"]([^\'\"]+)[\'"]',                     # WebDriver
                r'expect\(page\.locator\([\'"]([^\'\"]+)[\'"]',          # Playwright assertions
            ]
            
            for pattern in selector_patterns:
                matches = re.finditer(pattern, content, re.MULTILINE)
                for match in matches:
                    if len(match.groups()) >= 1:
                        selector = match.groups()[-1]  # Get the last group (selector)
                        element_type = self._infer_element_type(selector)
                        
                        patterns[selector] = UIPattern(
                            selector=selector,
                            element_type=element_type,
                            description=f"Found in test code",
                            source_refs=[source_ref] if source_ref else [],
                            evidence_ids=[f"E-UI-{selector}"],
                        )
                        
        except Exception as e:
            logger.warning(f"Failed to extract UI selectors from test code: {e}")
            
        return patterns
    
    def _extract_ui_selectors_from_components(self, content: str, source_ref: str = "") -> Dict[str, UIPattern]:
        """Extract potential selectors from UI component code."""
        patterns = {}
        
        try:
            # Extract data-testid, id, and class attributes
            attribute_patterns = [
                r'data-testid=[\'"]([^\'\"]+)[\'"]',
                r'id=[\'"]([^\'\"]+)[\'"]',
                r'className=[\'"]([^\'\"]+)[\'"]',
                r'class=[\'"]([^\'\"]+)[\'"]',
            ]
            
            for pattern in attribute_patterns:
                matches = re.finditer(pattern, content, re.MULTILINE)
                for match in matches:
                    value = match.group(1)
                    
                    if 'testid' in pattern:
                        selector = f'[data-testid="{value}"]'
                    elif 'id=' in pattern:
                        selector = f'#{value}'
                    else:
                        selector = f'.{value}'
                    
                    patterns[selector] = UIPattern(
                        selector=selector,
                        element_type=self._infer_element_type_from_context(content, value),
                        description=f"Found in component code",
                        source_refs=[source_ref] if source_ref else [],
                        evidence_ids=[f"E-UI-{selector}"],
                    )
                    
        except Exception as e:
            logger.warning(f"Failed to extract UI selectors from components: {e}")
            
        return patterns
    
    def _analyze_auth_patterns(self, docs: List[str]) -> Optional[Dict[str, Any]]:
        """Analyze authentication patterns from code documents."""
        auth_info = {}
        
        try:
            combined_content = '\n'.join(docs)
            
            # Detect auth type
            if 'jwt' in combined_content.lower() or 'bearer' in combined_content.lower():
                auth_info['type'] = 'jwt'
                auth_info['token_header'] = 'Authorization'
            elif 'session' in combined_content.lower():
                auth_info['type'] = 'session'
            elif 'oauth' in combined_content.lower():
                auth_info['type'] = 'oauth'
            else:
                auth_info['type'] = 'basic'
            
            # Look for login endpoints
            login_patterns = [
                r'/api/auth/login',
                r'/api/login',
                r'/auth/signin',
                r'/login'
            ]
            
            for pattern in login_patterns:
                if pattern in combined_content:
                    auth_info['endpoint'] = pattern
                    break
                    
        except Exception as e:
            logger.warning(f"Failed to analyze auth patterns: {e}")
            
        return auth_info if auth_info else None
    
    def _extract_data_schemas_from_code(self, content: str, source_ref: str = "") -> Dict[str, DataSchema]:
        """Extract data schemas from model definitions."""
        schemas = {}
        
        try:
            # Python model patterns (SQLAlchemy, Pydantic, Django)
            python_patterns = [
                r'class\s+(\w+)\(.*Model.*\):(.*?)(?=\n\n|\nclass|\nfunction|\Z)',
                r'class\s+(\w+)\(.*BaseModel.*\):(.*?)(?=\n\n|\nclass|\nfunction|\Z)',
            ]
            
            for pattern in python_patterns:
                matches = re.finditer(pattern, content, re.DOTALL | re.MULTILINE)
                for match in matches:
                    model_name = match.group(1)
                    model_body = match.group(2)
                    
                    fields = self._extract_fields_from_model_body(model_body)
                    if fields:
                        schemas[model_name] = DataSchema(
                            model_name=model_name,
                            fields=fields,
                            source_refs=[source_ref] if source_ref else [],
                            evidence_ids=[f"E-SCHEMA-{model_name}"],
                        )
                        
        except Exception as e:
            logger.warning(f"Failed to extract data schemas: {e}")
            
        return schemas
    
    def _extract_fields_from_model_body(self, body: str) -> Dict[str, str]:
        """Extract field definitions from model body."""
        fields = {}
        
        try:
            # Common field patterns
            field_patterns = [
                r'(\w+)\s*=\s*Column\(([^)]+)\)',          # SQLAlchemy
                r'(\w+):\s*(\w+(?:\[.*?\])?)',             # Pydantic/typing
                r'(\w+)\s*=\s*models\.(\w+Field)',         # Django
            ]
            
            for pattern in field_patterns:
                matches = re.finditer(pattern, body, re.MULTILINE)
                for match in matches:
                    field_name = match.group(1)
                    field_type = match.group(2)
                    fields[field_name] = field_type
                    
        except Exception as e:
            logger.warning(f"Failed to extract fields from model body: {e}")
            
        return fields
    
    def _extract_framework_config(self, content: str) -> Dict[str, Any]:
        """Extract framework configuration patterns."""
        config = {}
        
        try:
            # Try to parse as JSON configuration
            if content.strip().startswith('{'):
                json_config = json.loads(content)
                if 'testMatch' in json_config:  # Jest config
                    config['jest'] = json_config
                elif 'use' in json_config and 'projects' in json_config:  # Playwright
                    config['playwright'] = json_config
                    
        except Exception as e:
            logger.warning(f"Failed to extract framework config: {e}")
            
        return config
    
    def _infer_element_type(self, selector: str) -> str:
        """Infer element type from selector."""
        if 'button' in selector.lower() or 'btn' in selector.lower():
            return 'button'
        elif 'input' in selector.lower():
            return 'input'
        elif 'form' in selector.lower():
            return 'form'
        elif 'link' in selector.lower() or 'a[' in selector.lower():
            return 'link'
        else:
            return 'element'
    
    def _infer_element_type_from_context(self, content: str, value: str) -> str:
        """Infer element type from surrounding context."""
        value_context = content[max(0, content.find(value) - 100):content.find(value) + 100]
        
        if '<button' in value_context or 'Button' in value_context:
            return 'button'
        elif '<input' in value_context or 'Input' in value_context:
            return 'input'
        elif '<form' in value_context or 'Form' in value_context:
            return 'form'
        elif '<a' in value_context or 'Link' in value_context:
            return 'link'
        else:
            return 'element'
    
    def _infer_base_url(self) -> Optional[str]:
        """Infer base URL from configuration files or environment."""
        try:
            # Query for configuration files that might contain base URLs
            config_results = self.vector_store.query_similar(
                query_text="base_url baseURL API_URL SERVER_URL localhost development production",
                n_results=min(5, self.num_context_docs),
                metadata_filter={"file_type": [".json", ".js", ".py", ".env", ".yaml"]}
            )
            
            if config_results and config_results.get('documents'):
                for doc in config_results['documents'][0]:
                    url = self._extract_base_url_from_config(doc)
                    if url:
                        return url
                        
        except Exception as e:
            logger.warning(f"Failed to infer base URL: {e}")
            
        return "http://localhost:8000"  # Default fallback
    
    def _extract_base_url_from_config(self, content: str) -> Optional[str]:
        """Extract base URL from configuration content."""
        url_patterns = [
            r'base_?url[\'\":\s]+(https?://[^\s\'\"]+)',
            r'API_?URL[\'\":\s]+(https?://[^\s\'\"]+)',
            r'SERVER_?URL[\'\":\s]+(https?://[^\s\'\"]+)',
        ]
        
        for pattern in url_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)
                
        return None