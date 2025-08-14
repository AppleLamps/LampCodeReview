import streamlit as st
import requests
from dotenv import load_dotenv
import os
import json
import time
import zipfile
import io
import re
from typing import List, Dict, Generator, Tuple

# --- Constants and Configuration ---
load_dotenv()

MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB
SUPPORTED_EXTS = (
    ".py", ".js", ".java", ".ts", ".go", ".rb", ".php", ".cs", ".c", ".cpp",
    ".h", ".hpp", ".html", ".htm", ".css", ".sql", ".yaml", ".yml", ".json",
    ".xml", ".md", ".sh", ".bat", ".ps1"
)

SYSTEM_PROMPT = """[...your full prompt here...]"""  # Paste your original SYSTEM_PROMPT here!

# System prompt for IDE implementation instructions mode
IDE_INSTRUCTIONS_PROMPT = """You are Grok-4, an expert code reviewer specialized in providing step-by-step implementation instructions for IDEs like Cursor or Trae AI.

IMPORTANT: You MUST ONLY reference the actual files provided in the user prompt. DO NOT create fictional filenames or assume files that are not explicitly shown. Always use the exact filenames as they appear in the "FILES TO ANALYZE:" list and the "===== FILE: [filename] =====" headers.

Your task is to analyze the provided code and generate actionable, step-by-step instructions that users can copy and paste directly into their IDE's AI assistant (like Cursor or Trae) to implement the suggested improvements.

Before providing instructions, first list all the files you are analyzing:

## Files Being Analyzed
[List each filename exactly as provided]

For each improvement you identify, provide:

1. **Clear Step Title**: A concise description of what needs to be implemented
2. **IDE Instruction**: A complete, copy-pasteable instruction that includes:
   - ONLY the actual file paths from the provided files
   - Specific line numbers when relevant (based on the actual code shown)
   - Exact code changes needed
   - Context about why the change is needed
   - Any dependencies or imports required

Format your response as:

## Step-by-Step IDE Implementation Instructions

### Step 1: [Title]
**File:** [Use ONLY actual filename from the provided files]
**Copy this to your IDE:**
```
[Complete instruction that can be pasted directly to Cursor/Trae]
```

### Step 2: [Title]
**File:** [Use ONLY actual filename from the provided files]
**Copy this to your IDE:**
```
[Complete instruction that can be pasted directly to Cursor/Trae]
```

Continue this pattern for all identified improvements.

REMEMBER: 
- NEVER reference files that are not in the provided code
- NEVER create example filenames like 'main.py', 'utils.py', etc. unless they are actually provided
- Always use the exact filenames from the "FILES TO ANALYZE:" list and "===== FILE: [filename] =====" headers
- Base line numbers on the actual code content shown
- If you see a "FILES TO ANALYZE:" section, ONLY use those filenames

Focus on the most critical issues first (security, bugs, performance) and make each instruction self-contained and actionable."""

