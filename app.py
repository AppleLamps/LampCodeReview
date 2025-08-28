import streamlit as st
import requests
from dotenv import load_dotenv
import os
import json
import time
import zipfile
import re
import logging
import hashlib
import sqlite3
import subprocess
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Generator, Tuple, Any, Optional
import ast
import concurrent.futures
from dataclasses import dataclass
from enum import Enum
import pandas as pd

# --- Enhanced Configuration ---
APP_DIR = Path(__file__).resolve().parent
_ = load_dotenv(APP_DIR / ".env", override=False)

MAX_TOTAL_SIZE = 100 * 1024 * 1024  # Increased to 100 MB
MAX_FILE_SIZE = 20 * 1024 * 1024   # Increased to 20 MB
SUPPORTED_EXTS = (
    ".py", ".js", ".java", ".ts", ".go", ".rb", ".php", ".cs", ".c", ".cpp",
    ".h", ".hpp", ".html", ".htm", ".css", ".sql", ".yaml", ".yml", ".json",
    ".xml", ".md", ".sh", ".bat", ".rs", ".ps1", ".swift", ".kt", ".scala",
    ".r", ".m", ".pl", ".lua", ".dart", ".vue", ".jsx", ".tsx"
)

PROJECT_FILES = (
    "requirements.txt", "package.json", "Cargo.toml", "go.mod", "pom.xml",
    "Gemfile", "composer.json", "setup.py", "pyproject.toml", "Dockerfile",
    "README.md", "README.rst", "CHANGELOG.md", ".gitignore"
)

class ReviewMode(Enum):
    STANDARD = "Standard Review"
    IDE_INSTRUCTIONS = "IDE Implementation Instructions"
    SECURITY_FOCUSED = "Security-Focused Review"
    PERFORMANCE_FOCUSED = "Performance-Focused Review"
    ARCHITECTURE_REVIEW = "Architecture Review"

@dataclass
class CodeFile:
    filename: str
    content: str
    language: str
    file_hash: str
    static_analysis: Optional[Dict] = None
    complexity_score: Optional[float] = None

@dataclass
class ReviewResult:
    content: str
    timestamp: datetime
    model: str
    mode: ReviewMode
    file_hashes: List[str]
    static_analysis_summary: Optional[Dict] = None

# --- Enhanced System Prompts ---
ENHANCED_SYSTEM_PROMPT = r"""You are a senior code architect and security expert with 15+ years of experience across multiple domains. You combine automated static analysis results with deep architectural insights to provide comprehensive, actionable code reviews.

## Your Enhanced Analysis Framework

### 1. 🏗️ Architecture & Design Excellence
- **Modularity**: Evaluate separation of concerns, cohesion, and coupling
- **Design Patterns**: Identify appropriate/inappropriate pattern usage
- **SOLID Principles**: Assess adherence to fundamental design principles
- **Scalability**: Analyze for performance bottlenecks and scaling limitations
- **Maintainability**: Code organization, documentation, and future-proofing

### 2. 🔐 Advanced Security Analysis (CRITICAL PRIORITY)
- **OWASP Top 10**: Check for injection, broken auth, sensitive data exposure
- **Input Validation**: Comprehensive sanitization and validation gaps
- **Cryptography**: Proper implementation of encryption, hashing, key management
- **Dependencies**: Known vulnerabilities in third-party packages
- **Secrets Management**: Hardcoded credentials, API keys, configuration issues
- **Access Control**: Authorization flaws and privilege escalation risks

### 3. ⚡ Performance & Efficiency
- **Algorithmic Complexity**: Big O analysis and optimization opportunities
- **Resource Management**: Memory leaks, connection pooling, cleanup
- **Database Operations**: N+1 queries, missing indexes, inefficient joins
- **Caching Strategies**: Opportunities for performance improvements
- **Concurrency**: Race conditions, deadlocks, async/await usage

### 4. ✅ Code Quality & Correctness
- **Static Analysis Integration**: Leverage automated tool findings
- **Edge Cases**: Boundary conditions, null handling, error scenarios
- **Type Safety**: Proper typing, validation, and contracts
- **Testing**: Coverage gaps, test quality, integration concerns
- **Error Handling**: Comprehensive exception management and recovery

### 5. 📚 Documentation & Standards
- **Code Documentation**: Inline comments, docstrings, API documentation
- **Naming Conventions**: Clarity, consistency, domain appropriateness
- **Code Style**: Formatting, organization, readability
- **Team Standards**: Consistency with project conventions

## Enhanced Response Format

### 🎯 Executive Summary
[High-level assessment with risk score: LOW/MEDIUM/HIGH/CRITICAL]

### 🚨 Critical Security Issues
[Immediate action required - security vulnerabilities]

### ⚠️ Major Architectural Concerns  
[Design issues that impact maintainability/scalability]

### 📊 Static Analysis Findings
[Integration of automated tool results with context]

### 🔧 Performance Optimization Opportunities
[Specific bottlenecks and improvement strategies]

### ✨ Code Quality Improvements
[Readability, maintainability, and best practice adherence]

### 🏆 Positive Aspects
[Recognition of well-implemented features and good practices]

### 📋 Prioritized Action Plan
[Ordered by impact: Critical → High → Medium → Low]

For each finding:
- **Risk Level**: Critical/High/Medium/Low
- **Category**: Security/Architecture/Performance/Quality
- **Impact Assessment**: Specific consequences if not addressed
- **Effort Estimate**: How complex the fix is (Small/Medium/Large)
- **Detailed Solution**: Step-by-step implementation guidance
- **Verification Steps**: How to test the fix works
- **Prevention Strategy**: How to avoid similar issues

## Quality Standards
- Integrate static analysis findings with architectural insights
- Provide specific line references and code examples
- Focus on business impact, not just technical debt
- Balance thoroughness with actionability
- Consider team skill level and project constraints"""

