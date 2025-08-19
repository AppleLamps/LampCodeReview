import streamlit as st
import requests
from dotenv import load_dotenv
import os
import json
import time
import zipfile
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Generator, Tuple, Any

# --- Constants and Configuration ---
# Robustly load .env from the app directory (and let python-dotenv auto-discover as fallback)
APP_DIR = Path(__file__).resolve().parent
_ = load_dotenv(APP_DIR / ".env", override=False)  # Load from app directory with fallback to parent discovery

MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB
SUPPORTED_EXTS = (
    ".py", ".js", ".java", ".ts", ".go", ".rb", ".php", ".cs", ".c", ".cpp",
    ".h", ".hpp", ".html", ".htm", ".css", ".sql", ".yaml", ".yml", ".json",
    ".xml", ".md", ".sh", ".bat", ".rs", ".ps1"
)
SYSTEM_PROMPT = r"""You are an expert code reviewer with deep knowledge across multiple programming languages and frameworks. Your role is to provide comprehensive, actionable code analysis that helps developers improve their code quality, security, and maintainability.

## Your Analysis Framework

Analyze the provided code across these key dimensions:

### 1. 🏛️ Architecture & Design
- Code structure and organization
- Design patterns and architectural decisions
- Modularity and separation of concerns
- Scalability considerations
- Maintainability factors

### 2. 🔒 Security (Priority Focus)
- Input validation and sanitization
- Authentication and authorization flaws
- Data exposure risks
- Injection vulnerabilities (SQL, XSS, etc.)
- Hardcoded secrets or credentials
- Insecure dependencies
- Error handling that might leak information

### 3. ⚙️ Performance
- Algorithmic efficiency
- Resource management (memory, CPU, I/O)
- Database query optimization
- Caching strategies
- Bottleneck identification

### 4. ✅ Correctness & Resilience
- Logic errors and edge cases
- Error handling and recovery
- Race conditions and concurrency issues
- Data validation and type safety
- Null/undefined handling

### 5. ✨ Code Quality & Readability
- Naming conventions and clarity
- Code documentation and comments
- Consistent formatting and style
- Code duplication
- Complexity and cognitive load

## Response Format

Structure your analysis as follows:

## Executive Summary
[Brief overview of the code's overall quality and main concerns]

## Critical Issues (Fix Immediately)
[Security vulnerabilities, major bugs, or critical performance issues]

## Important Improvements
[Significant issues that should be addressed soon]

## Code Quality Enhancements
[Style, readability, and maintainability improvements]

## Positive Aspects
[What the code does well - acknowledge good practices]

## Recommendations
[Prioritized action items with specific implementation guidance]

For each issue identified:
- **Severity**: Critical/High/Medium/Low
- **Category**: Security/Performance/Correctness/Quality
- **Description**: Clear explanation of the issue
- **Impact**: What could go wrong
- **Solution**: Specific code examples or implementation guidance
- **File/Line**: Reference specific locations when possible

## Guidelines
- Be thorough but practical
- Provide specific, actionable recommendations
- Include code examples for complex fixes
- Prioritize security and correctness over style
- Be constructive and educational in tone
- Focus on the most impactful improvements first"""