# --- Helper Functions ---
def process_uploaded_files(
    uploaded_files: List[st.runtime.uploaded_file_manager.UploadedFile]
) -> Tuple[List[Dict[str, str]], List[str]]:
    code_contents = []
    warnings = []
    total_size = 0
    progress_bar_placeholder = st.empty()
    status_text = st.empty()

    if not uploaded_files:
        return [], []

    progress_bar = progress_bar_placeholder.progress(0)

    def is_supported(filename: str) -> bool:
        return filename.lower().endswith(SUPPORTED_EXTS)

    def truncate(content: str, filename: str) -> str:
        content_bytes = content.encode('utf-8', errors='ignore')
        if len(content_bytes) > MAX_FILE_SIZE:
            warnings.append(f"📄 File '{filename}' was truncated as it exceeds the {MAX_FILE_SIZE // 1024**2}MB limit.")
            return content_bytes[:MAX_FILE_SIZE].decode('utf-8', errors='ignore') + "\n\n... [Content truncated] ..."
        return content

    for i, file in enumerate(uploaded_files):
        progress_bar.progress((i + 1) / len(uploaded_files))
        status_text.text(f"Processing {file.name}...")
        if total_size >= MAX_TOTAL_SIZE:
            warnings.append("🚨 Total content size limit reached. Some files were skipped.")
            break
        try:
            if file.name.lower().endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(file.read()), 'r') as z:
                    for info in z.infolist():
                        if total_size >= MAX_TOTAL_SIZE:
                            warnings.append("🚨 Total content size limit reached. Some files from the zip were skipped.")
                            break
                        if not info.is_dir() and is_supported(info.filename):
                            with z.open(info.filename) as unzipped_file:
                                file_content_bytes = unzipped_file.read()
                                if len(file_content_bytes) > MAX_FILE_SIZE:
                                    warnings.append(f"📄 File '{info.filename}' from zip was truncated as it exceeds the {MAX_FILE_SIZE // 1024**2}MB limit.")
                                    file_content = file_content_bytes[:MAX_FILE_SIZE].decode("utf-8", errors="replace") + "\n\n... [Content truncated] ..."
                                else:
                                    file_content = file_content_bytes.decode("utf-8", errors="replace")
                                code_contents.append({"filename": info.filename, "content": file_content})
                                total_size += len(file_content.encode('utf-8', errors='ignore'))
            elif is_supported(file.name):
                file_content = file.getvalue().decode("utf-8", errors="replace")
                truncated_content = truncate(file_content, file.name)
                code_contents.append({"filename": file.name, "content": truncated_content})
                total_size += len(truncated_content.encode('utf-8', errors='ignore'))
        except Exception as e:
            st.error(f"Error processing '{file.name}': {e}")
    status_text.empty()
    progress_bar_placeholder.empty()
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

def stream_grok_review(api_key: str, user_prompt: str, use_ide_instructions: bool = False) -> Generator[str, None, None]:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title": "AI CodeGuardian Review"
    }
    system_prompt = IDE_INSTRUCTIONS_PROMPT if use_ide_instructions else SYSTEM_PROMPT
    payload = {
        "model": "x-ai/grok-4",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": True
    }
    response = requests.post(url, headers=headers, json=payload, stream=True, timeout=600)
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("data: "):
                try:
                    if "[DONE]" in decoded_line:
                        break
                    data_str = decoded_line[6:]
                    if data_str:
                        data = json.loads(data_str)
                        if "choices" in data and data["choices"][0]["delta"].get("content"):
                            yield data["choices"][0]["delta"]["content"]
                except json.JSONDecodeError:
                    continue

# --- Streamlit App UI ---
st.set_page_config(layout="wide", page_title="Grok-4 Code Review")
st.title("🤖 Grok-4 Code Review")
st.subheader("Powered by Grok via OpenRouter")

with st.expander("About This Tool & How It Works", expanded=True):
    st.write("""
## Advanced Code Analysis with a Clear, Actionable Framework
Upload your code for a comprehensive review by **Grok-4**, a persona designed for meticulous, expert-level analysis.

### How It Works:
The AI uses a structured thinking process to analyze your code across multiple dimensions:
1.  🏛️ **Architecture & Design**: Evaluates structure, scalability, and maintainability.
2.  🔒 **Security**: A primary focus, checking for common vulnerabilities like injection, hardcoded secrets, etc.
3.  ⚙️ **Performance**: Identifies bottlenecks and inefficient resource management.
4.  ✅ **Correctness & Resilience**: Looks for logic errors, missed edge cases, and poor error handling.
5.  ✨ **Readability**: Assesses code clarity, conventions, and documentation.

The AI then provides a prioritized list of findings, complete with actionable recommendations and code examples.
""")

# --- API Key and File Upload ---
# Try to get API key from environment variable first, then Streamlit secrets
env_api_key = os.getenv("OPENROUTER_API_KEY")
streamlit_api_key = None

try:
    streamlit_api_key = st.secrets["OPENROUTER_API_KEY"]
except (KeyError, FileNotFoundError):
    pass

if env_api_key:
    api_key = env_api_key
    st.info("API key found in environment variable (.env file).", icon="🔑")
