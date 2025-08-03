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
# Load environment variables from .env file
load_dotenv()

# File handling constants
MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_FILE_SIZE = 10 * 1024 * 1024    # 10 MB
SUPPORTED_EXTS = (
    ".py", ".js", ".java", ".ts", ".go", ".rb", ".php", ".cs", ".c", ".cpp",
    ".h", ".hpp", ".html", ".htm", ".css", ".sql", ".yaml", ".yml", ".json",
    ".xml", ".md", ".sh", ".bat", ".ps1"
)

# --- AI System Prompt ---
# This is the core of the code review logic. It instructs the AI on its persona,
# analysis framework, severity scale, and the required output format.
SYSTEM_PROMPT = """
# ROLE AND GOAL
You are CodeGuardian AI, a world-class Principal-level Software Architect and Security Specialist. Your purpose is to conduct a meticulous, in-depth code review. Your feedback must be professional, constructive, and highly actionable, empowering developers to improve their code quality significantly.

# CORE DIRECTIVES
1.  **Be Thorough:** Scrutinize every file provided. Do not skip any part of the code.
2.  **Be Precise:** Reference specific file names and line numbers for every issue you identify.
3.  **Be Actionable:** Provide clear, practical recommendations. Include corrected code snippets whenever possible to illustrate your point.
4.  **Be Constructive:** Frame your feedback positively. Acknowledge well-written code and good practices alongside areas for improvement.
5.  **Prioritize Ruthlessly:** Use the specified severity scale to help the developer focus on what matters most.

# ANALYSIS FRAMEWORK
You must analyze the code from the following perspectives. Structure your thinking process to cover each of these vectors:

1.  **Architecture & Design:**
    * **Cohesion & Coupling:** Are related components grouped logically? Is there unnecessary coupling between modules?
    * **Scalability:** Can the design handle increased load or data volume? Are there potential bottlenecks?
    * **Extensibility:** Is the code designed in a way that makes it easy to add new features without major refactoring? (e.g., use of interfaces, SOLID principles).
    * **Separation of Concerns:** Is UI, business logic, and data access logic properly separated?

2.  **Functionality & Correctness:**
    * **Logic Errors:** Are there flaws in the program's logic?
    * **Edge Cases:** Are null inputs, empty lists, zero values, and other edge cases handled correctly?
    * **Concurrency:** If multithreading is used, are there race conditions, deadlocks, or other concurrency issues?

3.  **Security (CRITICAL FOCUS):**
    * **Input Validation:** Is all external input (from users, APIs, files) rigorously validated and sanitized to prevent injection attacks (SQLi, XSS, Command Injection)?
    * **Output Encoding:** Is data properly encoded before being displayed in a UI or passed to other systems to prevent XSS?
    * **Authentication & Authorization:** Are there any weaknesses in how users or systems are authenticated or authorized?
    * **Secrets Management:** Are secrets (API keys, passwords, certs) hardcoded? They must never be.
    * **Dependency Vulnerabilities:** Are there outdated or known-vulnerable libraries being used? (Acknowledge you can't check versions but can spot suspicious libraries).
    * **Error Handling:** Do error messages leak sensitive information?

4.  **Performance:**
    * **Algorithmic Complexity:** Are there inefficient algorithms (e.g., O(n^2) loops where O(n) is possible)?
    * **Resource Management:** Are resources like file handles, database connections, and network sockets properly closed?
    * **Memory Usage:** Are there potential memory leaks or inefficient memory usage patterns?

5.  **Maintainability & Readability:**
    * **Clarity & Simplicity:** Is the code easy to understand? Is there unnecessary complexity?
    * **Naming Conventions:** Are variables, functions, and classes named clearly and consistently?
    * **Code Duplication (DRY Principle):** Is there repeated code that could be refactored into a shared function or class?
    * **Comments & Documentation:** Are there comments where needed? Is the code self-documenting where possible?

6.  **Error Handling & Resilience:**
    * **Robustness:** How does the application behave when things go wrong (e.g., network failure, database down)?
    * **Exception Handling:** Are exceptions caught specifically? Is there a consistent error handling strategy?

# SEVERITY SCALE (USE EXACTLY AS DEFINED)
- **CRITICAL:** A vulnerability that can lead to a security breach, data loss, or complete system failure. (e.g., SQL Injection, hardcoded production credentials). **Requires immediate action.**
- **HIGH:** A major functional bug, a serious performance issue affecting the user experience, or a design flaw that severely impacts maintainability. (e.g., race condition, incorrect business logic).
- **MEDIUM:** An issue that should be addressed but doesn't immediately impact operations. Improves code quality and reduces technical debt. (e.g., poor error handling, non-performant loop).
- **LOW:** A minor improvement, style suggestion, or documentation enhancement that improves readability or maintainability. (e.g., inconsistent naming, magic numbers).

# MANDATORY OUTPUT FORMAT
Your entire response MUST be a single Markdown document. Follow this structure precisely. Do not add any conversational text before the "Overall Assessment".

---

## 1. Overall Assessment

Provide a high-level executive summary of the codebase. Include a general statement on quality, a summary of the most critical findings, and a high-level recommendation for the next steps.

### Quality Scorecard
- **Security:** [Rating A-F]
- **Maintainability:** [Rating A-F]
- **Performance:** [Rating A-F]
- **Functionality:** [Rating A-F]

*(Provide a one-sentence justification for each score.)*

## 2. Architectural Overview

Describe the overall architecture as you understand it from the provided files. Explain how the components interact and comment on the architectural patterns used (or the lack thereof).

## 3. File-by-File Breakdown

For each file you were given, create a section. If no issues are found in a file, state that explicitly.

---
### **File: `[Full/Path/To/Filename.ext]`**

**Purpose:** (A brief, one-sentence description of the file's role in the project.)
**Strengths:** (1-2 bullet points on what this file does well.)
**Issues & Recommendations:**
*(List all identified issues for this file below. If none, write "No significant issues found.")*

#### [SEVERITY]: [Concise Title of the Issue]
- **Location:** Line(s) `[line_number_or_range]`
- **Description:** (Clear, detailed explanation of the problem.)
- **Impact:** (What are the consequences of this issue?)
- **Recommendation:** (Specific, actionable advice on how to fix it.)
- **Example (if applicable):**
  ```[language]
  // --- Before ---
  [code_with_issue]

  // --- After ---
  [corrected_code]
  ```

*(Repeat the "#### [SEVERITY]" block for each issue in the file.)*

-----

*(Repeat the "### File:" block for every file.)*

## 4. Cross-Cutting Concerns & General Recommendations

Summarize issues or patterns that appear across multiple files (e.g., inconsistent error handling, lack of input validation). Provide high-level recommendations for improving the entire codebase.
"""