# System prompt for IDE implementation instructions mode
IDE_INSTRUCTIONS_PROMPT = r"""You are an expert code reviewer specialized in providing step-by-step implementation instructions for IDEs like Cursor or Trae AI.

## Core Analysis Framework

Apply this systematic reasoning to every code review:

1. **What exactly needs to be fixed?** (Be specific about the issue)
2. **What files are actually provided?** (Use ONLY these files)
3. **What's the safest implementation approach?** (Minimize risk of breaking changes)
4. **How will the user verify it works?** (Include testing steps)
5. **What could go wrong during implementation?** (Anticipate common issues)

## File Reference Rules (CRITICAL)

**ABSOLUTE REQUIREMENTS:**
- You MUST ONLY reference the actual files provided in the user prompt
- DO NOT create fictional filenames or assume files that are not explicitly shown
- Always use the exact filenames as they appear in the "FILES TO ANALYZE:" list and the "===== FILE: [filename] =====" headers
- Base line numbers on the actual code content shown
- If you see a "FILES TO ANALYZE:" section, ONLY use those filenames

## Instruction Quality Standards

**Each IDE instruction must include:**
- **Exact file path** (from provided files only)
- **Specific line numbers** when relevant
- **Complete code changes** (no placeholders or TODOs)
- **Clear context** about why the change is needed
- **Dependencies/imports** required
- **Verification steps** to confirm the change works
- **Rollback guidance** if something goes wrong

## Format Structure

Before providing instructions, first list all the files you are analyzing:

## Files Being Analyzed
[List each filename exactly as provided]

Then provide improvements in this format:

## Step-by-Step IDE Implementation Instructions

### Step 1: [Clear Action Title]
**Priority:** Critical/High/Medium/Low
**File:** [Use ONLY actual filename from the provided files]
**Issue:** [What problem this fixes]
**Copy this to your IDE:**
```

[Complete, copy-pasteable instruction with all context needed]

Include:

    - Exact file path: [filename]
    - Specific changes needed
    - Why this change is important
    - How to verify it works: [specific test/check]
    - If it fails: [rollback instruction]

<!-- end list -->

```

### Step 2: [Clear Action Title]
**Priority:** Critical/High/Medium/Low
**File:** [Use ONLY actual filename from the provided files]
**Issue:** [What problem this fixes]
**Copy this to your IDE:**
```

[Complete, copy-pasteable instruction]

```

Continue this pattern for all identified improvements.

## Examples of Effective IDE Instructions

**GOOD Example:**
```

File: user\_auth.py
Replace the hardcoded password check on line 45 with proper hashing:

Current code (line 45):
if password == "admin123":

Replace with:
import bcrypt

# Add this import at the top

# Replace line 45 with:

if bcrypt.checkpw(password.encode('utf-8'), stored\_hash):

Why: Prevents password exposure in source code
Test: Try logging in with correct credentials
If it fails: Check that bcrypt is installed (pip install bcrypt)

```

**BAD Example:**
```

Fix the auth issue in the login function
Add proper validation
Update the security

````

## Self-Check Questions

Before finalizing each instruction, verify:
- **Am I using only the actual filenames provided?**
- **Is this instruction complete enough to copy-paste and execute?**
- **Have I included verification steps?**
- **Would this instruction work if I followed it exactly?**
- **Have I prioritized the most critical issues first?**

## Error Recovery Guidance

**When Instructions Might Fail:**
- **Import errors**: Always specify required dependencies
- **Syntax errors**: Include complete, valid code blocks
- **Logic errors**: Provide testing steps to verify correctness
- **Environment issues**: Note any environment requirements

**Include in each instruction:**
- How to test if the change worked
- What to do if it doesn't work
- How to revert if needed

## Quality Control

**NEVER do these things:**
- Reference files not in the provided code
- Create example filenames like 'main.py', 'utils.py', etc. unless actually provided
- Give incomplete instructions with placeholders
- Assume the user knows context not provided in the instruction
- Skip verification steps
- Provide instructions that could break working code

**ALWAYS do these things:**
- Start with the most critical security/bug issues
- Make each instruction self-contained and actionable
- Include specific line numbers from the actual code
- Provide complete code examples, not snippets
- Test your instructions mentally before providing them

Focus on the most critical issues first (security, bugs, performance) and make each instruction self-contained and actionable. Remember: the user should be able to follow your instructions exactly and get working, improved code."""