elif streamlit_api_key:
    api_key = streamlit_api_key
    st.info("API key found in Streamlit secrets.", icon="🔑")
else:
    api_key = st.text_input("Enter your OpenRouter API Key", type="password")
    if not api_key:
        st.warning("⚠️ No API key found. Please either:")
        st.markdown("""
        1. **Add to .env file**: `OPENROUTER_API_KEY=your_key_here`
        2. **Add to Streamlit secrets**: Create `.streamlit/secrets.toml` with your key
        3. **Enter manually**: Use the input field above
        
        Get your API key from: https://openrouter.ai/keys
        """)
if not api_key:
    st.warning("Please enter your OpenRouter API key to proceed.")
    st.stop()

st.subheader("📁 Upload Your Code")
with st.expander("Upload Tips"):
    st.info(f"""
- For the best analysis, upload related files or a whole module in a `.zip` archive.
- Supported extensions: `{', '.join(SUPPORTED_EXTS)}`
- Max total size: {MAX_TOTAL_SIZE // 1024**2}MB. Larger files will be truncated.
""")

uploaded_files = st.file_uploader(
    "Select code files or a .zip archive",
    accept_multiple_files=True,
    type=[ext.lstrip('.') for ext in SUPPORTED_EXTS] + ['zip']
)

# --- Analysis Mode Selection ---
st.subheader("⚙️ Analysis Mode")
ide_instructions_mode = st.checkbox(
    "🔧 Generate IDE Implementation Instructions",
    value=False,
    help="When checked, the AI will provide step-by-step instructions that you can copy and paste directly into Cursor or Trae AI to implement the suggested improvements."
)

if ide_instructions_mode:
    st.info("💡 **IDE Instructions Mode**: The AI will generate copy-pasteable instructions for your IDE assistant instead of a traditional code review.")
else:
    st.info("📋 **Standard Review Mode**: The AI will provide a comprehensive code analysis and recommendations.")

# --- State Initialization ---
if "full_review_text" not in st.session_state:
    st.session_state["full_review_text"] = ""
if "user_prompt" not in st.session_state:
    st.session_state["user_prompt"] = ""
if "show_tabs" not in st.session_state:
    st.session_state["show_tabs"] = False
if "review_in_progress" not in st.session_state:
    st.session_state["review_in_progress"] = False
if "ide_instructions_mode" not in st.session_state:
    st.session_state["ide_instructions_mode"] = False

# --- Analysis Execution ---
def start_review():
    st.session_state["full_review_text"] = ""
    st.session_state["user_prompt"] = ""
    st.session_state["show_tabs"] = False
    st.session_state["review_in_progress"] = True

analyze_button_text = "🔧 Generate IDE Instructions" if ide_instructions_mode else "🔍 Analyze Code"
if st.button(analyze_button_text, type="primary", use_container_width=True, key="analyze_btn"):
    if not uploaded_files:
        st.warning("⚠️ Please upload code files to analyze.")
        st.stop()
    with st.spinner("🔄 Preparing and processing files..."):
        code_contents, warnings = process_uploaded_files(uploaded_files)
        for warning in warnings:
            st.warning(warning)
        if not code_contents:
            st.error("No valid or supported code files were found. Please check your upload.")
            st.stop()
        
        # Display uploaded files for verification
        st.success(f"✅ Successfully processed {len(code_contents)} file(s):")
        with st.expander("📋 Files Being Sent to AI (Click to verify)", expanded=False):
            for i, item in enumerate(code_contents, 1):
                st.write(f"{i}. **{item['filename']}** ({len(item['content'])} characters)")
        
        st.session_state["user_prompt"] = construct_user_prompt(code_contents)
        st.session_state["ide_instructions_mode"] = ide_instructions_mode
        start_review()