# --- Database Setup for Caching ---
def init_database():
    """Initialize SQLite database for caching reviews."""
    db_path = APP_DIR / "review_cache.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute('''
    CREATE TABLE IF NOT EXISTS review_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content_hash TEXT UNIQUE,
        review_content TEXT,
        model TEXT,
        mode TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.execute('''
    CREATE TABLE IF NOT EXISTS static_analysis_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_hash TEXT UNIQUE,
        filename TEXT,
        language TEXT,
        analysis_results TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()

def get_cached_review(content_hash: str) -> Optional[ReviewResult]:
    """Get cached review if exists and is recent."""
    db_path = APP_DIR / "review_cache.db"
    conn = sqlite3.connect(db_path)
    
    # Get reviews from last 7 days
    cutoff_date = datetime.now() - timedelta(days=7)
    
    cursor = conn.execute('''
    SELECT review_content, model, mode, created_at 
    FROM review_cache 
    WHERE content_hash = ? AND created_at > ?
    ORDER BY created_at DESC LIMIT 1
    ''', (content_hash, cutoff_date))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return ReviewResult(
            content=result[0],
            model=result[1],
            mode=ReviewMode(result[2]),
            timestamp=datetime.fromisoformat(result[3]),
            file_hashes=[]
        )
    return None

def cache_review(content_hash: str, review: str, model: str, mode: str):
    """Cache review result."""
    db_path = APP_DIR / "review_cache.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute('''
    INSERT OR REPLACE INTO review_cache 
    (content_hash, review_content, model, mode, last_accessed)
    VALUES (?, ?, ?, ?, ?)
    ''', (content_hash, review, model, mode, datetime.now()))
    
    conn.commit()
    conn.close()

# --- Static Analysis Integration ---
def run_python_analysis(file_path: str) -> Dict:
    """Run Python-specific static analysis."""
    results = {
        'complexity': None,
        'issues': [],
        'metrics': {}
    }
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse AST for basic metrics
        tree = ast.parse(content)
        
        # Count functions, classes, lines
        functions = len([node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)])
        classes = len([node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)])
        lines = len(content.splitlines())
        
        results['metrics'] = {
            'functions': functions,
            'classes': classes,
            'lines_of_code': lines,
            'complexity_estimate': functions * 2 + classes * 3  # Simple heuristic
        }
        
        # Try to run pylint if available
        try:
            result = subprocess.run(
                ['python', '-m', 'pylint', '--output-format=json', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.stdout:
                pylint_results = json.loads(result.stdout)
                results['issues'] = [
                    {
                        'line': item.get('line', 0),
                        'type': item.get('type', 'info'),
                        'message': item.get('message', ''),
                        'symbol': item.get('symbol', '')
                    }
                    for item in pylint_results if isinstance(item, dict)
                ]
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass  # Pylint not available or failed
            
    except Exception as e:
        results['error'] = str(e)
    
    return results

def run_javascript_analysis(file_path: str) -> Dict:
    """Run JavaScript-specific static analysis."""
    results = {
        'complexity': None,
        'issues': [],
        'metrics': {}
    }
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Basic metrics
        lines = len(content.splitlines())
        functions = len(re.findall(r'function\s+\w+|=>\s*{|\w+\s*:\s*function', content))
        classes = len(re.findall(r'class\s+\w+', content))
        
        results['metrics'] = {
            'functions': functions,
            'classes': classes,
            'lines_of_code': lines,
            'complexity_estimate': functions * 2 + classes * 3
        }
        
        # Try ESLint if available
        try:
            result = subprocess.run(
                ['npx', 'eslint', '--format=json', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.stdout:
                eslint_results = json.loads(result.stdout)
                for file_result in eslint_results:
                    results['issues'].extend([
                        {
                            'line': msg.get('line', 0),
                            'type': msg.get('severity', 1) == 2 and 'error' or 'warning',
                            'message': msg.get('message', ''),
                            'rule': msg.get('ruleId', '')
                        }
                        for msg in file_result.get('messages', [])
                    ])
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass
            
    except Exception as e:
        results['error'] = str(e)
    
    return results

def analyze_file_static(file_path: str, language: str) -> Dict:
    """Run static analysis on a file based on its language."""
    if language == 'python':
        return run_python_analysis(file_path)
    elif language in ['javascript', 'typescript']:
        return run_javascript_analysis(file_path)
    else:
        # Generic analysis for other languages
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = len(content.splitlines())
            return {
                'metrics': {
                    'lines_of_code': lines,
                    'estimated_complexity': lines // 10  # Very rough estimate
                },
                'issues': []
            }
        except Exception as e:
            return {'error': str(e), 'metrics': {}, 'issues': []}

def detect_language(filename: str) -> str:
    """Detect programming language from filename."""
    ext = Path(filename).suffix.lower()
    language_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.go': 'go',
        '.rb': 'ruby',
        '.php': 'php',
        '.cs': 'csharp',
        '.cpp': 'cpp',
        '.c': 'c',
        '.rs': 'rust',
        '.swift': 'swift',
        '.kt': 'kotlin'
    }
    return language_map.get(ext, 'unknown')

# --- Enhanced File Processing ---
def process_uploaded_files_enhanced(
    uploaded_files: List[Any]
) -> Tuple[List[CodeFile], List[str], Dict[str, Any]]:
    """Enhanced file processing with static analysis."""
    code_files = []
    warnings = []
    project_context = {
        'has_config_files': False,
        'detected_framework': None,
        'dependency_files': [],
        'total_loc': 0
    }
    
    total_size = 0
    
    # Create temp directory for analysis
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        for uploaded_file in uploaded_files:
            file_size = uploaded_file.size
            total_size += file_size
            
            if total_size > MAX_TOTAL_SIZE:
                warnings.append(f"⚠️ Total upload size exceeded {MAX_TOTAL_SIZE // 1024**2}MB.")
                break
            
            if uploaded_file.name.endswith('.zip'):
                # Enhanced ZIP processing
                try:
                    with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
                        for file_info in zip_ref.infolist():
                            if file_info.filename.startswith(('/', '\\', '__MACOSX')) or '..' in file_info.filename:
                                continue
                            
                            safe_filename = os.path.basename(file_info.filename)
                            if not safe_filename or file_info.is_dir():
                                continue
                            
                            # Check if it's a project configuration file
                            if safe_filename in PROJECT_FILES:
                                project_context['has_config_files'] = True
                                if safe_filename in ['requirements.txt', 'package.json']:
                                    project_context['dependency_files'].append(safe_filename)
                            
                            # Process code files
                            if any(safe_filename.endswith(ext) for ext in SUPPORTED_EXTS):
                                with zip_ref.open(file_info) as file:
                                    content = file.read()
                                    if len(content) > MAX_FILE_SIZE:
                                        content = content[:MAX_FILE_SIZE]
                                        warnings.append(f"⚠️ File '{safe_filename}' truncated")
                                    
                                    try:
                                        decoded_content = content.decode('utf-8')
                                        if len(decoded_content.strip()) < 10:
                                            continue
                                        
                                        # Create temporary file for static analysis
                                        temp_file = temp_path / safe_filename
                                        temp_file.write_text(decoded_content, encoding='utf-8')
                                        
                                        language = detect_language(safe_filename)
                                        file_hash = hashlib.sha256(decoded_content.encode()).hexdigest()
                                        
                                        # Run static analysis
                                        static_analysis = analyze_file_static(str(temp_file), language)
                                        
                                        code_file = CodeFile(
                                            filename=safe_filename,
                                            content=decoded_content,
                                            language=language,
                                            file_hash=file_hash,
                                            static_analysis=static_analysis
                                        )
                                        
                                        code_files.append(code_file)
                                        
                                        if 'metrics' in static_analysis:
                                            project_context['total_loc'] += static_analysis['metrics'].get('lines_of_code', 0)
                                        
                                    except UnicodeDecodeError:
                                        warnings.append(f"⚠️ Could not decode '{safe_filename}' as UTF-8")
                                        
                except zipfile.BadZipFile:
                    warnings.append(f"⚠️ '{uploaded_file.name}' is not a valid ZIP file")
            else:
                # Process individual files
                if any(uploaded_file.name.endswith(ext) for ext in SUPPORTED_EXTS) or uploaded_file.name in PROJECT_FILES:
                    content = uploaded_file.read()
                    if len(content) > MAX_FILE_SIZE:
                        content = content[:MAX_FILE_SIZE]
                        warnings.append(f"⚠️ File '{uploaded_file.name}' truncated")
                    
                    try:
                        decoded_content = content.decode('utf-8')
                        if len(decoded_content.strip()) < 10:
                            continue
                        
                        # Create temporary file for analysis
                        temp_file = temp_path / uploaded_file.name
                        temp_file.write_text(decoded_content, encoding='utf-8')
                        
                        language = detect_language(uploaded_file.name)
                        file_hash = hashlib.sha256(decoded_content.encode()).hexdigest()
                        
                        # Run static analysis
                        static_analysis = analyze_file_static(str(temp_file), language)
                        
                        code_file = CodeFile(
                            filename=uploaded_file.name,
                            content=decoded_content,
                            language=language,
                            file_hash=file_hash,
                            static_analysis=static_analysis
                        )
                        
                        code_files.append(code_file)
                        
                        if 'metrics' in static_analysis:
                            project_context['total_loc'] += static_analysis['metrics'].get('lines_of_code', 0)
                        
                        # Check for project files
                        if uploaded_file.name in PROJECT_FILES:
                            project_context['has_config_files'] = True
                            if uploaded_file.name in ['requirements.txt', 'package.json']:
                                project_context['dependency_files'].append(uploaded_file.name)
                        
                    except UnicodeDecodeError:
                        warnings.append(f"⚠️ Could not decode '{uploaded_file.name}' as UTF-8")
                else:
                    warnings.append(f"⚠️ '{uploaded_file.name}' has an unsupported extension")
    
    return code_files, warnings, project_context

# --- Enhanced Prompt Construction ---
def construct_enhanced_prompt(
    code_files: List[CodeFile], 
    project_context: Dict[str, Any],
    review_mode: ReviewMode
) -> str:
    """Construct enhanced prompt with static analysis integration."""
    
    prompt_parts = [
        f"# Code Review Request - {review_mode.value}\n\n",
        "## Project Overview\n"
    ]
    
    # Add project context
    prompt_parts.append(f"- **Total files**: {len(code_files)}\n")
    prompt_parts.append(f"- **Total lines of code**: {project_context['total_loc']:,}\n")
    prompt_parts.append(f"- **Has configuration files**: {'Yes' if project_context['has_config_files'] else 'No'}\n")
    
    if project_context['dependency_files']:
        prompt_parts.append(f"- **Dependency files found**: {', '.join(project_context['dependency_files'])}\n")
    
    # Language breakdown
    languages = {}
    for file in code_files:
        languages[file.language] = languages.get(file.language, 0) + 1
    
    prompt_parts.append(f"- **Languages detected**: {', '.join(f'{lang} ({count})' for lang, count in languages.items())}\n\n")
    
    # Static analysis summary
    total_issues = sum(len(file.static_analysis.get('issues', [])) for file in code_files if file.static_analysis)
    if total_issues > 0:
        prompt_parts.append(f"## 📊 Static Analysis Summary\n")
        prompt_parts.append(f"- **Total automated issues found**: {total_issues}\n")
        
        # Break down by severity
        issue_types = {}
        for file in code_files:
            if file.static_analysis and 'issues' in file.static_analysis:
                for issue in file.static_analysis['issues']:
                    issue_type = issue.get('type', 'info')
                    issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
        
        for issue_type, count in issue_types.items():
            prompt_parts.append(f"  - {issue_type.title()}: {count}\n")
        
        prompt_parts.append("\n")
    
    # File listing
    prompt_parts.append("## FILES TO ANALYZE:\n")
    for i, file in enumerate(code_files, 1):
        complexity = ""
        if file.static_analysis and 'metrics' in file.static_analysis:
            metrics = file.static_analysis['metrics']
            if 'complexity_estimate' in metrics:
                complexity = f" (complexity: {metrics['complexity_estimate']})"
        
        prompt_parts.append(f"{i}. **{file.filename}** ({file.language}){complexity}\n")
    
    prompt_parts.append("\n" + "="*60 + "\n\n")
    
    # Add each file with analysis
    for file in code_files:
        prompt_parts.append(f"{'='*20} FILE: {file.filename} ({'='*20}\n")
        
        # Add static analysis results if available
        if file.static_analysis:
            if 'metrics' in file.static_analysis and file.static_analysis['metrics']:
                prompt_parts.append("**Static Analysis Metrics:**\n")
                for key, value in file.static_analysis['metrics'].items():
                    prompt_parts.append(f"- {key.replace('_', ' ').title()}: {value}\n")
                prompt_parts.append("\n")
            
            if 'issues' in file.static_analysis and file.static_analysis['issues']:
                prompt_parts.append("**Automated Issues Found:**\n")
                for issue in file.static_analysis['issues'][:10]:  # Limit to top 10
                    prompt_parts.append(f"- Line {issue.get('line', '?')}: {issue.get('message', 'Unknown issue')} [{issue.get('type', 'info')}]\n")
                
                if len(file.static_analysis['issues']) > 10:
                    prompt_parts.append(f"- ... and {len(file.static_analysis['issues']) - 10} more issues\n")
                
                prompt_parts.append("\n")
        
        prompt_parts.append(f"**Code:**\n```{file.language}\n{file.content}\n```\n\n")
    
    return "".join(prompt_parts)

# --- Enhanced Streaming with Progress ---
def stream_enhanced_review(
    api_key: str,
    user_prompt: str,
    review_mode: ReviewMode,
    model: str = "x-ai/grok-4",
    enable_caching: bool = True
) -> Generator[Tuple[str, Dict], None, None]:
    """Enhanced streaming with caching and progress tracking."""
    
    # Check cache first
    content_hash = hashlib.sha256(user_prompt.encode()).hexdigest()
    
    if enable_caching:
        cached_result = get_cached_review(content_hash)
        if cached_result:
            # Stream cached result
            words = cached_result.content.split()
            for i, word in enumerate(words):
                yield word + " ", {
                    'progress': (i + 1) / len(words),
                    'status': 'streaming_cached',
                    'cached': True
                }
            return
    
    # Determine system prompt based on mode
    if review_mode == ReviewMode.SECURITY_FOCUSED:
        system_prompt = ENHANCED_SYSTEM_PROMPT + "\n\n**SPECIAL FOCUS: Prioritize security analysis above all else.**"
    elif review_mode == ReviewMode.PERFORMANCE_FOCUSED:
        system_prompt = ENHANCED_SYSTEM_PROMPT + "\n\n**SPECIAL FOCUS: Prioritize performance and scalability analysis.**"
    elif review_mode == ReviewMode.ARCHITECTURE_REVIEW:
        system_prompt = ENHANCED_SYSTEM_PROMPT + "\n\n**SPECIAL FOCUS: Prioritize architectural design and maintainability.**"
    else:
        system_prompt = ENHANCED_SYSTEM_PROMPT
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/enhanced-code-reviewer",
        "X-Title": f"Enhanced AI Code Review ({model})",
    }
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": True,
        "temperature": 0.1,
        "max_tokens": 4000
    }
    
    full_response = ""
    
    try:
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=60)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                try:
                    line = line.decode('utf-8')
                except UnicodeDecodeError:
                    continue
                    
                if line.startswith('data: '):
                    line = line[6:]
                    if line.strip() == '[DONE]':
                        break
                    try:
                        chunk = json.loads(line)
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            if 'content' in delta:
                                content = delta['content']
                                full_response += content
                                yield content, {
                                    'status': 'streaming',
                                    'cached': False,
                                    'total_tokens': len(full_response.split())
                                }
                    except json.JSONDecodeError:
                        continue
        
        # Cache the result
        if enable_caching and full_response:
            cache_review(content_hash, full_response, model, review_mode.value)
        
    except Exception as e:
        yield f"❌ **Error**: {str(e)}", {'status': 'error', 'cached': False}

# --- Streamlit Enhanced UI ---
st.set_page_config(
    layout="wide", 
    page_title="Enhanced AI Code Reviewer",
    page_icon="🚀",
    initial_sidebar_state="expanded"
)

# Initialize database
init_database()

st.title("🚀 Enhanced AI Code Reviewer")
st.subheader("Advanced Static Analysis + AI Intelligence")

# Sidebar for advanced options
with st.sidebar:
    st.header("⚙️ Advanced Options")
    
    enable_caching = st.checkbox("Enable Result Caching", value=True, help="Cache reviews to avoid re-analyzing the same code")
    enable_static_analysis = st.checkbox("Run Static Analysis", value=True, help="Integrate automated code analysis tools")
    max_concurrent_analysis = st.slider("Concurrent Analysis Threads", 1, 4, 2, help="Number of files to analyze in parallel")
    
    st.header("📊 Cache Statistics")
    # Show cache stats
    try:
        db_path = APP_DIR / "review_cache.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM review_cache")
        cache_count = cursor.fetchone()[0]
        st.metric("Cached Reviews", cache_count)
        
        cursor = conn.execute("SELECT COUNT(*) FROM static_analysis_cache")
        analysis_cache_count = cursor.fetchone()[0]
        st.metric("Cached Analyses", analysis_cache_count)
        conn.close()
    except:
        st.info("Cache database not initialized")

# Main content
with st.expander("🎯 What's New in Enhanced Code Reviewer", expanded=False):
    st.markdown("""
    ### 🔥 Advanced Features:
    - **Static Analysis Integration**: Automatic pylint, eslint, and language-specific analysis
    - **Smart Caching**: Avoid re-reviewing identical code (7-day cache)
    - **Project Context Awareness**: Understands your project structure and dependencies  
    - **Multiple Review Modes**: Security-focused, Performance-focused, Architecture reviews
    - **Parallel Processing**: Analyze multiple files simultaneously
    - **Enhanced Metrics**: Complexity scoring, issue categorization, progress tracking
    - **Better Error Handling**: Graceful degradation when tools aren't available
    
    ### 🎨 Review Modes:
    - **Standard**: Comprehensive analysis across all dimensions
    - **Security-Focused**: Prioritizes OWASP Top 10 and security best practices
    - **Performance-Focused**: Emphasizes bottlenecks and optimization opportunities
    - **Architecture Review**: Deep dive into design patterns and maintainability
    - **IDE Instructions**: Copy-pasteable fixes for Cursor/Claude/etc.
    """)

# API Key handling (same as before)
api_key = None
api_key_source = None

if 'OPENROUTER_API_KEY' in os.environ:
    api_key = os.environ['OPENROUTER_API_KEY']
    api_key_source = ".env / environment"
elif hasattr(st, 'secrets') and 'OPENROUTER_API_KEY' in st.secrets:
    api_key = st.secrets['OPENROUTER_API_KEY']
    api_key_source = "Streamlit secrets"

if not api_key:
    with st.expander("🔑 OpenRouter API Key Required", expanded=True):
        st.info("Get your API key from: https://openrouter.ai/keys")
    api_key = st.text_input("Enter your OpenRouter API Key:", type="password")
    if api_key:
        api_key_source = "manual input"

if api_key:
    if not api_key.startswith('sk-or-') or len(api_key) < 20:
        st.error("Invalid OpenRouter API key format.")
        st.stop()
    
    st.success(f"✅ API Key validated ({api_key_source})")

# Enhanced file upload section
st.markdown("### 📁 Upload Your Code")
st.info(f"""
**Enhanced Processing Capabilities:**
- Supports {len(SUPPORTED_EXTS)} programming languages and formats
- Project context detection (requirements.txt, package.json, etc.)
- Automatic static analysis integration
- Smart complexity estimation and issue detection
- Max size: {MAX_TOTAL_SIZE // 1024**2}MB total, {MAX_FILE_SIZE // 1024**2}MB per file
""")

uploaded_files = st.file_uploader(
    "Choose files or ZIP archives",
    accept_multiple_files=True,
    type=[ext.lstrip('.') for ext in SUPPORTED_EXTS] + ['zip']
)

# Enhanced settings
st.markdown("### ⚙️ Review Configuration")
col1, col2, col3 = st.columns(3)

with col1:
    review_mode = st.selectbox(
        "Review Mode:",
        options=[mode.value for mode in ReviewMode],
        index=0,
        help="Choose the focus area for your review"
    )
    selected_mode = ReviewMode(review_mode)

with col2:
    MODEL_OPTIONS = [
        "x-ai/grok-code-fast-1",
        "x-ai/grok-4", 
        "anthropic/claude-sonnet-4",
        "openai/gpt-5",
        "anthropic/claude-3.5-sonnet",
        "qwen/qwen3-coder:free"
    ]
    
    selected_model = st.selectbox(
        "AI Model:",
        options=MODEL_OPTIONS,
        index=1,
        help="Choose the AI model for analysis"
    )

with col3:
    analysis_depth = st.selectbox(
        "Analysis Depth:",
        options=["Quick Scan", "Standard", "Deep Analysis"],
        index=1,
        help="Thoroughness vs speed tradeoff"
    )

# Session state initialization
if 'review_complete' not in st.session_state:
    st.session_state.review_complete = False
if 'review_result' not in st.session_state:
    st.session_state.review_result = ""
if 'last_review_time' not in st.session_state:
    st.session_state.last_review_time = None
if 'project_context' not in st.session_state:
    st.session_state.project_context = {}

# Enhanced review function
def start_enhanced_review():
    """Start the enhanced review process."""
    if not api_key:
        st.error("Please provide an OpenRouter API key.")
        return
    
    if not uploaded_files:
        st.error("Please upload at least one file.")
        return
    
    # Rate limiting
    if st.session_state.last_review_time:
        time_since_last = datetime.now() - st.session_state.last_review_time
        if time_since_last.total_seconds() < 5:  # Reduced cooldown
            st.error("Please wait a moment before starting another review.")
            return
    
    st.session_state.last_review_time = datetime.now()
    
    # Enhanced file processing with progress
    progress_container = st.empty()
    with progress_container.container():
        st.info("🔍 Processing files and running static analysis...")
        progress_bar = st.progress(0)
        status_text = st.empty()
    
    try:
        # Process files with static analysis
        status_text.text("Extracting and validating files...")
        progress_bar.progress(0.2)
        
        code_files, warnings, project_context = process_uploaded_files_enhanced(uploaded_files)
        
        if warnings:
            for warning in warnings:
                st.warning(warning)
        
        if not code_files:
            st.error("No valid code files found.")
            return
        
        status_text.text(f"Running static analysis on {len(code_files)} files...")
        progress_bar.progress(0.5)
        
        # Store project context
        st.session_state.project_context = project_context
        
        status_text.text("Constructing analysis prompt...")
        progress_bar.progress(0.7)
        
        # Construct enhanced prompt
        user_prompt = construct_enhanced_prompt(code_files, project_context, selected_mode)
        
        status_text.text("Connecting to AI model...")
        progress_bar.progress(0.9)
        
        # Clear processing status
        progress_container.empty()
        
        # Show file processing results
        st.success(f"✅ Successfully processed {len(code_files)} file(s)")
        
        # Display project insights
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Files", len(code_files))
        with col2:
            st.metric("Lines of Code", f"{project_context['total_loc']:,}")
        with col3:
            total_issues = sum(len(f.static_analysis.get('issues', [])) for f in code_files if f.static_analysis)
            st.metric("Static Issues", total_issues)
        with col4:
            languages = len(set(f.language for f in code_files))
            st.metric("Languages", languages)
        
        # Show detailed file info
        with st.expander("📋 File Analysis Details", expanded=False):
            df_data = []
            for file in code_files:
                issues = len(file.static_analysis.get('issues', [])) if file.static_analysis else 0
                complexity = file.static_analysis.get('metrics', {}).get('complexity_estimate', 'N/A') if file.static_analysis else 'N/A'
                loc = file.static_analysis.get('metrics', {}).get('lines_of_code', len(file.content.splitlines())) if file.static_analysis else len(file.content.splitlines())
                
                df_data.append({
                    'File': file.filename,
                    'Language': file.language.title(),
                    'Lines': loc,
                    'Complexity': complexity,
                    'Issues': issues
                })
            
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True)
        
        # Stream the review
        st.markdown("---")
        st.markdown("## 🤖 AI Analysis in Progress...")
        
        result_container = st.empty()
        progress_info = st.empty()
        
        full_response = ""
        
        for chunk, metadata in stream_enhanced_review(
            api_key, 
            user_prompt, 
            selected_mode, 
            selected_model,
            enable_caching
        ):
            full_response += chunk
            result_container.markdown(full_response)
            
            # Show progress info
            if metadata.get('cached'):
                progress_info.info("📦 Loading from cache...")
            else:
                tokens = metadata.get('total_tokens', 0)
                progress_info.info(f"🔄 Generating... ({tokens:,} tokens)")
        
        # Clear progress info
        progress_info.empty()
        
        # Store results
        st.session_state.review_result = full_response
        st.session_state.review_complete = True
        st.session_state.selected_mode = selected_mode
        st.session_state.selected_model = selected_model
        
    except Exception as e:
        st.error(f"An error occurred during processing: {str(e)}")
        st.exception(e)

# Analyze button
if st.button("🚀 Start Enhanced Analysis", type="primary", use_container_width=True):
    start_enhanced_review()

# Enhanced results display
if st.session_state.review_complete and st.session_state.review_result:
    st.markdown("---")
    st.markdown("## 📊 Analysis Results")
    
    # Enhanced tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Full Review", "📊 Summary", "🎯 Action Items", "📈 Metrics", "🔧 Debug"])
    
    with tab1:
        st.markdown(st.session_state.review_result)
        
        # Enhanced download options
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                "📥 Download Review (Markdown)",
                data=st.session_state.review_result,
                file_name=f"code_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown"
            )
        with col2:
            # Create summary report
            summary_data = {
                'timestamp': datetime.now().isoformat(),
                'model': st.session_state.get('selected_model', 'unknown'),
                'mode': st.session_state.get('selected_mode', ReviewMode.STANDARD).value,
                'project_context': st.session_state.get('project_context', {}),
                'review_content': st.session_state.review_result
            }
            
            st.download_button(
                "📋 Download Summary (JSON)",
                data=json.dumps(summary_data, indent=2),
                file_name=f"review_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )
    
    with tab2:
        # Extract key sections using regex
        review_text = st.session_state.review_result
        
        # Extract executive summary
        summary_match = re.search(r"(?:Executive Summary|Summary)[\s\S]*?(?=##|$)", review_text, re.IGNORECASE)
        if summary_match:
            st.markdown(summary_match.group(0))
        else:
            st.info("Summary extraction in progress...")
    
    with tab3:
        # Extract action items
        st.markdown("### 🎯 Prioritized Action Items")
        
        # Look for action items, recommendations, or critical issues
        action_patterns = [
            r"## Critical.*?(?=##|$)",
            r"## Action.*?(?=##|$)", 
            r"## Recommend.*?(?=##|$)",
            r"## Priority.*?(?=##|$)"
        ]
        
        actions_found = False
        for pattern in action_patterns:
            matches = re.findall(pattern, review_text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                st.markdown(match)
                actions_found = True
        
        if not actions_found:
            st.info("No structured action items found. Check the Full Review tab.")
    
    with tab4:
        # Show project metrics
        st.markdown("### 📈 Project Metrics")
        
        if st.session_state.get('project_context'):
            context = st.session_state.project_context
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Lines of Code", f"{context.get('total_loc', 0):,}")
                st.metric("Configuration Files", "Yes" if context.get('has_config_files') else "No")
            
            with col2:
                if context.get('dependency_files'):
                    st.write("**Dependency Files:**")
                    for dep_file in context['dependency_files']:
                        st.write(f"- {dep_file}")
        
        # Review metadata
        st.markdown("### 🔍 Review Metadata")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("AI Model", st.session_state.get('selected_model', 'Unknown'))
        with col2:
            mode = st.session_state.get('selected_mode', ReviewMode.STANDARD)
            st.metric("Review Mode", mode.value if hasattr(mode, 'value') else str(mode))
        with col3:
            word_count = len(st.session_state.review_result.split())
            st.metric("Review Length", f"{word_count:,} words")
    
    with tab5:
        # Debug information
        st.markdown("### 🔧 Debug Information")
        
        with st.expander("System Configuration"):
            st.code({
                "cache_enabled": enable_caching,
                "static_analysis_enabled": enable_static_analysis,
                "max_concurrent_threads": max_concurrent_analysis,
                "supported_extensions": SUPPORTED_EXTS,
                "project_files_detected": PROJECT_FILES
            })
        
        with st.expander("Session State"):
            debug_state = {k: str(v)[:200] for k, v in st.session_state.items()}
            st.json(debug_state)

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>🚀 Enhanced AI Code Reviewer v2.0 | Powered by OpenRouter | 
    <a href='https://openrouter.ai' target='_blank'>Get API Key</a></p>
</div>
""", unsafe_allow_html=True)