# --- Helper Functions ---
def process_uploaded_files(
    uploaded_files: List[Any]
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Process uploaded files and return code contents and warnings."""
    code_contents = []
    warnings = []
    total_size = 0
    
    for uploaded_file in uploaded_files:
        file_size = uploaded_file.size
        total_size += file_size
        
        if total_size > MAX_TOTAL_SIZE:
            warnings.append(f"⚠️ Total upload size exceeded {MAX_TOTAL_SIZE // 1024**2}MB. Skipping remaining files.")
            break
        
        if uploaded_file.name.endswith('.zip'):
            # Handle ZIP files
            try:
                with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
                    for file_info in zip_ref.infolist():
                        if file_info.filename.startswith(('/', '\\')) or '..' in file_info.filename.split(os.sep):
                            warnings.append(f"⚠️ Skipping file with potential path traversal: {file_info.filename}")
                            continue

                        if file_info.file_size > MAX_FILE_SIZE:
                            warnings.append(f"⚠️ Skipping large file in ZIP: {file_info.filename} ({file_info.file_size} bytes)")
                            continue

                        # Sanitize file path to prevent directory traversal
                        safe_filename = os.path.basename(file_info.filename)
                        if not safe_filename or safe_filename.startswith('.'):
                            continue
                        
                        if not file_info.is_dir() and any(safe_filename.endswith(ext) for ext in SUPPORTED_EXTS):
                            with zip_ref.open(file_info) as file:
                                content = file.read()
                                if len(content) > MAX_FILE_SIZE:
                                    content = content[:MAX_FILE_SIZE]
                                    warnings.append(f"⚠️ File '{safe_filename}' truncated to {MAX_FILE_SIZE // 1024**2}MB")
                                
                                try:
                                    decoded_content = content.decode('utf-8')
                                    
                                    # Validate content is not empty or just whitespace
                                    if not decoded_content.strip():
                                        warnings.append(f"⚠️ File '{safe_filename}' is empty or contains only whitespace. Skipping.")
                                        continue
                                    
                                    # Validate minimum content length (at least 10 characters)
                                    if len(decoded_content.strip()) < 10:
                                        warnings.append(f"⚠️ File '{safe_filename}' is too short for meaningful analysis. Skipping.")
                                        continue
                                    
                                    code_contents.append({
                                        'filename': safe_filename,
                                        'content': decoded_content
                                    })
                                except UnicodeDecodeError:
                                    warnings.append(f"⚠️ Could not decode '{safe_filename}' as UTF-8. Skipping.")
            except zipfile.BadZipFile:
                warnings.append(f"⚠️ '{uploaded_file.name}' is not a valid ZIP file. Skipping.")
        else:
            # Handle individual files
            if any(uploaded_file.name.endswith(ext) for ext in SUPPORTED_EXTS):
                content = uploaded_file.read()
                if len(content) > MAX_FILE_SIZE:
                    content = content[:MAX_FILE_SIZE]
                    warnings.append(f"⚠️ File '{uploaded_file.name}' truncated to {MAX_FILE_SIZE // 1024**2}MB")
                
                try:
                    decoded_content = content.decode('utf-8')
                    
                    # Validate content is not empty or just whitespace
                    if not decoded_content.strip():
                        warnings.append(f"⚠️ File '{uploaded_file.name}' is empty or contains only whitespace. Skipping.")
                        continue
                    
                    # Validate minimum content length (at least 10 characters)
                    if len(decoded_content.strip()) < 10:
                        warnings.append(f"⚠️ File '{uploaded_file.name}' is too short for meaningful analysis. Skipping.")
                        continue
                    
                    code_contents.append({
                        'filename': uploaded_file.name,
                        'content': decoded_content
                    })
                except UnicodeDecodeError:
                    warnings.append(f"⚠️ Could not decode '{uploaded_file.name}' as UTF-8. Skipping.")
            else:
                warnings.append(f"⚠️ '{uploaded_file.name}' has an unsupported file extension. Skipping.")
    
    return code_contents, warnings

def construct_user_prompt(code_contents: List[Dict[str, str]]) -> str:
    # Start with file list for clarity
    prompt_parts = ["Please review the following code files:\n\n"]
    prompt_parts.append("FILES TO ANALYZE:\n")
    for i, item in enumerate(code_contents, 1):
        prompt_parts.append(f"{i}. {item['filename']}\n")
    prompt_parts.append("\n" + "="*50 + "\n\n")
    
    # Add each file with prominent headers
    for item in code_contents:
        prompt_parts.append(f"{'='*20} FILE: {item['filename']} {'='*20}\n\n```\n{item['content']}\n```\n\n")
    return "".join(prompt_parts)

def stream_grok_review(
    api_key: str,
    user_prompt: str,
    use_ide_instructions: bool = False,
    model: str = "x-ai/grok-4",
) -> Generator[str, None, None]:
    """Stream the Grok review response."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title": f"AI Code Review ({model})",
    }
    
    system_prompt = IDE_INSTRUCTIONS_PROMPT if use_ide_instructions else SYSTEM_PROMPT
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": True,
        "temperature": 0.1
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=30)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                try:
                    line = line.decode('utf-8')
                except UnicodeDecodeError:
                    logging.warning("Failed to decode response line as UTF-8")
                    continue
                    
                if line.startswith('data: '):
                    line = line[6:]  # Remove 'data: ' prefix
                    if line.strip() == '[DONE]':
                        break
                    try:
                        chunk = json.loads(line)
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            if 'content' in delta:
                                yield delta['content']
                    except json.JSONDecodeError as e:
                        logging.warning(f"Failed to parse JSON chunk: {e}")
                        continue
                    except (KeyError, IndexError) as e:
                        logging.warning(f"Unexpected response structure: {e}")
                        continue
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            yield "❌ **Authentication Error**: Invalid API key. Please verify your OpenRouter credentials at https://openrouter.ai/keys"
        elif e.response.status_code == 429:
            yield "⏱️ **Rate Limit Exceeded**: Too many requests. Please wait a few minutes or check your OpenRouter quota at https://openrouter.ai/activity"
        elif e.response.status_code == 402:
            yield "💳 **Payment Required**: Insufficient credits. Please add credits to your OpenRouter account."
        elif e.response.status_code == 503:
            yield "🔧 **Service Unavailable**: The AI model is temporarily unavailable. Please try again in a few minutes."
        else:
            yield f"❌ **HTTP Error {e.response.status_code}**: {str(e)}\n\nPlease check the OpenRouter status page or try a different model."
    except requests.exceptions.Timeout:
        yield "⏱️ **Timeout Error**: The request took too long. Please try again with smaller files or check your internet connection."
    except requests.exceptions.ConnectionError:
        yield "🌐 **Connection Error**: Could not connect to OpenRouter. Please check your internet connection."
    except requests.exceptions.RequestException as e:
        yield f"❌ **Network Error**: {str(e)}\n\nPlease check your internet connection and try again."

