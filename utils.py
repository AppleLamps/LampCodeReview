import os
import zipfile
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import List, Dict, Tuple, Any, Optional, Set
from config import (
    SUPPORTED_EXTS_SET, MAX_TOTAL_SIZE, MAX_FILE_SIZE,
    MAX_DECOMPRESSION_RATIO, BINARY_RATIO_THRESHOLD,
    SUMMARY_MODE_HEAD_CHARS, SUMMARY_MODE_TAIL_CHARS,
)
import logging

logger = logging.getLogger(__name__)


def is_supported_file(filename: str) -> bool:
    """Check if the filename uses one of the supported extensions with O(1) lookup."""
    try:
        if not filename or not isinstance(filename, str):
            return False
        lowercase_name = filename.lower()
        # Use rfind for better performance on long filenames
        dot_index = lowercase_name.rfind('.')
        if dot_index == -1:
            return False
        ext = lowercase_name[dot_index:]
        return ext in SUPPORTED_EXTS_SET
    except (AttributeError, TypeError) as e:
        logger.debug(f"Error checking file support for '{filename}': {e}")
        return False


def sanitize_zip_member_path(member_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Return a safe, normalized path for a ZIP member or an error reason."""
    try:
        if not member_name or not isinstance(member_name, str):
            return None, "invalid path name"
        
        normalized = member_name.replace("\\", "/")
        pure_path = PurePosixPath(normalized)

        if pure_path.is_absolute():
            return None, "absolute path"

        parts = [part for part in pure_path.parts if part not in ("", ".")]
        if not parts:
            return None, "empty or hidden path"

        if any(part == ".." for part in parts):
            return None, "path traversal"

        safe_path = "/".join(parts)
        return safe_path, None
    except (ValueError, TypeError) as e:
        logger.debug(f"Error sanitizing path '{member_name}': {e}")
        return None, "invalid path"


def _decoded_length(raw_content: bytes) -> int:
    """Count the length of the decoded string without loading all of it."""
    try:
        return len(raw_content.decode('utf-8'))
    except UnicodeDecodeError:
        return len(raw_content.decode('utf-8', errors='replace'))


def _safe_truncate_bytes(raw_content: bytes, max_bytes: int, encoding: str = 'utf-8') -> bytes:
    """Truncate raw bytes at a valid character boundary for the given encoding."""
    if len(raw_content) <= max_bytes:
        return raw_content
    truncated = raw_content[:max_bytes]
    if encoding.lower().replace('-', '').replace('_', '') in ('utf8', 'utf16', 'utf32'):
        while max_bytes > 0:
            try:
                truncated.decode(encoding)
                break
            except UnicodeDecodeError as e:
                if e.start is not None and e.start < max_bytes:
                    max_bytes = e.start
                    truncated = raw_content[:max_bytes]
                else:
                    max_bytes -= 1
                    truncated = raw_content[:max_bytes]
    return truncated


def _decode_and_validate_content(raw_content: bytes, filename: str, warnings: List[str], max_chars: Optional[int] = None) -> Optional[str]:
    """Decode and validate file content. Returns decoded content or None if invalid.

    Tries a cascade of encodings: UTF-8 (with BOM stripped), UTF-8, latin-1,
    cp1252, and falls back to UTF-8 with replacement characters.
    Rejects files that appear to be binary (high ratio of non-printable chars).
    """
    # Strip BOM
    if raw_content.startswith(b'\xef\xbb\xbf'):
        raw_content = raw_content[3:]

    decoded_content = None
    encoding_used = None

    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            decoded_content = raw_content.decode(encoding)
            encoding_used = encoding
            break
        except UnicodeDecodeError:
            continue

    if decoded_content is None:
        decoded_content = raw_content.decode('utf-8', errors='replace')
        encoding_used = 'utf-8 (with replacement chars)'
        warnings.append(f"⚠️ '{filename}' decoded with replacement characters. Review may be unreliable.")

    # Reject binary files
    if len(decoded_content) > 0:
        non_printable = sum(1 for c in decoded_content if ord(c) < 32 and c not in '\n\r\t')
        ratio = non_printable / len(decoded_content)
        if ratio > BINARY_RATIO_THRESHOLD:
            warnings.append(f"⚠️ '{filename}' appears to be binary ({ratio:.0%} non-printable). Skipping.")
            return None

    stripped = decoded_content.strip()

    if not stripped:
        warnings.append(f"⚠️ File '{filename}' is empty or contains only whitespace. Skipping.")
        return None

    if len(stripped) < 10:
        warnings.append(f"⚠️ File '{filename}' is too short for meaningful analysis. Skipping.")
        return None

    if max_chars is not None and len(decoded_content) > max_chars:
        decoded_content = decoded_content[:max_chars]

    return decoded_content


def _process_zip_file(uploaded_file: Any, code_contents: List[Dict[str, str]], warnings: List[str], max_file_size: int, upload_metadata: Dict) -> None:
    """Process a ZIP file and extract supported code files."""
    try:
        with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                try:
                    if file_info.is_dir():
                        continue

                    safe_filename, error_reason = sanitize_zip_member_path(file_info.filename)
                    if error_reason:
                        logger.debug(f"Skipping {file_info.filename}: {error_reason}")
                        upload_metadata['skipped_files'].append({
                            'name': file_info.filename,
                            'reason': f'zip_path_error: {error_reason}'
                        })
                        continue

                    if not safe_filename:
                        continue

                    # Reject suspicious compression ratios (ZIP bomb)
                    if file_info.file_size > 0 and file_info.compress_size > 0:
                        ratio = file_info.file_size / file_info.compress_size
                        if ratio > MAX_DECOMPRESSION_RATIO:
                            warnings.append(f"⚠️ Skipping potential ZIP bomb: {safe_filename} (ratio {ratio:.0f}:1)")
                            upload_metadata['skipped_files'].append({
                                'name': safe_filename,
                                'reason': 'zip_bomb_suspected'
                            })
                            continue

                    if file_info.file_size > max_file_size:
                        warnings.append(f"⚠️ Skipping large file in ZIP: {safe_filename} ({file_info.file_size} bytes)")
                        upload_metadata['skipped_files'].append({
                            'name': safe_filename,
                            'reason': 'file_too_large'
                        })
                        continue

                    # Filter dot-directories (e.g. .git/) and unsupported files
                    path_parts = safe_filename.split('/')
                    if (not is_supported_file(safe_filename)
                            or safe_filename.startswith('.')
                            or any(part.startswith('.') and part not in ('.', '..') for part in path_parts)):
                        continue

                    try:
                        with zip_ref.open(file_info) as file:
                            content = file.read()
                    except IOError as e:
                        logger.warning(f"Failed to read '{safe_filename}' from ZIP: {e}")
                        warnings.append(f"⚠️ Could not read '{safe_filename}' from ZIP. Skipping.")
                        continue

                    if len(content) > max_file_size:
                        content = _safe_truncate_bytes(content, max_file_size)
                        warnings.append(f"⚠️ File '{safe_filename}' truncated to {max_file_size // 1024**2}MB")
                        upload_metadata['truncated_files'].append(safe_filename)

                    decoded_content = _decode_and_validate_content(content, safe_filename, warnings)
                    if decoded_content:
                        code_contents.append({
                            'filename': safe_filename,
                            'content': decoded_content
                        })
                except Exception as e:
                    logger.error(f"Error processing file in ZIP '{file_info.filename}': {e}")
                    continue
    except zipfile.BadZipFile as e:
        logger.warning(f"Invalid ZIP file '{uploaded_file.name}': {e}")
        warnings.append(f"⚠️ '{uploaded_file.name}' is not a valid ZIP file. Skipping.")
    except Exception as e:
        logger.error(f"Error extracting ZIP file '{uploaded_file.name}': {e}")
        warnings.append(f"⚠️ Error processing ZIP file '{uploaded_file.name}'. Skipping.")


def _process_regular_file(uploaded_file: Any, code_contents: List[Dict[str, str]], warnings: List[str], max_file_size: int, upload_metadata: Dict) -> None:
    """Process a regular (non-ZIP) uploaded file."""
    try:
        if not is_supported_file(uploaded_file.name):
            logger.debug(f"Skipping unsupported file: {uploaded_file.name}")
            upload_metadata['skipped_files'].append({
                'name': uploaded_file.name,
                'reason': 'unsupported_extension'
            })
            return

        try:
            content = uploaded_file.read()
        except IOError as e:
            logger.warning(f"Failed to read file '{uploaded_file.name}': {e}")
            warnings.append(f"⚠️ Could not read '{uploaded_file.name}'. Skipping.")
            upload_metadata['skipped_files'].append({
                'name': uploaded_file.name,
                'reason': 'read_error'
            })
            return

        if len(content) > max_file_size:
            content = _safe_truncate_bytes(content, max_file_size)
            warnings.append(f"⚠️ File '{uploaded_file.name}' truncated to {max_file_size // 1024**2}MB")
            upload_metadata['truncated_files'].append(uploaded_file.name)

        decoded_content = _decode_and_validate_content(content, uploaded_file.name, warnings)
        if decoded_content:
            code_contents.append({
                'filename': uploaded_file.name,
                'content': decoded_content
            })
    except Exception as e:
        logger.error(f"Error processing regular file '{uploaded_file.name}': {e}")
        warnings.append(f"⚠️ Error processing '{uploaded_file.name}'. Skipping.")
        upload_metadata['skipped_files'].append({
            'name': uploaded_file.name,
            'reason': str(e)
        })


def process_uploaded_files(
    uploaded_files: List[Any]
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Process uploaded files and return code contents and warnings."""
    code_contents = []
    warnings = []
    seen_names: set = set()
    total_bytes_read = 0

    # Track upload metadata for context
    upload_metadata = {
        'timestamp': datetime.now().isoformat(),
        'source': 'local_upload',
        'total_files': len(uploaded_files),
        'total_size': 0,
        'skipped_files': [],
        'truncated_files': [],
    }

    if not uploaded_files:
        return code_contents, warnings

    try:
        for uploaded_file in uploaded_files:
            try:
                file_size = getattr(uploaded_file, 'size', None)
                if file_size is None:
                    # Fall back to reading the file to determine size
                    try:
                        uploaded_file.seek(0)
                        content_sample = uploaded_file.read()
                        file_size = len(content_sample)
                        uploaded_file.seek(0)
                    except Exception:
                        file_size = 0

                if file_size <= 0:
                    logger.warning(f"Skipping file with invalid size: {uploaded_file.name}")
                    warnings.append(f"⚠️ File '{uploaded_file.name}' has invalid size. Skipping.")
                    upload_metadata['skipped_files'].append({
                        'name': uploaded_file.name,
                        'reason': 'invalid_size'
                    })
                    continue

                if total_bytes_read + file_size > MAX_TOTAL_SIZE:
                    warnings.append(f"⚠️ Total upload size exceeded {MAX_TOTAL_SIZE // 1024**2}MB. Skipping remaining files.")
                    break

                # Deduplicate by basename
                base_name = uploaded_file.name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
                if base_name in seen_names:
                    warnings.append(f"⚠️ Duplicate filename '{base_name}'. Skipping duplicate.")
                    upload_metadata['skipped_files'].append({
                        'name': base_name,
                        'reason': 'duplicate_filename'
                    })
                    continue

                prefix_count = len(code_contents)

                if uploaded_file.name.lower().endswith('.zip'):
                    _process_zip_file(uploaded_file, code_contents, warnings, MAX_FILE_SIZE, upload_metadata)
                else:
                    _process_regular_file(uploaded_file, code_contents, warnings, MAX_FILE_SIZE, upload_metadata)

                # Only accumulate size for files that were successfully decoded
                newly_added = len(code_contents) - prefix_count
                if newly_added > 0:
                    seen_names.add(base_name)
                    total_bytes_read += file_size
                    upload_metadata['total_size'] = total_bytes_read
            except Exception as e:
                logger.error(f"Error processing file '{getattr(uploaded_file, 'name', 'unknown')}': {e}")
                warnings.append(f"⚠️ Error processing '{getattr(uploaded_file, 'name', 'unknown')}'. Skipping.")
                upload_metadata['skipped_files'].append({
                    'name': getattr(uploaded_file, 'name', 'unknown'),
                    'reason': str(e)
                })
                continue
    except Exception as e:
        logger.error(f"Critical error in process_uploaded_files: {e}")
        warnings.append(f"⚠️ Critical error processing files: {str(e)}")

    return code_contents, warnings


def detect_dependencies(code_contents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Detect import dependencies across Python and JavaScript/TypeScript files and
    reorder files so dependencies come before dependents.

    Returns:
        Files ordered: configuration first, then entry points, then utilities,
        then dependents. Within each band, dependency order is preserved.
    """
    if not code_contents:
        return []

    def _base_name(filename: str) -> str:
        """Get the basename without directory and extension."""
        return filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]

    def _file_module(filename: str) -> str:
        """Get a module name that other files might import this file as."""
        base = _base_name(filename)
        # Convert hyphens to underscores (Python convention)
        return base.replace('-', '_')

    # Build import map: file -> set of imported module names
    import_map = {}
    for item in code_contents:
        filename = item['filename']
        imports = set()
        try:
            # Python imports
            python_patterns = [
                r'from\s+([\w.]+)\s+import',
                r'import\s+([\w.]+)',
            ]
            # JS/TS imports
            js_patterns = [
                r'import\s+.*\s+from\s+["\']([^"\']+)["\']',
                r'require\s*\(\s*["\']([^"\']+)["\']\s*\)',
                r'import\s*\(\s*["\']([^"\']+)["\']\s*\)',  # dynamic import
            ]
            content = item['content']
            for pattern in python_patterns + js_patterns:
                for match in re.finditer(pattern, content):
                    module = match.group(1)
                    if module.startswith('.'):
                        # Resolve relative import against the importer's directory
                        norm_filename = filename.replace(os.sep, '/')
                        importer_dir = PurePosixPath(norm_filename).parent
                        try:
                            raw_parts = list((importer_dir / module).parts)
                            resolved_parts: list = []
                            for p in raw_parts:
                                if p == '..':
                                    if resolved_parts:
                                        resolved_parts.pop()
                                elif p != '.':
                                    resolved_parts.append(p)
                            resolved_str: Optional[str] = '/'.join(resolved_parts) if resolved_parts else None
                        except Exception:
                            resolved_str = None
                        if resolved_str:
                            candidates = [resolved_str]
                            for ext in ('.ts', '.tsx', '.js', '.jsx'):
                                candidates.append(resolved_str + ext)
                                candidates.append(resolved_str + '/index' + ext)
                            code_filenames_norm = {itm['filename'].replace(os.sep, '/'): itm for itm in code_contents}
                            for cand in candidates:
                                cand_norm = cand.lstrip('/')
                                if cand_norm in code_filenames_norm:
                                    imports.add(_file_module(cand_norm))
                                    break
                        continue
                    # Take only the top-level segment (e.g., "utils.helper" -> "utils")
                    top_module = module.split('.')[0].split('/')[0]
                    if top_module:
                        imports.add(top_module)
        except Exception as e:
            logger.debug(f"Error parsing imports in {filename}: {e}")
        import_map[filename] = imports

    # Build a reverse map: module name -> list of files that expose that module
    module_to_files = {}
    for filename in import_map:
        module = _file_module(filename)
        module_to_files.setdefault(module, []).append(filename)

    # Topological sort with stable ordering
    ordered: List[Dict[str, str]] = []
    visited = set()
    visiting = set()

    filename_to_item = {item['filename']: item for item in code_contents}

    def visit(filename: str) -> None:
        if filename in visited:
            return
        if filename in visiting:
            # Circular dependency — break the cycle
            visiting.discard(filename)
            visited.add(filename)
            return

        visiting.add(filename)

        # Visit dependencies first
        for dep_module in import_map.get(filename, set()):
            dep_files = module_to_files.get(dep_module, [])
            for other_file in dep_files:
                if other_file != filename and other_file not in visited:
                    visit(other_file)

        visiting.discard(filename)
        visited.add(filename)
        item = filename_to_item.get(filename)
        if item is not None and item not in ordered:
            ordered.append(item)

    for item in code_contents:
        visit(item['filename'])

    # Build an index of dependency-ordered files
    if not ordered:
        return code_contents

    deps_index = {item['filename']: i for i, item in enumerate(ordered)}

    # Final ordering: trust the topological sort (deps before dependents).
    # Optional category hints nudge obvious config/entry files earlier when
    # dependencies don't dictate, but never reorder against the dep graph.
    config_patterns = {
        'config', 'settings', 'configuration', 'constants', 'env',
        'pyproject', 'package.json', 'tsconfig', 'pom.xml', 'build.gradle',
    }
    entry_patterns = {
        'main', 'app', 'index', 'server', 'cli', 'manage',
    }
    test_patterns = {'test', 'tests', '__tests__', 'spec', 'specs'}

    def categorize(filename: str) -> int:
        """Lower numbers come first (config/entry before source, tests last)."""
        base = _base_name(filename).lower()
        path = filename.lower()
        if any(p in base for p in test_patterns) or '/test' in path:
            return 3
        if any(p in base for p in config_patterns) or '/config' in path:
            return 0
        if any(p in base for p in entry_patterns) or '/main' in path:
            return 0
        return 1

    # Stable, dependency-aware sort:
    # - primary key = coarse bucket (10-percentile groups) of dependency index
    #   so category hints can break ties within the same dependency layer
    # - secondary key = category hint
    BUCKET = max(1, len(ordered) // 10)

    def sort_key(item: Dict[str, Any]) -> tuple:
        deps_rank = deps_index.get(item['filename'], 1_000_000) // BUCKET
        return (deps_rank, categorize(item['filename']))

    return sorted(ordered, key=sort_key)


def detect_redundancy(code_contents: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Detect common code patterns (shared imports, repeated patterns) across files.

    Returns:
        Dict with keys:
            - imports: {import_statement: [files_using_it]}
            - docstring_style: {style_name: [files_using_it]}
            - error_handling: {pattern_name: [files_using_it]}
            - logger_setup: [files_that_set_up_a_logger]
            - common_blocks: [(normalized_block, [files])] — top repeated code blocks
    """
    patterns: Dict[str, Any] = {
        'imports': {},
        'docstring_style': {},
        'error_handling': {},
        'logger_setup': [],
        'common_blocks': [],
    }

    if not code_contents:
        return patterns

    try:
        all_blocks: Dict[str, List[str]] = {}

        for item in code_contents:
            filename = item['filename']
            content = item['content']

            # Extract imports (line-based)
            import_pattern = r'^(?:from|import|const\s+\w+\s*=\s*require|import\s+\*\s*as)\s+.+$'
            imports = set(re.findall(import_pattern, content, re.MULTILINE))
            for imp in imports:
                imp = imp.strip()
                patterns['imports'].setdefault(imp, []).append(filename)

            # Detect docstring style
            if re.search(r'"""[\s\S]*?"""', content[:500]):
                patterns['docstring_style'].setdefault('triple-double-quote', []).append(filename)
            elif re.search(r"'''[\s\S]*?'''", content[:500]):
                patterns['docstring_style'].setdefault('triple-single-quote', []).append(filename)
            elif re.search(r'/\*\*[\s\S]*?\*/', content[:500]):
                patterns['docstring_style'].setdefault('jsdoc', []).append(filename)

            # Detect error-handling patterns
            if re.search(r'\btry\s*:', content) and re.search(r'\bexcept\b', content):
                patterns['error_handling'].setdefault('try-except', []).append(filename)
            if re.search(r'\.catch\s*\(', content):
                patterns['error_handling'].setdefault('promise-catch', []).append(filename)
            if re.search(r'\bcatch\s*\(', content):
                patterns['error_handling'].setdefault('try-catch', []).append(filename)

            # Detect logger setup
            if re.search(r'logger\s*=\s*logging\.getLogger', content):
                if filename not in patterns['logger_setup']:
                    patterns['logger_setup'].append(filename)
            elif re.search(r'logging\.basicConfig', content):
                if filename not in patterns['logger_setup']:
                    patterns['logger_setup'].append(filename)

            # Detect repeated function/class signatures
            sig_patterns = [
                r'^\s*def\s+(\w+)',                          # def foo
                r'^\s*class\s+(\w+)',                        # class Foo
                r'^\s*function\s+(\w+)',                     # function foo
                r'^\s*async\s+function\s+(\w+)',             # async function foo
                r'^\s*const\s+(\w+)\s*=',                    # const foo =
                r'^\s*(?:const|let|var)\s+(\w+)\s*=\s*\(',  # const/let/var foo = (
            ]
            for pat in sig_patterns:
                for match in re.finditer(pat, content, re.MULTILINE):
                    sig = match.group(1)
                    if len(sig) > 3:  # skip very short names
                        all_blocks.setdefault(sig, []).append(filename)

        # Take only symbols repeated across 2+ files
        for sig, files in all_blocks.items():
            unique_files = sorted(set(files))
            if len(unique_files) >= 2:
                patterns['common_blocks'].append((sig, unique_files))

        # Sort common blocks by usage
        patterns['common_blocks'].sort(key=lambda x: -len(x[1]))
    except Exception as e:
        logger.debug(f"Error detecting redundancy: {e}")

    return patterns


def detect_project_context(code_contents: List[Dict[str, str]]) -> Dict[str, Any]:
    """Detect project type, frameworks, and patterns from code structure."""
    context = {
        'project_type': 'unknown',
        'frameworks': [],
        'patterns': [],
        'entry_points': [],
        'config_files': [],
        'test_files': []
    }
    
    # Framework detection patterns
    framework_patterns = {
        'django': [
            r'from\s+django\.',
            r'Django==',
            r'manage\.py',
            r'settings\.py',
            r'urls\.py'
        ],
        'flask': [
            r'from\s+flask\s+import',
            r'Flask==',
            r'@app\.route',
            r'app\.run\('
        ],
        'fastapi': [
            r'from\s+fastapi\s+import',
            r'FastAPI\(',
            r'@app\.get\(',
            r'uvicorn\.run'
        ],
        'react': [
            r'import\s+React',
            r'package\.json.*react',
            r'\.jsx?',
            r'components/'
        ],
        'node': [
            r'package\.json',
            r'node_modules/',
            r'require\(',
            r'import.*from'
        ],
        'streamlit': [
            r'import\s+streamlit',
            r'st\.',
            r'\.streamlit/'
        ]
    }
    
    # Entry point detection
    entry_point_files = [
        'main.py', 'app.py', 'index.js', 'server.js', 'run.py', 'manage.py'
    ]
    
    # Config file detection
    config_files = [
        'requirements.txt', 'package.json', 'pyproject.toml', 'setup.py',
        'Dockerfile', 'docker-compose.yml', '.env', 'config.py',
        'settings.py', 'app.yaml', 'Procfile'
    ]
    
    # Test file detection
    test_patterns = [
        r'test_.*\.py$', r'.*_test\.py$', r'.*\.spec\.js$',
        r'.*\.test\.js$', r'.*\.spec\.ts$', r'.*\.test\.ts$'
    ]
    
    filenames = [item['filename'] for item in code_contents]
    all_content = '\n'.join([item['content'][:1000] for item in code_contents])  # First 1000 chars
    
    # Detect frameworks
    for framework, patterns in framework_patterns.items():
        for pattern in patterns:
            if re.search(pattern, all_content, re.IGNORECASE) or \
               any(re.search(pattern, fname, re.IGNORECASE) for fname in filenames):
                if framework not in context['frameworks']:
                    context['frameworks'].append(framework)
    
    # Detect project type based on frameworks
    if 'django' in context['frameworks']:
        context['project_type'] = 'django'
    elif 'fastapi' in context['frameworks']:
        context['project_type'] = 'fastapi'
    elif 'flask' in context['frameworks']:
        context['project_type'] = 'flask'
    elif 'react' in context['frameworks']:
        context['project_type'] = 'react'
    elif 'streamlit' in context['frameworks']:
        context['project_type'] = 'streamlit'
    elif 'node' in context['frameworks']:
        context['project_type'] = 'node'
    
    # Detect entry points
    for item in code_contents:
        if item['filename'] in entry_point_files:
            context['entry_points'].append(item['filename'])
    
    # Detect config files
    for item in code_contents:
        if item['filename'] in config_files:
            context['config_files'].append(item['filename'])
    
    # Detect test files
    for item in code_contents:
        for pattern in test_patterns:
            if re.search(pattern, item['filename']):
                context['test_files'].append(item['filename'])
                break
    
    return context


def _base_name_for_priority(filename: str) -> str:
    """Extract the basename without directory and convert to lowercase."""
    return filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1].lower()


def prioritize_files(code_contents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Prioritize files based on importance for review."""
    if not code_contents:
        return []

    # Exact basename sets for priority scoring
    entry_points = {'main.py', 'app.py', 'index.js', 'server.js', 'run.py', 'manage.py'}
    config_files = {'config.py', 'settings.py', 'package.json', 'requirements.txt'}
    core_files = {'models.py', 'views.py', 'controllers.py', 'services.py', 'utils.py'}
    security_files = {'auth.py', 'security.py', 'permissions.py', 'middleware.py'}
    test_indicators = ('test_', '_test', '.spec.', '.test.')

    priority_scores = []

    for item in code_contents:
        filename = item['filename']
        base = _base_name_for_priority(filename)

        score = 0

        # Entry points get highest priority
        if base in entry_points:
            score += 100

        # Config files
        if base in config_files:
            score += 80

        # Core business logic
        if base in core_files:
            score += 60

        # Security/auth files
        if base in security_files:
            score += 70

        # Test files (lower priority but still important)
        if any(indicator in base for indicator in test_indicators):
            score += 40

        # File size consideration (very large files might be less critical)
        content_length = len(item['content'])
        if content_length > 5000:
            score -= 10
        elif content_length < 100:
            score -= 5

        priority_scores.append((score, item))

    # Sort by priority score (descending)
    priority_scores.sort(key=lambda x: x[0], reverse=True)

    return [item for score, item in priority_scores]


def _sanitize_for_prompt(text: str) -> str:
    """Sanitize a string for safe inclusion in an LLM prompt."""
    sanitized = ''.join(c for c in text if c.isprintable() or c in '\n\r\t')
    sanitized = sanitized.replace('`', "'")
    return sanitized


def _prompt_fence(content: str) -> str:
    """Return a markdown code fence that won't conflict with file content."""
    if '```' in content:
        return '````'
    return '```'


def construct_user_prompt(
    code_contents: List[Dict[str, str]],
    warnings: Optional[List[str]] = None,
    review_context: Optional[Dict[str, str]] = None,
    summary_mode: bool = False,
    max_file_chars: Optional[int] = None,
) -> str:
    """Construct the user prompt with comprehensive metadata, architecture overview, and organized code content.

    Args:
        code_contents: List of {"filename": str, "content": str} items.
        warnings: Optional list of processing warnings to surface.
        review_context: Optional dict of contextual information for the reviewer.
        summary_mode: If True, emit a compact prompt with truncated file bodies
            (first/last N chars per file) to reduce token use on large codebases.
        max_file_chars: Per-file character cap (after summary_mode truncation).
    """
    prompt_parts = []

    # Normalize all path separators to forward slashes
    for item in code_contents:
        item['filename'] = item['filename'].replace('\\', '/')

    # Detect project context and prioritize files
    project_context = detect_project_context(code_contents)
    prioritized_contents = prioritize_files(code_contents)
    ordered_contents = detect_dependencies(prioritized_contents)
    
    # Build file tree structure
    file_tree = {}
    for item in ordered_contents:
        path = item['filename'].split('/')
        current_level = file_tree
        for part in path[:-1]:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]
        current_level[path[-1]] = None
    
    def format_tree(tree, indent=0):
        lines = []
        for name, subtree in sorted(tree.items()):
            if subtree is None:  # It's a file
                lines.append('    ' * indent + f'📄 {name}')
            else:  # It's a directory
                lines.append('    ' * indent + f'📁 {name}/')
                lines.extend(format_tree(subtree, indent + 1))
        return lines
    
    file_tree_str = '\n'.join(format_tree(file_tree))
    
    # Detect shared patterns
    redundancy_info = detect_redundancy(ordered_contents)
    
    # Add metadata summary
    total_chars = sum(len(item['content']) for item in ordered_contents)
    total_lines = sum(item['content'].count('\n') for item in ordered_contents)
    
    # Count by language
    languages = {}
    for item in ordered_contents:
        ext = item['filename'].split('.')[-1] if '.' in item['filename'] else 'unknown'
        languages[ext] = languages.get(ext, 0) + 1
    
    # Calculate complexity hints per file
    file_stats = []
    for item in ordered_contents:
        filename = item['filename']
        content = item['content']
        lines = content.count('\n')
        chars = len(content)
        # Simple complexity: avg line length + nesting depth estimate
        avg_line_len = chars / max(lines, 1)
        nesting = content.count('    ') / max(lines, 1) * 4  # rough indent depth
        complexity = "Low" if lines < 100 and avg_line_len < 80 else (
            "High" if lines > 300 or avg_line_len > 120 or nesting > 8 else "Medium")
        lang = filename.split('.')[-1] if '.' in filename else 'unknown'
        file_stats.append({
            'filename': filename,
            'lines': lines,
            'chars': chars,
            'lang': lang,
            'complexity': complexity,
            'avg_line_len': round(avg_line_len, 1),
        })
    
    # Add submission metadata
    upload_time = datetime.now().isoformat()

    prompt_parts.append("## Code Review Request\n")
    prompt_parts.append(f"**Submission Metadata:**\n")
    prompt_parts.append(f"- Files Analyzed: {len(ordered_contents)}\n")
    prompt_parts.append(f"- Total Lines of Code: {total_lines:,}\n")
    prompt_parts.append(f"- Total Characters: {total_chars:,}\n")
    prompt_parts.append(f"- Estimated Tokens: ~{int(total_chars * 0.25):,}\n")
    prompt_parts.append(f"- Languages: {', '.join(f'{lang} ({count})' for lang, count in languages.items())}\n")
    prompt_parts.append(f"- Upload Time: {upload_time}\n")
    prompt_parts.append(f"- Source: Streamlit file upload (local/ZIP)\n\n")
    
    # Add project context
    prompt_parts.append("## Project Context\n")
    prompt_parts.append(f"- **Project Type**: {project_context['project_type']}\n")
    prompt_parts.append(f"- **Frameworks**: {', '.join(project_context['frameworks']) or 'None detected'}\n")
    prompt_parts.append(f"- **Entry Points**: {', '.join(project_context['entry_points']) or 'None detected'}\n")
    prompt_parts.append(f"- **Config Files**: {', '.join(project_context['config_files']) or 'None detected'}\n")
    prompt_parts.append(f"- **Test Files**: {', '.join(project_context['test_files']) or 'None detected'}\n\n")
    
    # Add file tree to the prompt
    prompt_parts.append("\n## Project Structure\n```\n")
    prompt_parts.append(file_tree_str)
    prompt_parts.append("\n```\n")
    
    # Add file statistics table
    prompt_parts.append("\n## File Statistics\n\n")
    prompt_parts.append("| File | Lines | Chars | Lang | Complexity |\n")
    prompt_parts.append("|------|-------|-------|------|------------|\n")
    for stat in file_stats:
        safe_name = _sanitize_for_prompt(stat['filename'])
        prompt_parts.append(f"| {safe_name} | {stat['lines']:,} | {stat['chars']:,} | {stat['lang']} | {stat['complexity']} |\n")
    prompt_parts.append("\n")
    
    if review_context:
        prompt_parts.append("## Review Request Context\n\n")
        for label, value in review_context.items():
            prompt_parts.append(f"- **{label}**: {value}\n")
        prompt_parts.append("\n")
    
    prompt_parts.append(
        "Please evaluate the provided application code and point out both code-level issues and opportunities to make the AI code review workflow itself more effective. Consider how files are processed before they are sent to you, how the API payload is constructed, and how prompts could better guide future reviews.\n\n"
    )
    
    # Add module architecture overview (data-driven from project_context)
    layers = {
        'Config Layer': project_context.get('config_files', []),
        'Entry Points': project_context.get('entry_points', []),
        'Test Layer': project_context.get('test_files', []),
        'Frameworks': project_context.get('frameworks', []),
    }
    prompt_parts.append("## Module Architecture\n\n")
    has_layer_info = any(v for v in layers.values())
    if has_layer_info:
        for layer_name, files in layers.items():
            if files:
                file_list = ', '.join(_sanitize_for_prompt(Path(f).name) for f in files[:6])
                extra = f" (+{len(files) - 6} more)" if len(files) > 6 else ""
                prompt_parts.append(f"- **{layer_name}**: `{file_list}`{extra}\n")
        prompt_parts.append("\n")
        if project_context.get('patterns'):
            prompt_parts.append("**Detected patterns**: ")
            prompt_parts.append(', '.join(project_context['patterns']))
            prompt_parts.append("\n\n")
    else:
        prompt_parts.append("The codebase is organized into layers:\n")
        prompt_parts.append("- **Configuration Layer** (config.py): Settings, constants, prompts\n")
        prompt_parts.append("- **Processing Layer** (utils.py): File handling, validation, prompt construction\n")
        prompt_parts.append("- **API Layer** (reviewer.py): OpenRouter integration, streaming, error handling\n")
        prompt_parts.append("- **UI Layer** (app.py): Streamlit interface, orchestration\n\n")
    
    # Add shared patterns section if any
    if redundancy_info:
        shared_imports = [imp for imp, files in redundancy_info.get('imports', {}).items() if len(files) > 1]
        common_blocks = redundancy_info.get('common_blocks', [])[:8]
        docstring_styles = redundancy_info.get('docstring_style', {})
        error_styles = redundancy_info.get('error_handling', {})
        logger_users = redundancy_info.get('logger_setup', [])

        if shared_imports or common_blocks or docstring_styles or error_styles or logger_users:
            prompt_parts.append("## Shared Patterns\n\n")
            if shared_imports:
                prompt_parts.append("**Common imports** used across multiple files:\n")
                for imp in sorted(shared_imports)[:10]:
                    prompt_parts.append(f"- `{imp}`\n")
                prompt_parts.append("\n")
            if common_blocks:
                prompt_parts.append("**Symbols defined across multiple files** (potential candidates for shared module):\n")
                for sym, files in common_blocks[:6]:
                    file_list = ', '.join(_sanitize_for_prompt(f.split('/')[-1]) for f in files[:4])
                    extra = f" (+{len(files) - 4} more)" if len(files) > 4 else ""
                    prompt_parts.append(f"- `{sym}()` / `class {sym}` — {file_list}{extra}\n")
                prompt_parts.append("\n")
            if docstring_styles:
                prompt_parts.append("**Docstring styles**: ")
                prompt_parts.append(", ".join(f"{style} ({len(files)})" for style, files in docstring_styles.items()))
                prompt_parts.append("\n")
            if error_styles:
                prompt_parts.append("**Error-handling styles**: ")
                prompt_parts.append(", ".join(f"{style} ({len(files)})" for style, files in error_styles.items()))
                prompt_parts.append("\n")
            if logger_users:
                prompt_parts.append(f"**Logger setup** found in: {', '.join(_sanitize_for_prompt(Path(f).name) for f in logger_users)}\n")
            prompt_parts.append("\n")
    
    # Include file processing report
    if warnings:
        prompt_parts.append("## File Processing Report\n\n")
        prompt_parts.append("**Issues Encountered:**\n")
        for warning in warnings:
            clean_warning = warning.replace("⚠️ ", "").replace("✅ ", "")
            prompt_parts.append(f"- ⚠️ {clean_warning}\n")
        prompt_parts.append("\n")
    else:
        prompt_parts.append("## File Processing Report\n\n")
        prompt_parts.append("- ✅ All files processed successfully\n\n")

    # Add file listing with statistics (in dependency order) AND truncation flags
    prompt_parts.append("## Files to Analyze\n\n")
    for i, item in enumerate(ordered_contents, 1):
        filename = item['filename']
        content = item['content']
        lines = content.count('\n')
        chars = len(content)
        lang = filename.split('.')[-1] if '.' in filename else 'unknown'

        # Check if file was truncated (original size check)
        truncation_note = ""
        if chars >= 10 * 1024 * 1024:  # 10MB limit
            truncation_note = " ⚠️ **TRUNCATED**"
        elif chars < 100 and lines < 5:
            truncation_note = " ⚠️ **VERY SMALL**"

        prompt_parts.append(f"{i}. **{_sanitize_for_prompt(filename)}** ({lines} lines, {chars} chars, {lang}){truncation_note}\n")


    # Add each file with headers (in dependency order)
    for item in ordered_contents:
        filename = item['filename']
        content = item['content']
        displayed = content

        # Apply per-file cap if requested
        if max_file_chars and len(content) > max_file_chars:
            half = max_file_chars // 2
            displayed = (
                content[:half]
                + f"\n\n... [{len(content) - max_file_chars} chars omitted for brevity] ...\n\n"
                + content[-half:]
            )

        # Apply summary mode: keep head + tail
        if summary_mode and len(displayed) > (SUMMARY_MODE_HEAD_CHARS + SUMMARY_MODE_TAIL_CHARS):
            head_chars = SUMMARY_MODE_HEAD_CHARS
            tail_chars = SUMMARY_MODE_TAIL_CHARS
            displayed = (
                displayed[:head_chars]
                + f"\n\n... [{len(displayed) - head_chars - tail_chars} chars omitted in summary mode] ...\n\n"
                + displayed[-tail_chars:]
            )

        fence = _prompt_fence(displayed)
        prompt_parts.append(f"### FILE: {_sanitize_for_prompt(filename)}\n\n")
        prompt_parts.append(f"{fence}\n{displayed}\n{fence}\n\n")

    if summary_mode:
        prompt_parts.append("\n*Note: Summary mode is active — file bodies are abbreviated. "
                            "Disable summary mode for a complete review.*\n")

    return "".join(prompt_parts)