# --- Helper Functions ---

def process_uploaded_files(
    uploaded_files: List[st.runtime.uploaded_file_manager.UploadedFile]
) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    Processes uploaded files, handling zip archives, and enforcing size limits.

    Args:
        uploaded_files: A list of files uploaded via Streamlit's file_uploader.

    Returns:
        A tuple containing:
        - A list of dictionaries, where each dict has 'filename' and 'content'.
        - A list of warning messages to display to the user.
    """
    code_contents = []
    warnings = []
    total_size = 0
    # Add a placeholder for progress bar to avoid errors if no files are uploaded
    progress_bar_placeholder = st.empty()
    status_text = st.empty()

    if not uploaded_files:
        return [], []

    progress_bar = progress_bar_placeholder.progress(0)

    def is_supported(filename: str) -> bool:
        return filename.lower().endswith(SUPPORTED_EXTS)

    def truncate(content: str, filename: str) -> str:
        # Using byte length for more accurate size check
        content_bytes = content.encode('utf-8', errors='ignore')
        if len(content_bytes) > MAX_FILE_SIZE:
            warnings.append(f"📄 File '{filename}' was truncated as it exceeds the {MAX_FILE_SIZE // 1024**2}MB limit.")
            # Truncate based on byte limit to avoid partial characters
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
    """Formats the code content into a single string for the user prompt."""
    prompt_parts = ["Please review the following code files:\n\n"]
    for item in code_contents:
        prompt_parts.append(f"--- File: {item['filename']} ---\n\n```\n{item['content']}\n```\n\n")
    return "".join(prompt_parts)

def stream_grok_review(api_key: str, user_prompt: str) -> Generator[str, None, None]:
    """
    Calls the OpenRouter API and streams the response.

    Args:
        api_key: The user's OpenRouter API key.
        user_prompt: The formatted string of code files.

    Yields:
        Chunks of the review text as they are received from the API.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo", # Replace with your app's URL
        "X-Title": "AI CodeGuardian Review"
    }
    payload = {
        # Updated model name to x-ai/grok-4 as requested
        "model": "x-ai/grok-4",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
                    # Ignore non-JSON lines or malformed data chunks
                    continue

# --- Streamlit App UI ---

st.set_page_config(layout="wide", page_title="CodeGuardian AI Review")

st.title("🛡️ CodeGuardian AI Review")
st.subheader("Powered by Grok via OpenRouter")

with st.expander("About This Tool & How It Works", expanded=True):
    st.write("""
## Advanced Code Analysis with a Clear, Actionable Framework
Upload your code for a comprehensive review by **CodeGuardian AI**, a persona designed for meticulous, expert-level analysis.

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

env_api_key = os.getenv("OPENROUTER_API_KEY")
if env_api_key:
    api_key = env_api_key
    # Updated message to be more generic
    st.info("API key found in an environment variable.", icon="🔑")
else:
    api_key = st.text_input("Enter your OpenRouter API Key", type="password")

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

# --- Analysis Execution ---

if st.button("🔍 Analyze Code", type="primary", use_container_width=True):
    if not uploaded_files:
        st.warning("⚠️ Please upload code files to analyze.")
    else:
        with st.spinner("🔄 Preparing and processing files..."):
            code_contents, warnings = process_uploaded_files(uploaded_files)
            for warning in warnings:
                st.warning(warning)

            if not code_contents:
                st.error("No valid or supported code files were found. Please check your upload.")
                st.stop()

            user_prompt = construct_user_prompt(code_contents)

            # Main container for results
            results_container = st.container()
            full_review_text = ""

            try:
                with results_container:
                    st.subheader("📊 Code Review Results")
                    review_placeholder = st.empty()
                    with st.spinner("🧠 CodeGuardian AI is analyzing your code... This may take several minutes."):
                        for chunk in stream_grok_review(api_key, user_prompt):
                            full_review_text += chunk
                            review_placeholder.markdown(full_review_text + "▌") # Add a cursor effect

                    review_placeholder.markdown(full_review_text) # Display final result

                # --- Results Display in Tabs after generation is complete ---
                if full_review_text:
                    # Place tabs outside the main generation container
                    tab1, tab2, tab3 = st.tabs(["📝 Full Review", "📋 Summary", "🔎 Full Prompt"])

                    with tab1:
                        st.markdown(full_review_text)
                        timestamp = time.strftime("%Y%m%d-%H%M%S")
                        st.download_button(
                            label="💾 Download Full Review (Markdown)",
                            data=full_review_text,
                            file_name=f"CodeGuardian_Review_{timestamp}.md",
                            mime="text/markdown"
                        )

                    with tab2:
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
                            st.markdown(f"```markdown\n{SYSTEM_PROMPT}\n```")
                        with st.expander("User Prompt (Your Code)"):
                            st.code(user_prompt, language="markdown")
                else:
                    st.error("The API returned an empty response. This could be a temporary issue with the service. Please try again.")

            except requests.exceptions.HTTPError as e:
                st.error(f"An HTTP error occurred: {e.response.status_code} {e.response.reason}")
                if e.response.status_code == 401:
                    st.warning("Authentication failed. Please check if your API key is correct and valid.")
                elif e.response.status_code == 402:
                     st.warning("Payment Required. Please check your OpenRouter account credits.")
                elif e.response.status_code == 429:
                    st.warning("Rate limit exceeded. Please try again later.")
                elif e.response.status_code >= 500:
                    st.warning("API error: The service may be overloaded or down. Please try again later.")
                # Show error details from API for easier debugging
                try:
                    error_details = e.response.json()
                    st.code(json.dumps(error_details, indent=2), language="json")
                except json.JSONDecodeError:
                    st.code(e.response.text, language="text")
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")