# --- Streamlit App UI ---
st.set_page_config(layout="wide", page_title="AI Code Review")
st.title("🤖 AI Code Review")
st.subheader("Powered by OpenRouter")

with st.expander("About This Tool & How It Works", expanded=True):
    st.write("""
## Advanced Code Analysis with a Clear, Actionable Framework
Upload your code for a comprehensive review by an expert AI model via **OpenRouter**, designed for meticulous, expert-level analysis.

### How It Works:
The AI uses a structured thinking process to analyze your code across multiple dimensions:
1.  🏛️ **Architecture & Design**: Evaluates structure, scalability, and maintainability.
2.  🔒 **Security**: A primary focus, checking for common vulnerabilities like injection, hardcoded secrets, etc.
3.  ⚙️ **Performance**: Identifies bottlenecks and inefficient resource management.
4.  ✅ **Correctness & Resilience**: Looks for logic errors, missed edge cases, and poor error handling.
5.  ✨ **Readability**: Assesses code clarity, conventions, and documentation.

The AI then provides a prioritized list of findings, complete with actionable recommendations and code examples.
    """)

# API Key Input
api_key = None
api_key_source = None

# Try to get API key from environment or secrets
if 'OPENROUTER_API_KEY' in os.environ:
    api_key = os.environ['OPENROUTER_API_KEY']
    api_key_source = ".env / environment"
elif hasattr(st, 'secrets') and 'OPENROUTER_API_KEY' in st.secrets:
    api_key = st.secrets['OPENROUTER_API_KEY']
    api_key_source = "Streamlit secrets"

if not api_key:
    with st.expander("🔑 OpenRouter API Key Required", expanded=True):
        st.info("""
        To use this tool, you need an OpenRouter API key. You can:
        
        1. **Add to .env file**: `OPENROUTER_API_KEY=your_key_here`
        2. **Add to Streamlit secrets**: Create `.streamlit/secrets.toml` with your key
        3. **Enter manually**: Use the input field above
        
        Get your API key from: https://openrouter.ai/keys
        """)
    api_key = st.text_input("Enter your OpenRouter API Key:", type="password")
    if api_key:
        api_key_source = "manual input"

