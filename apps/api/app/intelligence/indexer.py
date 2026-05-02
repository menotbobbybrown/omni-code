"""
Codebase Indexer - AST-aware chunking and vector search for code intelligence.
"""
import os
import ast
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass
from pathlib import Path
import structlog
from datetime import datetime

logger = structlog.get_logger()

# Supported file extensions and their AST parsers
SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".rb": "ruby",
}

# Patterns for semantic chunking
CHUNK_PATTERNS = {
    "function": r"def\s+(\w+)\s*\(",
    "class": r"class\s+(\w+)\s*[:\(]",
    "async_function": r"async\s+def\s+(\w+)\s*\(",
    "arrow_function": r"const\s+(\w+)\s*=\s*\(",
    "component": r"function\s+(\w+[Cc]omponent)\s*\(",
}


@dataclass
class CodeChunk:
    """Represents a chunk of code with metadata for indexing."""
    file_path: str
    chunk_type: str  # function, class, module, etc.
    name: str
    start_line: int
    end_line: int
    content: str
    signature: Optional[str] = None
    imports: List[str] = None
    docstring: Optional[str] = None
    language: str = "unknown"
    
    def __post_init__(self):
        if self.imports is None:
            self.imports = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "chunk_type": self.chunk_type,
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "signature": self.signature,
            "imports": self.imports,
            "docstring": self.docstring,
            "language": self.language
        }


class PythonIndexer:
    """AST-based indexer for Python files."""
    
    def __init__(self, file_path: str, content: str):
        self.file_path = file_path
        self.content = content
        self.tree = None
        self.chunks: List[CodeChunk] = []
        
    def parse(self) -> bool:
        """Parse the Python file into an AST."""
        try:
            self.tree = ast.parse(self.content)
            return True
        except SyntaxError as e:
            logger.error(
                "python_parse_failed",
                file_path=self.file_path,
                error=str(e)
            )
            return False
    
    def extract_imports(self) -> List[str]:
        """Extract all imports from the file."""
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports
    
    def extract_docstring(self, node: ast.AST) -> Optional[str]:
        """Extract docstring from a node."""
        docstring = ast.get_docstring(node)
        if docstring:
            # Truncate if too long
            if len(docstring) > 500:
                docstring = docstring[:500] + "..."
        return docstring
    
    def extract_function_signature(self, node: ast.FunctionDef) -> str:
        """Extract function signature."""
        args = node.args
        params = []
        
        # Get default values for positional args
        defaults = list(node.args.defaults)
        num_defaults = len(defaults)
        num_args = len(args.args)
        
        for i, arg in enumerate(args.args):
            param_name = arg.arg
            
            # Check if this arg has a default
            default_idx = i - (num_args - num_defaults)
            if default_idx >= 0:
                param_name += "=..."
            
            params.append(param_name)
        
        # Add *args and **kwargs
        if args.vararg:
            params.append(f"*{args.vararg.arg}")
        if args.kwarg:
            params.append(f"**{args.kwarg.arg}")
        
        return f"def {node.name}({', '.join(params)})"
    
    def extract_class_signature(self, node: ast.ClassDef) -> str:
        """Extract class signature with base classes."""
        bases = [ast.unparse(base) for base in node.bases]
        if node.decorator_list:
            decorators = [ast.unparse(d) for d in node.decorator_list]
            return f"@decorator\nclass {node.name}({', '.join(bases)})"
        return f"class {node.name}({', '.join(bases)})"
    
    def index(self) -> List[CodeChunk]:
        """Index all code elements in the file."""
        if not self.tree:
            return []
        
        imports = self.extract_imports()
        
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.FunctionDef):
                self._process_function(node, imports)
            elif isinstance(node, ast.AsyncFunctionDef):
                self._process_async_function(node, imports)
            elif isinstance(node, ast.ClassDef):
                self._process_class(node, imports)
        
        # If no chunks found, add the whole file as a module chunk
        if not self.chunks:
            self.chunks.append(CodeChunk(
                file_path=self.file_path,
                chunk_type="module",
                name=os.path.basename(self.file_path),
                start_line=1,
                end_line=len(self.content.splitlines()),
                content=self.content[:5000],  # Limit content size
                imports=imports,
                language="python"
            ))
        
        return self.chunks
    
    def _process_function(self, node: ast.FunctionDef, file_imports: List[str]):
        """Process a function definition."""
        start_line = node.lineno
        end_line = node.end_lineno or start_line
        
        # Get the source code for this function
        lines = self.content.splitlines()
        if start_line <= len(lines) and end_line <= len(lines):
            content = "\n".join(lines[start_line - 1:end_line])
        else:
            content = ast.unparse(node)
        
        self.chunks.append(CodeChunk(
            file_path=self.file_path,
            chunk_type="function",
            name=node.name,
            start_line=start_line,
            end_line=end_line,
            content=content,
            signature=self.extract_function_signature(node),
            imports=list(file_imports),
            docstring=self.extract_docstring(node),
            language="python"
        ))
        
        # Also index inner classes and functions
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                self._process_class(child, file_imports, parent_name=node.name)
            elif isinstance(child, ast.FunctionDef):
                self._process_function(child, file_imports, parent_name=node.name)
    
    def _process_async_function(self, node: ast.AsyncFunctionDef, file_imports: List[str], parent_name: str = None):
        """Process an async function definition."""
        self._process_function(node, file_imports, parent_name)
    
    def _process_class(self, node: ast.ClassDef, file_imports: List[str], parent_name: str = None):
        """Process a class definition."""
        start_line = node.lineno
        end_line = node.end_lineno or start_line
        
        # Get the source code for this class
        lines = self.content.splitlines()
        if start_line <= len(lines) and end_line <= len(lines):
            content = "\n".join(lines[start_line - 1:end_line])
        else:
            content = ast.unparse(node)
        
        prefix = f"{parent_name}." if parent_name else ""
        
        self.chunks.append(CodeChunk(
            file_path=self.file_path,
            chunk_type="class",
            name=f"{prefix}{node.name}",
            start_line=start_line,
            end_line=end_line,
            content=content,
            signature=self.extract_class_signature(node),
            imports=list(file_imports),
            docstring=self.extract_docstring(node),
            language="python"
        ))


