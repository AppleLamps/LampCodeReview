import zipfile
import re
from pathlib import Path, PurePosixPath
from typing import List, Dict, Tuple, Any, Optional, Set
from config import SUPPORTED_EXTS_SET, MAX_TOTAL_SIZE, MAX_FILE_SIZE
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


def _decode_and_validate_content(raw_content: bytes, filename: str, warnings: List[str]) -> Optional[str]:
    """Decode and validate file content. Returns decoded content or None if invalid."""
    try:
        decoded_content = raw_content.decode('utf-8')
    except UnicodeDecodeError as e:
        logger.debug(f"UTF-8 decode error for '{filename}': {e}")
        warnings.append(f"⚠️ Could not decode '{filename}' as UTF-8. Skipping.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error decoding '{filename}': {e}")
        warnings.append(f"⚠️ Error processing '{filename}'. Skipping.")
        return None

    stripped = decoded_content.strip()
    
    if not stripped:
        warnings.append(f"⚠️ File '{filename}' is empty or contains only whitespace. Skipping.")
        return None
    
    if len(stripped) < 10:
        warnings.append(f"⚠️ File '{filename}' is too short for meaningful analysis. Skipping.")
        return None
    
    return decoded_content


def _process_zip_file(uploaded_file: Any, code_contents: List[Dict[str, str]], warnings: List[str], max_file_size: int) -> None:
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
                        continue

                    if not safe_filename:
                        continue

                    if file_info.file_size > max_file_size:
                        warnings.append(f"⚠️ Skipping large file in ZIP: {safe_filename} ({file_info.file_size} bytes)")
                        continue

                    if not is_supported_file(safe_filename) or safe_filename.startswith('.'):
                        continue

                    try:
                        with zip_ref.open(file_info) as file:
                            content = file.read()
                    except IOError as e:
                        logger.warning(f"Failed to read '{safe_filename}' from ZIP: {e}")
                        warnings.append(f"⚠️ Could not read '{safe_filename}' from ZIP. Skipping.")
                        continue
                    
                    if len(content) > max_file_size:
                        content = content[:max_file_size]
                        warnings.append(f"⚠️ File '{safe_filename}' truncated to {max_file_size // 1024**2}MB")

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


def _process_regular_file(uploaded_file: Any, code_contents: List[Dict[str, str]], warnings: List[str], max_file_size: int) -> None:
    """Process a regular (non-ZIP) uploaded file."""
    try:
        if not is_supported_file(uploaded_file.name):
            logger.debug(f"Skipping unsupported file: {uploaded_file.name}")
            return

        try:
            content = uploaded_file.read()
        except IOError as e:
            logger.warning(f"Failed to read file '{uploaded_file.name}': {e}")
            warnings.append(f"⚠️ Could not read '{uploaded_file.name}'. Skipping.")
            return
        
        if len(content) > max_file_size:
            content = content[:max_file_size]
            warnings.append(f"⚠️ File '{uploaded_file.name}' truncated to {max_file_size // 1024**2}MB")

        decoded_content = _decode_and_validate_content(content, uploaded_file.name, warnings)
        if decoded_content:
            code_contents.append({
                'filename': uploaded_file.name,
                'content': decoded_content
            })
    except Exception as e:
        logger.error(f"Error processing regular file '{uploaded_file.name}': {e}")
        warnings.append(f"⚠️ Error processing '{uploaded_file.name}'. Skipping.")