if api_key:
    # Validate API key format and length
    if not api_key.startswith('sk-or-') or len(api_key) < 20:
        st.error("Invalid OpenRouter API key format. It should start with 'sk-or-' and be at least 20 characters long.")
        st.stop()
    
    # Test API key validity with a minimal request
    try:
        test_response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5
        )
        if test_response.status_code != 200:
            st.error("API key validation failed. Please check your OpenRouter credentials.")
            st.stop()
    except requests.RequestException:
        st.warning("Could not validate API key (network issue). Proceeding with caution.")
    
    st.success(f"✅ API Key loaded and validated successfully ({api_key_source}).")

# File Upload Section
st.markdown("### 📁 Upload Your Code Files")
st.info(f"""
- For the best analysis, upload related files or a whole module in a `.zip` archive.
- Supported extensions: `{', '.join(SUPPORTED_EXTS)}`
- Max total size: {MAX_TOTAL_SIZE // 1024**2}MB. Larger files will be truncated.
""")

uploaded_files = st.file_uploader(
    "Choose files to analyze",
    accept_multiple_files=True,
    # Streamlit expects extensions without leading dots
    type=[ext.lstrip('.') for ext in SUPPORTED_EXTS] + ['zip']
)

MODEL_OPTIONS = [
    "anthropic/claude-sonnet-4",
    "x-ai/grok-4",
    "openai/gpt-5",
    "moonshotai/kimi-k2:free",
    "qwen/qwen3-coder:free",
    "anthropic/claude-opus-4.1",
]

# Review Mode + Model Selection
st.markdown("### ⚙️ Review Settings")
col1, col2 = st.columns(2)

with col1:
    review_mode = st.radio(
        "Select review mode:",
        ["Standard Review", "IDE Implementation Instructions"],
        help="Standard: Comprehensive analysis. IDE: Step-by-step instructions for Cursor/Trae AI."
    )

with col2:
    selected_model = st.selectbox(
        "Model:",
        options=MODEL_OPTIONS,
        index=MODEL_OPTIONS.index("x-ai/grok-4") if "x-ai/grok-4" in MODEL_OPTIONS else 0,
        help="Choose which model to run your review on (via OpenRouter).",
    )
    st.session_state["selected_model"] = selected_model
    if review_mode == "IDE Implementation Instructions":
        st.info("💡 This mode generates copy-pasteable instructions for IDE AI assistants like Cursor or Trae AI.")