class GenericIndexer:
    """Fallback indexer for languages without AST support."""
    
    def __init__(self, file_path: str, content: str):
        self.file_path = file_path
        self.content = content
        self.chunks: List[CodeChunk] = []
    
    def index(self) -> List[CodeChunk]:
        """Index using pattern matching."""
        language = self._detect_language()
        
        # Try to extract functions and classes using patterns
        chunks = []
        
        # Function patterns
        function_pattern = r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\([^)]*\)"
        for match in re.finditer(function_pattern, self.content):
            name = match.group(1)
            start_line = self.content[:match.start()].count('\n') + 1
            end_line = self.content[:match.end()].count('\n') + 1
            
            chunks.append(CodeChunk(
                file_path=self.file_path,
                chunk_type="function",
                name=name,
                start_line=start_line,
                end_line=end_line,
                content=match.group(0),
                language=language
            ))
        
        # Class patterns
        class_pattern = r"(?:export\s+)?class\s+(\w+)(?:\s+extends\s+\w+)?\s*\{"
        for match in re.finditer(class_pattern, self.content):
            name = match.group(1)
            start_line = self.content[:match.start()].count('\n') + 1
            end_line = self.content[:match.end()].count('\n') + 1
            
            chunks.append(CodeChunk(
                file_path=self.file_path,
                chunk_type="class",
                name=name,
                start_line=start_line,
                end_line=end_line,
                content=match.group(0),
                language=language
            ))
        
        # React component patterns
        component_pattern = r"(?:export\s+)?const\s+(\w+[Cc]omponent)\s*=\s*(?:\(?[^)]*\)?\s*=>?|function)\s*\("
        for match in re.finditer(component_pattern, self.content):
            name = match.group(1)
            start_line = self.content[:match.start()].count('\n') + 1
            end_line = self.content[:match.end()].count('\n') + 1
            
            chunks.append(CodeChunk(
                file_path=self.file_path,
                chunk_type="component",
                name=name,
                start_line=start_line,
                end_line=end_line,
                content=match.group(0),
                language=language
            ))
        
        if chunks:
            self.chunks = chunks
        else:
            # Fallback to file-level chunk
            self.chunks.append(CodeChunk(
                file_path=self.file_path,
                chunk_type="module",
                name=os.path.basename(self.file_path),
                start_line=1,
                end_line=self.content.count('\n') + 1,
                content=self.content[:5000],
                language=language
            ))
        
        return self.chunks
    
    def _detect_language(self) -> str:
        """Detect language from file extension."""
        ext = os.path.splitext(self.file_path)[1].lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".java": "java",
            ".rs": "rust",
            ".rb": "ruby",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }
        return lang_map.get(ext, "unknown")