# --- Streaming and Live Preview ---
if st.session_state["review_in_progress"]:
    full_review_text = ""
    review_placeholder = st.empty()
    try:
        spinner_text = "🔧 Generating IDE implementation instructions..." if st.session_state.get("ide_instructions_mode", False) else "🧠 CodeGuardian AI is analyzing your code..."
        spinner_text += " This may take several minutes."
        with st.spinner(spinner_text):
            for chunk in stream_grok_review(api_key, st.session_state["user_prompt"], st.session_state.get("ide_instructions_mode", False)):
                full_review_text += chunk
                review_placeholder.markdown(full_review_text + "▌")
        review_placeholder.markdown(full_review_text)
        st.session_state["full_review_text"] = full_review_text
        st.session_state["review_in_progress"] = False
        st.session_state["show_tabs"] = True
    except requests.exceptions.HTTPError as e:
        st.session_state["review_in_progress"] = False
        st.error(f"An HTTP error occurred: {e.response.status_code} {e.response.reason}")
        if e.response.status_code == 401:
            st.warning("Authentication failed. Please check if your API key is correct and valid.")
        elif e.response.status_code == 402:
            st.warning("Payment Required. Please check your OpenRouter account credits.")
        elif e.response.status_code == 429:
            st.warning("Rate limit exceeded. Please try again later.")
        elif e.response.status_code >= 500:
            st.warning("API error: The service may be overloaded or down. Please try again later.")
        try:
            error_details = e.response.json()
            st.code(json.dumps(error_details, indent=2), language="json")
        except json.JSONDecodeError:
            st.code(e.response.text, language="text")
    except Exception as e:
        st.session_state["review_in_progress"] = False
        st.error(f"An unexpected error occurred: {e}")

# --- Results Display in Tabs ---
if st.session_state["show_tabs"] and st.session_state["full_review_text"]:
    full_review_text = st.session_state["full_review_text"]
    user_prompt = st.session_state["user_prompt"]
    is_ide_mode = st.session_state.get("ide_instructions_mode", False)
    
    # Dynamic tab names based on mode
    tab1_name = "🔧 IDE Instructions" if is_ide_mode else "📝 Full Review"
    tab2_name = "📋 Quick Steps" if is_ide_mode else "📋 Summary"
    
    tab1, tab2, tab3 = st.tabs([tab1_name, tab2_name, "🔎 Full Prompt"])
    with tab1:
        st.markdown(full_review_text)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        
        # Dynamic download button based on mode
        download_label = "💾 Download IDE Instructions (Markdown)" if is_ide_mode else "💾 Download Full Review (Markdown)"
        file_prefix = "CodeGuardian_IDE_Instructions" if is_ide_mode else "CodeGuardian_Review"
        
        st.download_button(
            label=download_label,
            data=full_review_text,
            file_name=f"{file_prefix}_{timestamp}.md",
            mime="text/markdown"
        )
    with tab2:
        if is_ide_mode:
            # For IDE mode, try to extract the first few steps
            steps_match = re.search(
                r'### Step 1:.*?(?=### Step [4-9]:|\Z)',
                full_review_text,
                re.IGNORECASE | re.DOTALL
            )
            if steps_match:
                st.markdown("## First 3 Steps (Quick Preview)")
                st.markdown(steps_match.group(0))
                st.info("💡 See the full instructions in the 'IDE Instructions' tab above.")
            else:
                st.info("Could not automatically extract quick steps. Please see the 'IDE Instructions' tab.")
        else:
            # Original summary logic for standard review mode
            summary_match = re.search(
                r'## 1\.\s+Overall Assessment.*?(?=## 2\.|\Z)',
                full_review_text,
                re.IGNORECASE | re.DOTALL
            )
            if summary_match:
                st.markdown(summary_match.group(0))
            else:
                st.info("Could not automatically extract a summary. Please see the 'Full Review' tab.")
    with tab3:
        with st.expander("System Prompt (The AI's Instructions)"):
            current_prompt = IDE_INSTRUCTIONS_PROMPT if is_ide_mode else SYSTEM_PROMPT
            st.markdown(f"```markdown\n{current_prompt}\n```")
        with st.expander("User Prompt (Your Code)"):
            st.code(user_prompt, language="markdown")