# Initialize all session state variables
def initialize_session_state():
    """Initialize all session state variables with default values."""
    defaults = {
        'review_complete': False,
        'review_result': "",
        'user_prompt': "",
        'selected_review_mode': "Standard Review",
        'selected_model': "x-ai/grok-4",
        'last_review_time': None
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# Call initialization
initialize_session_state()

# Rate limiting
RATE_LIMIT_SECONDS = 10  # Minimum seconds between reviews

def check_rate_limit():
    """Check if enough time has passed since last review."""
    if 'last_review_time' not in st.session_state or st.session_state.last_review_time is None:
        return True
    
    time_since_last = datetime.now() - st.session_state.last_review_time
    return time_since_last.total_seconds() >= RATE_LIMIT_SECONDS


def start_review():
    """Process files and start the review."""
    # Check rate limiting
    if not check_rate_limit():
        if st.session_state.last_review_time is not None:
            remaining_time = RATE_LIMIT_SECONDS - (datetime.now() - st.session_state.last_review_time).total_seconds()
            st.error(f"Please wait {remaining_time:.0f} more seconds before starting another review.")
        else:
            st.error("Please wait before starting another review.")
        return
    
    # Set the review time
    st.session_state.last_review_time = datetime.now()
    
    if not api_key:
        st.error("Please provide an OpenRouter API key.")
        return
    
    if not uploaded_files:
        st.error("Please upload at least one file.")
        return
    
    # Process uploaded files
    with st.spinner("Processing uploaded files..."):
        code_contents, warnings = process_uploaded_files(uploaded_files)
    
    if warnings:
        for warning in warnings:
            st.warning(warning)
    
    if not code_contents:
        st.error("No valid code files found. Please check file extensions and content.")
        return
    
    # Display debug information about uploaded files
    st.success(f"✅ Successfully processed {len(code_contents)} file(s)")
    with st.expander("📋 Files being sent to AI", expanded=False):
        for i, item in enumerate(code_contents, 1):
            st.write(f"{i}. **{item['filename']}** ({len(item['content']):,} characters)")
    
    # Construct user prompt
    user_prompt = construct_user_prompt(code_contents)
    st.session_state.user_prompt = user_prompt
    # --- FIX: Save the selected review mode to the session state ---
    st.session_state.selected_review_mode = review_mode
    st.session_state.selected_model = selected_model
    
    # Determine if using IDE instructions mode
    use_ide_instructions = review_mode == "IDE Implementation Instructions"
    
    # Start streaming review
    with st.spinner("🤖 The model is analyzing your code..."):
        progress_bar = st.progress(0)
        result_container = st.empty()
        
        full_response = ""
        chunk_count = 0
        
        for chunk in stream_grok_review(
            api_key,
            user_prompt,
            use_ide_instructions,
            model=st.session_state.selected_model,
        ):
            chunk_count += 1
            full_response += chunk
            
            # Update progress (simulate progress based on chunk count)
            progress = min(chunk_count / 100, 0.95)  # Cap at 95% until complete
            progress_bar.progress(progress)
            
            # Update the display with current response
            result_container.markdown(full_response)
        
        # Complete the progress bar
        progress_bar.progress(1.0)
        time.sleep(0.5)
        progress_bar.empty()
    
    # Store the result
    st.session_state.review_result = full_response
    st.session_state.review_complete = True

# Analyze Button
if st.button("🚀 Analyze Code", type="primary", use_container_width=True):
    start_review()

# Display Results
if st.session_state.review_complete and st.session_state.review_result:
    st.markdown("---")
    st.markdown("## 📊 Analysis Results")
    
    # Create tabs for different views
    tab1, tab2, tab3 = st.tabs(["📋 Full Review", "📝 Summary", "🔧 Debug Info"])
    
    with tab1:
        st.markdown(st.session_state.review_result)
        
        # Download button
        st.download_button(
            label="📥 Download Full Review",
            data=st.session_state.review_result,
            file_name="code_review.md",
            mime="text/markdown"
        )
    
    with tab2:
        # Try to extract summary from the review
        review_text = st.session_state.review_result
        
        # Look for summary section
        summary_patterns = [
            r"## Executive Summary[\s\S]*?(?=##|$)",
            r"## Summary[\s\S]*?(?=##|$)",
            r"### Summary[\s\S]*?(?=###|##|$)"
        ]
        
        summary_found = False
        for pattern in summary_patterns:
            summary_match = re.search(pattern, review_text, re.IGNORECASE)
            if summary_match:
                st.markdown(summary_match.group(0))
                summary_found = True
                break
        
        if not summary_found:
            # If no summary section found, show first few paragraphs
            paragraphs = review_text.split('\n\n')[:3]
            summary = '\n\n'.join(paragraphs)
            if summary:
                st.markdown("### Key Findings")
                st.markdown(summary)
            else:
                st.info("Could not automatically extract a summary. Please see the 'Full Review' tab.")
    
    with tab3:
        with st.expander("System Prompt (The AI's Instructions)"):
            # --- FIX: Read the review mode from session state ---
            mode_used = st.session_state.get("selected_review_mode")
            current_prompt = IDE_INSTRUCTIONS_PROMPT if mode_used == "IDE Implementation Instructions" else SYSTEM_PROMPT
            st.markdown(f"```markdown\n{current_prompt}\n```")
        with st.expander("User Prompt (Your Code)"):
            st.code(st.session_state.user_prompt, language="markdown")
        with st.expander("Run Configuration"):
            st.write({
                "model": st.session_state.get("selected_model", "x-ai/grok-4"),
                "review_mode": st.session_state.get("selected_review_mode", "Standard Review"),
                "api_key_source": api_key_source or "unknown",
            })