class CodebaseIndexer:
    """
    Main indexer that orchestrates codebase indexing and vector storage.
    
    Features:
    - AST-aware chunking for Python
    - Pattern-based chunking for other languages
    - Incremental indexing (only changed files)
    - Vector embedding storage
    """
    
    def __init__(self, workspace_id: int, workspace_path: str):
        self.workspace_id = workspace_id
        self.workspace_path = workspace_path
        self.embedding_model = None
        self.db = None
        
    def initialize(self):
        """Initialize the indexer with database and embedding model."""
        try:
            from app.database.session import SessionLocal
            from app.core.embedding import get_embedding_model
            
            self.db = SessionLocal()
            self.embedding_model = get_embedding_model()
            logger.info("indexer_initialized", workspace_id=self.workspace_id)
        except Exception as e:
            logger.error("indexer_init_failed", error=str(e))
            raise
    
    def index_file(self, file_path: str) -> List[CodeChunk]:
        """
        Index a single file and return chunks.
        
        Args:
            file_path: Absolute path to the file
            
        Returns:
            List of CodeChunk objects
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.warning("failed_to_read_file", file_path=file_path, error=str(e))
            return []
        
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == ".py":
            indexer = PythonIndexer(file_path, content)
            if indexer.parse():
                return indexer.index()
        
        # Fallback to generic indexer
        indexer = GenericIndexer(file_path, content)
        return indexer.index()
    
    def index_directory(self, path: str = None, exclude_patterns: List[str] = None) -> List[CodeChunk]:
        """
        Index all supported files in a directory.
        
        Args:
            path: Directory path to index (defaults to workspace root)
            exclude_patterns: List of glob patterns to exclude
            
        Returns:
            List of all CodeChunk objects
        """
        if path is None:
            path = self.workspace_path
        
        if exclude_patterns is None:
            exclude_patterns = [
                "**/node_modules/**",
                "**/venv/**",
                "**/__pycache__/**",
                "**/.git/**",
                "**/dist/**",
                "**/build/**",
                "**/.venv/**",
                "**/env/**",
                "**/*.min.js",
                "**/*.bundle.js",
            ]
        
        all_chunks = []
        
        for root, dirs, files in os.walk(path):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not self._is_excluded(os.path.join(root, d), exclude_patterns)]
            
            for file in files:
                file_path = os.path.join(root, file)
                
                if self._is_excluded(file_path, exclude_patterns):
                    continue
                
                ext = os.path.splitext(file)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                
                chunks = self.index_file(file_path)
                all_chunks.extend(chunks)
        
        logger.info(
            "directory_indexed",
            workspace_id=self.workspace_id,
            path=path,
            files_processed=len(all_chunks),
            chunks_created=len(all_chunks)
        )
        
        return all_chunks
    
    def _is_excluded(self, path: str, patterns: List[str]) -> bool:
        """Check if a path matches any exclusion pattern."""
        from pathlib import Path
        
        path_obj = Path(path)
        for pattern in patterns:
            if Path(pattern).match(path):
                return True
            if pattern.replace("**/", "") in str(path_obj.parts):
                return True
        return False
    
    def store_chunks(self, chunks: List[CodeChunk]) -> int:
        """
        Store chunks in the database with vector embeddings.
        
        Args:
            chunks: List of CodeChunk objects to store
            
        Returns:
            Number of chunks stored
        """
        if not self.db or not self.embedding_model:
            self.initialize()
        
        stored_count = 0
        
        for chunk in chunks:
            try:
                # Generate embedding
                embedding_text = f"{chunk.name} {chunk.content[:500]}"
                embedding = self.embedding_model.embed_query(embedding_text)
                
                # Create or update code chunk in database
                from app.database.models import CodeChunk as DBCodeChunk
                
                existing = self.db.query(DBCodeChunk).filter(
                    DBCodeChunk.workspace_id == self.workspace_id,
                    DBCodeChunk.file_path == chunk.file_path,
                    DBCodeChunk.name == chunk.name,
                    DBCodeChunk.chunk_type == chunk.chunk_type
                ).first()
                
                if existing:
                    existing.content = chunk.content
                    existing.embedding = embedding
                    existing.signature = chunk.signature
                    existing.imports = chunk.imports
                else:
                    db_chunk = DBCodeChunk(
                        workspace_id=self.workspace_id,
                        file_path=chunk.file_path,
                        content=chunk.content,
                        embedding=embedding,
                        signature=chunk.signature,
                        imports=chunk.imports,
                        chunk_type=chunk.chunk_type,
                        name=chunk.name
                    )
                    self.db.add(db_chunk)
                
                stored_count += 1
                
            except Exception as e:
                logger.error(
                    "chunk_storage_failed",
                    file_path=chunk.file_path,
                    chunk_name=chunk.name,
                    error=str(e)
                )
        
        self.db.commit()
        
        logger.info(
            "chunks_stored",
            workspace_id=self.workspace_id,
            count=stored_count
        )
        
        return stored_count
    
    def search_similar(self, query: str, limit: int = 5, chunk_types: List[str] = None) -> List[Dict]:
        """
        Search for code chunks similar to the query.
        
        Args:
            query: Search query
            limit: Maximum number of results
            chunk_types: Filter by chunk types (function, class, etc.)
            
        Returns:
            List of matching chunks with relevance scores
        """
        if not self.db or not self.embedding_model:
            self.initialize()
        
        try:
            query_embedding = self.embedding_model.embed_query(query)
            
            from app.database.models import CodeChunk as DBCodeChunk
            
            db_query = self.db.query(DBCodeChunk).filter(
                DBCodeChunk.workspace_id == self.workspace_id
            )
            
            if chunk_types:
                db_query = db_query.filter(DBCodeChunk.chunk_type.in_(chunk_types))
            
            results = db_query.order_by(
                DBCodeChunk.embedding.cosine_distance(query_embedding)
            ).limit(limit).all()
            
            return [
                {
                    "file_path": r.file_path,
                    "name": r.name,
                    "chunk_type": r.chunk_type,
                    "content": r.content,
                    "signature": r.signature,
                    "relevance": 1 - getattr(r.embedding, 'cosine_distance', lambda x: 0.5)(query_embedding)
                }
                for r in results
            ]
            
        except Exception as e:
            logger.error("search_failed", error=str(e))
            return []
    
    def get_file_structure(self, path: str = None) -> Dict[str, Any]:
        """
        Get a tree view of the codebase structure.
        
        Args:
            path: Directory path (defaults to workspace root)
            
        Returns:
            Dictionary representing the file tree
        """
        if path is None:
            path = self.workspace_path
        
        tree = {
            "name": os.path.basename(path) or path,
            "type": "directory",
            "children": []
        }
        
        try:
            for item in sorted(os.listdir(path)):
                item_path = os.path.join(path, item)
                
                if os.path.isdir(item_path):
                    if not self._is_excluded(item_path, ["**/node_modules/**", "**/.git/**"]):
                        tree["children"].append(self.get_file_structure(item_path))
                else:
                    ext = os.path.splitext(item)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        tree["children"].append({
                            "name": item,
                            "type": "file",
                            "extension": ext,
                            "language": SUPPORTED_EXTENSIONS[ext]
                        })
        except PermissionError:
            pass
        
        return tree
    
    def delete_file_chunks(self, file_path: str):
        """Delete all chunks for a specific file."""
        if not self.db:
            self.initialize()
        
        from app.database.models import CodeChunk as DBCodeChunk
        
        self.db.query(DBCodeChunk).filter(
            DBCodeChunk.file_path == file_path,
            DBCodeChunk.workspace_id == self.workspace_id
        ).delete()
        self.db.commit()
        
        logger.info("file_chunks_deleted", file_path=file_path)


def index_workspace(workspace_id: int, workspace_path: str) -> Dict[str, Any]:
    """
    Main entry point for indexing a workspace.
    
    Args:
        workspace_id: The workspace ID
        workspace_path: Path to the workspace directory
        
    Returns:
        Summary of indexing results
    """
    indexer = CodebaseIndexer(workspace_id, workspace_path)
    
    try:
        indexer.initialize()
        
        # Index all files
        chunks = indexer.index_directory()
        
        # Store in database
        stored = indexer.store_chunks(chunks)
        
        return {
            "status": "success",
            "workspace_id": workspace_id,
            "chunks_indexed": len(chunks),
            "chunks_stored": stored
        }
        
    finally:
        if indexer.db:
            indexer.db.close()