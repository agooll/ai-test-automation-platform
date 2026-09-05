"""CLI commands for TestTeller RAG-enhanced automation generation."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

# Import core utilities
from ..core.utils.loader import with_progress_bar_sync
from ..core.data_ingestion.unified_document_parser import UnifiedDocumentParser, DocumentType
from ..core.constants import SUPPORTED_LANGUAGES, SUPPORTED_FRAMEWORKS
from ..core.vector_store.chromadb_manager import ChromaDBManager
from ..quality_gate.gate import QualityGate
from ..quality_gate.reviewer import AIReviewSkill
from ..core.llm.llm_manager import LLMManager
from ..config import settings

# Import RAG-enhanced automation components
from .parser.markdown_parser import MarkdownTestCaseParser
from .rag_enhanced_generator import RAGEnhancedTestGenerator

logger = logging.getLogger(__name__)

# Default values
DEFAULT_COLLECTION_NAME = "test_collection"
DEFAULT_OUTPUT_DIR = "./testteller_automated_tests"
DEFAULT_LANGUAGE = "python"
DEFAULT_FRAMEWORK = "pytest"


def get_collection_name(provided_name: Optional[str] = None) -> str:
    """
    Get the collection name to use, with the following priority:
    1. User-provided name
    2. Name from settings
    3. Default fallback name
    """
    if provided_name:
        return provided_name
    
    try:
        if settings and settings.chromadb and settings.chromadb.default_collection_name:
            name = settings.chromadb.default_collection_name
            logger.info(f"Using collection name from settings: {name}")
            return name
    except Exception as e:
        logger.warning(f"Failed to get collection name from settings: {e}")
    
    logger.info(f"Using default collection name: {DEFAULT_COLLECTION_NAME}")
    return DEFAULT_COLLECTION_NAME


def get_language(provided_language: Optional[str] = None) -> str:
    """Get the programming language to use."""
    if provided_language:
        return provided_language
    
    # Try environment variable
    env_language = os.getenv('AUTOMATION_LANGUAGE')
    if env_language:
        logger.info(f"Using language from environment: {env_language}")
        return env_language
    
    logger.info(f"Using default language: {DEFAULT_LANGUAGE}")
    return DEFAULT_LANGUAGE


def get_framework(provided_framework: Optional[str] = None, language: str = DEFAULT_LANGUAGE) -> str:
    """Get the test framework to use."""
    if provided_framework:
        return provided_framework
    
    # Try environment variable
    env_framework = os.getenv('AUTOMATION_FRAMEWORK')
    if env_framework:
        logger.info(f"Using framework from environment: {env_framework}")
        return env_framework
    
    # Use first supported framework for the language
    frameworks = SUPPORTED_FRAMEWORKS.get(language, [DEFAULT_FRAMEWORK])
    framework = frameworks[0]
    logger.info(f"Using default framework for {language}: {framework}")
    return framework


def get_output_dir(provided_output_dir: Optional[str] = None) -> str:
    """Get the output directory to use."""
    if provided_output_dir:
        return provided_output_dir
    
    # Try environment variable
    from_env = os.getenv('AUTOMATION_OUTPUT_DIR')
    if from_env:
        return from_env
        
    # Try from settings/config
    try:
        return settings.automation_output_dir
    except:
        pass
    
    # Use default
    return DEFAULT_OUTPUT_DIR


def validate_framework(language: str, framework: str) -> bool:
    """Validate that the framework is supported for the language."""
    return framework in SUPPORTED_FRAMEWORKS.get(language, [])


def initialize_vector_store(collection_name: str) -> ChromaDBManager:
    """Initialize vector store using configuration settings."""
    try:
        # Use settings to get ChromaDB configuration
        persist_directory = None
        if settings and settings.chromadb:
            persist_directory = getattr(settings.chromadb, 'persist_directory', None)
        
        # Fallback to environment variable or default
        if not persist_directory:
            persist_directory = os.getenv('CHROMA_DB_PERSIST_DIRECTORY', './chroma_data')
        
        # Expand user path
        persist_directory = os.path.expanduser(persist_directory)
        
        logger.info(f"Initializing vector store at: {persist_directory}")
        
        # Initialize vector store with LLM manager
        llm_manager = LLMManager()  # Uses settings configuration
        vector_store = ChromaDBManager(llm_manager, persist_directory=persist_directory)
        
        # Test connectivity by listing collections
        try:
            collections = vector_store.list_collections()
            logger.info(f"Vector store ready with {len(collections)} collections")
            return vector_store
        except Exception as e:
            logger.warning(f"Vector store connectivity test failed: {e}")
            return vector_store
            
    except Exception as e:
        logger.error(f"Failed to initialize vector store: {e}")
        raise typer.Exit(code=1) from e


def automate_command(
    input_file: Annotated[str, typer.Argument(help="Path to test cases file (supports .md, .txt, .pdf, .docx, .xlsx)")],
    collection_name: Annotated[str, typer.Option(
        "--collection-name", "-c", help="ChromaDB collection name for application context")] = None,
    language: Annotated[str, typer.Option(
        "--language", "-l", help="Programming language for test automation")] = None,
    framework: Annotated[str, typer.Option(
        "--framework", "-F", help="Test framework to use")] = None,
    output_dir: Annotated[str, typer.Option(
        "--output-dir", "-o", help="Output directory for generated tests")] = None,
    interactive: Annotated[bool, typer.Option(
        "--interactive", "-i", help="Interactive mode to select test cases")] = False,
    num_context_docs: Annotated[int, typer.Option(
        "--num-context", "-n", min=1, max=20, help="Number of context documents to retrieve")] = 5,
    verbose: Annotated[bool, typer.Option(
        "--verbose", "-v", help="Enable verbose logging")] = False
):
    """Generate automation code using RAG-enhanced approach with vector store knowledge."""
    
    # Configure logging
    if verbose:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    print("🚀 RAG-Enhanced Test Automation Generation")
    print("=" * 50)
    
    # Validate input file exists
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Error: Test cases file '{input_file}' not found.")
        raise typer.Exit(code=1)
    
    # Resolve configuration parameters
    collection_name = get_collection_name(collection_name)
    language = get_language(language)
    framework = get_framework(framework, language)
    output_dir = get_output_dir(output_dir)
    
    # Validate framework compatibility
    if not validate_framework(language, framework):
        print(f"❌ Error: Framework '{framework}' is not supported for language '{language}'.")
        print(f"Supported frameworks for {language}: {', '.join(SUPPORTED_FRAMEWORKS[language])}")
        raise typer.Exit(code=1)
    
    # Show resolved configuration
    print(f"✅ Configuration:")
    print(f"   • Language: {language}")
    print(f"   • Framework: {framework}")
    print(f"   • Collection: {collection_name}")
    print(f"   • Output: {output_dir}")
    print(f"   • Context docs: {num_context_docs}")
    
    try:
        # 1. Initialize Vector Store
        def init_vector_store():
            return initialize_vector_store(collection_name)
        
        vector_store = with_progress_bar_sync(
            init_vector_store,
            "🔍 Initializing vector store and application context..."
        )
        
        # 2. Initialize LLM Manager from settings
        def init_llm():
            return LLMManager()  # Uses configuration from settings
        
        llm_manager = with_progress_bar_sync(
            init_llm,
            "🤖 Initializing LLM for code generation..."
        )
        
        print(f"✅ RAG system ready with LLM provider: {llm_manager.provider}")
        
        # 3. Parse test cases using unified parser
        file_extension = input_path.suffix.lower()
        
        if file_extension not in ['.md', '.txt', '.pdf', '.docx', '.xlsx']:
            print(f"❌ Unsupported file format: {file_extension}")
            print("Supported formats: .md, .txt, .pdf, .docx, .xlsx")
            raise typer.Exit(code=1)
        
        # Parse document for automation
        unified_parser = UnifiedDocumentParser()
        
        def parse_operation():
            return asyncio.run(unified_parser.parse_for_automation(input_path))
        
        parsed_doc = with_progress_bar_sync(
            parse_operation,
            f"📖 Parsing test cases from {input_path.name}..."
        )
        
        # Extract test cases
        test_cases = parsed_doc.test_cases
        
        # Fallback to markdown parser if needed
        if not test_cases and file_extension == '.md':
            def fallback_parse():
                md_parser = MarkdownTestCaseParser()
                return md_parser.parse_file(input_path)
            
            test_cases = with_progress_bar_sync(
                fallback_parse,
                "🔄 Using markdown-specific parser..."
            )
        
        # Fallback for DOCX files - parse extracted content with markdown parser
        if not test_cases and file_extension == '.docx' and parsed_doc.content:
            def docx_fallback_parse():
                md_parser = MarkdownTestCaseParser()
                return md_parser.parse_content(parsed_doc.content)
            
            test_cases = with_progress_bar_sync(
                docx_fallback_parse,
                "🔄 Using DOCX content parser..."
            )
        
        # Fallback for PDF files - parse extracted content as markdown
        if not test_cases and file_extension == '.pdf' and parsed_doc.content:
            def pdf_fallback_parse():
                # Parse extracted PDF content with custom PDF parser
                return _parse_pdf_test_cases(parsed_doc.content)
            
            test_cases = with_progress_bar_sync(
                pdf_fallback_parse,
                "🔄 Using PDF content parser..."
            )
        
        if not test_cases:
            print("❌ No test cases found in the file.")
            print("💡 Ensure the file contains structured test cases in the expected format.")
            raise typer.Exit(code=1)

        # Do not generate automation from cases that have not passed the gate.
        quality_result = asyncio.run(
            QualityGate(AIReviewSkill(llm_manager)).evaluate_cases(test_cases, use_ai=True)
        )
        if quality_result.status != "PASS":
            print(f"❌ Quality gate blocked automation: {quality_result.status}")
            print(f"   {quality_result.recommendation}")
            for violation in quality_result.hard_rule_errors[:10]:
                print(f"   - {violation.field}: {violation.message}")
            for finding in quality_result.coverage_findings[:10]:
                print(f"   - {finding.requirement_id}: {finding.message}")
            raise typer.Exit(code=1)
        
        # Show parsing results
        print(f"\n✅ Test cases parsed successfully!")
        print(f"   • Found: {len(test_cases)} test cases")
        if parsed_doc.metadata.title:
            print(f"   • Document: {parsed_doc.metadata.title}")
        print(f"   • Content: {parsed_doc.metadata.word_count} words")
        
        # Interactive selection if requested
        if interactive:
            selected_cases = interactive_select_tests(test_cases)
            if not selected_cases:
                print("❌ No test cases selected.")
                raise typer.Exit(code=1)
            test_cases = selected_cases
            print(f"✅ Selected {len(test_cases)} test cases for automation")
        
        # 4. Generate automation code using RAG approach
        output_path = Path(output_dir)
        
        # Create RAG-enhanced generator
        generator = RAGEnhancedTestGenerator(
            framework=framework,
            output_dir=output_path,
            vector_store=vector_store,
            language=language,
            llm_manager=llm_manager,
            num_context_docs=num_context_docs
        )
        
        def rag_generate_operation():
            return asyncio.run(generator.generate(test_cases))
        
        generated_files = with_progress_bar_sync(
            rag_generate_operation,
            f"🧠 Generating {language}/{framework} tests with application context..."
        )
        
        # 5. Write files
        def write_operation():
            return generator.write_files(generated_files)
        
        with_progress_bar_sync(
            write_operation,
            f"📝 Writing {len(generated_files)} files to {output_dir}..."
        )
        
        # 6. Success Summary
        print(f"\n🎉 Test Generation Complete!")
        print(f"✅ Generated {len(generated_files)} files using RAG-enhanced approach:")
        
        for file_name in sorted(generated_files.keys()):
            file_path = output_path / file_name
            file_size = len(generated_files[file_name])
            print(f"   • {file_name} ({file_size:,} chars)")
        
        print(f"\n📁 Output directory: {output_path.absolute()}")
        
        # 7. Next steps
        print_next_steps(language, framework, output_path)
        
        # 8. Quality assessment
        assess_generated_quality(generated_files)
        
    except Exception as e:
        logger.error(f"Test generation failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        raise typer.Exit(code=1)


def interactive_select_tests(test_cases):
    """Interactive test case selection."""
    print("\n📋 Available test cases:")
    for i, tc in enumerate(test_cases, 1):
        objective = tc.objective[:60] + "..." if len(tc.objective) > 60 else tc.objective
        print(f"{i:3d}. [{tc.id}] {objective}")
    
    print("\nSelect test cases to automate:")
    print("  • Enter numbers separated by commas (e.g., 1,3,5)")
    print("  • Enter ranges (e.g., 1-5)")
    print("  • Enter 'all' to select all tests")
    print("  • Enter 'none' to cancel")
    
    selection = typer.prompt("\nYour selection").strip().lower()
    
    if selection == 'none':
        return []
    elif selection == 'all':
        return test_cases
    else:
        selected_indices = parse_selection(selection, len(test_cases))
        return [test_cases[i-1] for i in selected_indices]


def parse_selection(selection: str, max_index: int) -> list:
    """Parse user selection string into list of indices."""
    indices = set()
    
    for part in selection.split(','):
        part = part.strip()
        if '-' in part:
            # Range
            try:
                start, end = map(int, part.split('-'))
                indices.update(range(max(1, start), min(max_index + 1, end + 1)))
            except ValueError:
                print(f"⚠️  Invalid range: {part}")
        else:
            # Single number
            try:
                num = int(part)
                if 1 <= num <= max_index:
                    indices.add(num)
                else:
                    print(f"⚠️  Index out of range: {num}")
            except ValueError:
                print(f"⚠️  Invalid number: {part}")
    
    return sorted(indices)


def print_next_steps(language: str, framework: str, output_dir: Path):
    """Print next steps for generated tests."""
    print("\n📚 Next Steps:")
    
    if language == 'python':
        print(f"  1. cd {output_dir}")
        print("  2. pip install -r requirements.txt")
        if framework == 'pytest':
            print("  3. pytest --verbose")
            print("  4. pytest --html=report.html  # For HTML reports")
        elif framework == 'playwright':
            print("  3. playwright install  # Install browsers")
            print("  4. pytest --headed  # Run with visible browser")
        else:
            print("  3. python -m unittest discover -v")
    
    elif language in ('javascript', 'typescript'):
        print(f"  1. cd {output_dir}")
        print("  2. npm install")
        if framework == 'playwright':
            print("  3. npx playwright install")
            print("  4. npm test")
        else:
            print("  3. npm test")
    
    elif language == 'java':
        print(f"  1. cd {output_dir}")
        print("  2. mvn clean install")
        print("  3. mvn test")
        if framework == 'junit5':
            print("  4. mvn surefire-report:report  # For HTML reports")
        
    print("\n✨ RAG-Enhanced Features:")
    print("  • Tests use real application endpoints and selectors")
    print("  • Authentication flows based on discovered patterns")
    print("  • Test data matches application schemas")
    print("  • Framework best practices applied automatically")


def assess_generated_quality(generated_files: dict):
    """Assess and report on the quality of generated tests."""
    total_lines = 0
    todo_count = 0
    test_function_count = 0
    
    for file_name, content in generated_files.items():
        if file_name.endswith(('.py', '.js', '.ts')):  # Test files
            lines = content.split('\n')
            total_lines += len(lines)
            
            # Count TODOs
            todo_count += sum(1 for line in lines if 'TODO' in line or 'FIXME' in line)
            
            # Count test functions
            test_function_count += sum(1 for line in lines 
                                     if any(pattern in line for pattern in 
                                           ['def test_', 'it(', 'test(', 'describe(']))
    
    print(f"\n📊 Quality Assessment:")
    print(f"   • Total Lines of Code: {total_lines:,}")
    print(f"   • Test Functions: {test_function_count}")
    print(f"   • TODO Items: {todo_count}")
    
    # Calculate quality score
    quality_score = max(0, 100 - (todo_count * 10)) if test_function_count > 0 else 0
    print(f"   • Quality Score: {quality_score}%")
    
    if quality_score >= 90:
        print("   🟢 Excellent: Tests should run with minimal modifications")
    elif quality_score >= 70:
        print("   🟡 Good: Some minor updates may be needed")
    elif quality_score >= 50:
        print("   🟠 Fair: Some manual work may be required")
    else:
        print("   🔴 Needs work: Significant manual implementation needed")


def _parse_pdf_test_cases(content: str) -> list:
    """Parse test cases from PDF-extracted content."""
    from .parser.markdown_parser import TestCase
    import re
    
    test_cases = []
    lines = content.split('\n')
    
    # Look for test case patterns in the flattened PDF content
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for test ID patterns (E2E_1, INT_1, TECH_1, MOCK_1)
        if re.match(r'^(E2E_|INT_|TECH_|MOCK_)\d+$', line):
            test_id = line
            
            # Collect information from following lines
            feature = ""
            category = ""
            objective = ""
            
            # Look ahead for test case details
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                
                # Skip common table headers and separators
                if next_line in ['Feature', 'Category', 'Objective', 'Priority', 'High', 'Medium', 'Low', 
                               'Happy', 'Path', 'Negative', 'Technical Area', 'Focus', 'Type', 'Component Under Test']:
                    continue
                
                # Stop if we hit another test ID
                if re.match(r'^(E2E_|INT_|TECH_|MOCK_)\d+$', next_line):
                    break
                
                # Collect meaningful content
                if not feature and len(next_line) > 3 and not next_line.isdigit():
                    feature = next_line
                elif not category and next_line in ['Happy', 'Negative', 'Contract', 'Error', 'Flow', 'Performance', 'Security', 'Recovery', 'Functional', 'Unit']:
                    category = next_line
                elif not objective and len(next_line) > 10 and 'verify' in next_line.lower():
                    objective = next_line
            
            # Create test case if we have minimum required info
            if feature or objective:
                test_case = TestCase(
                    id=test_id,
                    feature=feature or "Unknown",
                    type="Journey/Flow" if test_id.startswith("E2E_") else 
                         "API" if test_id.startswith("INT_") else
                         "Technical" if test_id.startswith("TECH_") else
                         "Functional",
                    category=category or "Happy Path",
                    objective=objective or f"Test case for {test_id}"
                )
                test_cases.append(test_case)
            
            i = j if 'j' in locals() else i + 5  # Skip ahead
        else:
            i += 1
    
    return test_cases