def process_uploaded_files(
    uploaded_files: List[Any]
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Process uploaded files and return code contents and warnings."""
    code_contents = []
    warnings = []
    total_size = 0

    if not uploaded_files:
        return code_contents, warnings

    try:
        for uploaded_file in uploaded_files:
            try:
                file_size = getattr(uploaded_file, 'size', 0)
                if file_size <= 0:
                    logger.warning(f"Skipping file with invalid size: {uploaded_file.name}")
                    warnings.append(f"⚠️ File '{uploaded_file.name}' has invalid size. Skipping.")
                    continue
                
                total_size += file_size

                if total_size > MAX_TOTAL_SIZE:
                    warnings.append(f"⚠️ Total upload size exceeded {MAX_TOTAL_SIZE // 1024**2}MB. Skipping remaining files.")
                    break

                if uploaded_file.name.lower().endswith('.zip'):
                    _process_zip_file(uploaded_file, code_contents, warnings, MAX_FILE_SIZE)
                else:
                    _process_regular_file(uploaded_file, code_contents, warnings, MAX_FILE_SIZE)
            except Exception as e:
                logger.error(f"Error processing file '{getattr(uploaded_file, 'name', 'unknown')}': {e}")
                warnings.append(f"⚠️ Error processing '{getattr(uploaded_file, 'name', 'unknown')}'. Skipping.")
                continue
    except Exception as e:
        logger.error(f"Critical error in process_uploaded_files: {e}")
        warnings.append(f"⚠️ Critical error processing files: {str(e)}")

    return code_contents, warnings


def detect_dependencies(code_contents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Detect Python import dependencies and reorder files for logical flow.
    Returns files ordered so dependencies come before dependents.
    """
    if not code_contents:
        return []
    
    # Build import map
    import_map = {}
    for item in code_contents:
        filename = item['filename']
        imports = set()
        try:
            # Extract imports using regex
            import_patterns = [
                r'from\s+([\w.]+)\s+import',
                r'import\s+([\w.]+)',
            ]
            for pattern in import_patterns:
                for match in re.finditer(pattern, item['content']):
                    module = match.group(1).split('.')[0]  # Get top-level module
                    imports.add(module)
        except Exception as e:
            logger.debug(f"Error parsing imports in {filename}: {e}")
        import_map[filename] = imports
    
    # Topological sort: order files so dependencies come first
    ordered = []
    visited = set()
    visiting = set()
    
    def visit(filename: str) -> None:
        if filename in visited:
            return
        if filename in visiting:
            # Circular dependency, just add it
            visiting.discard(filename)
            visited.add(filename)
            return
        
        visiting.add(filename)
        
        # Visit dependencies first
        for dep_module in import_map.get(filename, set()):
            # Find if any file exports this module
            for other_file in import_map:
                if other_file != filename:
                    base_name = other_file.split('.')[0]
                    if base_name == dep_module:
                        if other_file not in visited:
                            visit(other_file)
        
        visiting.discard(filename)
        visited.add(filename)
        # Find the original item and add it
        for item in code_contents:
            if item['filename'] == filename and filename not in [o['filename'] for o in ordered]:
                ordered.append(item)
    
    # Visit all files
    for item in code_contents:
        visit(item['filename'])
    
    return ordered if ordered else code_contents


def detect_redundancy(code_contents: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Detect common code patterns (shared imports, repeated patterns) across files.
    Returns a dict of pattern type -> list of files containing it.
    """
    patterns = {
        'imports': {},
        'docstring_style': {},
        'error_handling': {}
    }
    
    try:
        for item in code_contents:
            filename = item['filename']
            content = item['content']
            
            # Extract imports
            import_pattern = r'^(?:from|import)\s+.+$'
            imports = set(re.findall(import_pattern, content, re.MULTILINE))
            for imp in imports:
                if imp not in patterns['imports']:
                    patterns['imports'][imp] = []
                patterns['imports'][imp].append(filename)
            
            # Detect error handling patterns
            if 'try:' in content and 'except' in content:
                if 'error_handling' not in patterns:
                    patterns['error_handling'] = {}
                patterns['error_handling']['try-except'] = patterns['error_handling'].get('try-except', []) + [filename]
            
            # Detect logging patterns
            if 'logging.getLogger' in content or 'logger' in content:
                if 'logging' not in patterns:
                    patterns['logging'] = {}
                patterns['logging']['logger_usage'] = patterns['logging'].get('logger_usage', []) + [filename]
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


def prioritize_files(code_contents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Prioritize files based on importance for review."""
    if not code_contents:
        return []
    
    # Priority scoring
    priority_scores = []
    
    for item in code_contents:
        filename = item['filename']
        score = 0
        
        # Entry points get highest priority
        entry_points = ['main.py', 'app.py', 'index.js', 'server.js', 'run.py', 'manage.py']
        if any(ep in filename.lower() for ep in entry_points):
            score += 100
        
        # Config files
        config_files = ['config.py', 'settings.py', 'package.json', 'requirements.txt']
        if any(cf in filename.lower() for cf in config_files):
            score += 80
        
        # Core business logic
        core_patterns = ['models.py', 'views.py', 'controllers.py', 'services.py', 'utils.py']
        if any(cp in filename.lower() for cp in core_patterns):
            score += 60
        
        # Security/auth files
        security_patterns = ['auth.py', 'security.py', 'permissions.py', 'middleware.py']
        if any(sp in filename.lower() for sp in security_patterns):
            score += 70
        
        # Test files (lower priority but still important)
        if any(test in filename.lower() for test in ['test_', '_test', '.spec.', '.test.']):
            score += 40
        
        # File size consideration (very large files might be less critical)
        content_length = len(item['content'])
        if content_length > 5000:  # Large files
            score -= 10
        elif content_length < 100:  # Very small files
            score -= 5
        
        priority_scores.append((score, item))
    
    # Sort by priority score (descending)
    priority_scores.sort(key=lambda x: x[0], reverse=True)
    
    return [item for score, item in priority_scores]


def construct_user_prompt(
    code_contents: List[Dict[str, str]],
    warnings: Optional[List[str]] = None,
    review_context: Optional[Dict[str, str]] = None
) -> str:
    """Construct the user prompt with comprehensive metadata, architecture overview, and organized code content."""
    prompt_parts = []
    
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
    
    prompt_parts.append("## Code Review Request\n")
    prompt_parts.append(f"**Submission Metadata:**\n")
    prompt_parts.append(f"- Files Analyzed: {len(ordered_contents)}")
    prompt_parts.append(f"- Total Lines of Code: {total_lines:,}")
    prompt_parts.append(f"- Total Characters: {total_chars:,}")
    prompt_parts.append(f"- Estimated Tokens: ~{int(total_chars * 0.25):,}")
    prompt_parts.append(f"- Languages: {', '.join(f'{lang} ({count})' for lang, count in languages.items())}\n")
    
    # Add project context
    prompt_parts.append("## Project Context\n")
    prompt_parts.append(f"- **Project Type**: {project_context['project_type']}")
    prompt_parts.append(f"- **Frameworks**: {', '.join(project_context['frameworks']) or 'None detected'}")
    prompt_parts.append(f"- **Entry Points**: {', '.join(project_context['entry_points']) or 'None detected'}")
    prompt_parts.append(f"- **Config Files**: {', '.join(project_context['config_files']) or 'None detected'}")
    prompt_parts.append(f"- **Test Files**: {', '.join(project_context['test_files']) or 'None detected'}\n")
    
    # Add file tree to the prompt
    prompt_parts.append("\n## Project Structure\n```\n")
    prompt_parts.append(file_tree_str)
    prompt_parts.append("\n```\n")

    if review_context:
        prompt_parts.append("## Review Request Context\n\n")
        for label, value in review_context.items():
            prompt_parts.append(f"- **{label}**: {value}\n")
        prompt_parts.append("\n")

    prompt_parts.append(
        "Please evaluate the provided application code and point out both code-level issues and opportunities to make the AI code review workflow itself more effective. Consider how files are processed before they are sent to you, how the API payload is constructed, and how prompts could better guide future reviews.\n\n"
    )

    # Add module architecture overview
    prompt_parts.append("## Module Architecture\n\n")
    prompt_parts.append("The codebase is organized into layers:\n")
    prompt_parts.append("- **Configuration Layer** (config.py): Settings, constants, prompts\n")
    prompt_parts.append("- **Processing Layer** (utils.py): File handling, validation, prompt construction\n")
    prompt_parts.append("- **API Layer** (reviewer.py): OpenRouter integration, streaming, error handling\n")
    prompt_parts.append("- **UI Layer** (app.py): Streamlit interface, orchestration\n\n")

    # Add shared patterns section if any
    if redundancy_info:
        shared_imports = [imp for imp, files in redundancy_info.get('imports', {}).items() if len(files) > 1]
        if shared_imports:
            prompt_parts.append("## Shared Patterns\n\n")
            prompt_parts.append("Common imports used across multiple files:\n")
            for imp in sorted(shared_imports)[:10]:  # Limit to 10 most common
                prompt_parts.append(f"- `{imp}`\n")
            prompt_parts.append("\n")

    # Include file processing report
    if warnings:
        prompt_parts.append("## File Processing Report\n\n")
        prompt_parts.append("**Issues Encountered:**\n")
        for warning in warnings:
            clean_warning = warning.replace("⚠️ ", "").replace("✅ ", "")
            prompt_parts.append(f"- {clean_warning}\n")
        prompt_parts.append("\n")
    else:
        prompt_parts.append("## File Processing Report\n\n")
        prompt_parts.append("- All files processed successfully\n\n")

    # Add file listing with statistics (in dependency order)
    prompt_parts.append("## Files to Analyze\n\n")
    for i, item in enumerate(ordered_contents, 1):
        filename = item['filename']
        content = item['content']
        lines = content.count('\n')
        chars = len(content)
        lang = filename.split('.')[-1] if '.' in filename else 'unknown'
        prompt_parts.append(f"{i}. **{filename}** ({lines} lines, {chars} chars, {lang})\n")
    prompt_parts.append("\n" + "="*60 + "\n\n")

    # Add each file with headers (in dependency order)
    for item in ordered_contents:
        prompt_parts.append(f"### FILE: {item['filename']}\n\n")
        prompt_parts.append(f"```\n{item['content']}\n```\n\n")

    return "".join(prompt_parts)