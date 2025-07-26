import streamlit as st
import requests
from dotenv import load_dotenv
import os
import json
import time
import zipfile
import io
import re
from typing import List, Dict

# Load environment variables from .env file
load_dotenv()

# --- Streamlit app layout ---
st.set_page_config(layout="wide", page_title="AI-Powered Code Review")

st.title("🧠 AI-Powered Code Review with Grok-4")

# Use expanders for detailed explanations
with st.expander("About This Tool & How It Works", expanded=True):
    st.write("""
    ## Advanced Code Analysis with a Clear, Actionable Framework

    Upload your code for a comprehensive review powered by xAI's Grok-4 model. This tool focuses on providing practical, developer-friendly feedback.

    ### How It Works:
    The AI uses a structured thinking process to analyze your code, similar to how an expert developer would approach a code review:

    1. 🔍 **Initial Assessment**: Understands each file's purpose and identifies languages/frameworks.
    2. 🧩 **Deep Analysis**: Examines structure, patterns, relationships, and implementation details.
    3. ⚖️ **Issue Prioritization**: Categorizes findings by severity (**CRITICAL, HIGH, MEDIUM, LOW**) for clear actionability.
    4. 💡 **Recommendation Formulation**: Develops specific, actionable improvements with examples.
    """)

# API Key input with validation
env_api_key = os.getenv("OPENROUTER_API_KEY")
if env_api_key:
    api_key = env_api_key
    st.info("API costs covered by @lamps_apple on 𝕏.")
else:
    api_key = st.text_input("Enter your OpenRouter API Key", type="password")

if not api_key:
    st.warning("Please enter your OpenRouter API key to proceed.")
    st.stop()

# File uploader with improved guidance and multiple options
st.subheader("📁 Upload Your Code Files")

with st.expander("Upload Tips & Best Practices"):
    st.info("""
    - Upload entire modules or related files for contextual analysis.
    - Support for zip archives with nested directories.
    - Max total size: 50MB (larger files will be truncated).
    """)

uploaded_files = st.file_uploader(
    "Select code files or a .zip archive to analyze",
    accept_multiple_files=True,
    type=["py", "js", "java", "ts", "go", "rb", "php", "cs", "c", "cpp", "h", "hpp", "html", "htm", "css", "sql", "yaml", "yml", "json", "xml", "md", "sh", "bat", "ps1", "zip"]
)

# Analysis button
analyze_button = st.button("🔍 Analyze Code", type="primary", use_container_width=True)

if analyze_button:
    if not uploaded_files:
        st.warning("⚠️ Please upload some code files first.")
    else:
        with st.spinner("🔄 Preparing files for analysis..."):
            progress_bar = st.progress(0)
            status_text = st.empty()

            # Constants
            MAX_CONTENT_SIZE = 50 * 1024 * 1024  # 50 MB total
            MAX_FILE_SIZE = 10 * 1024 * 1024    # 10 MB per file
            SUPPORTED_EXTS = (".py", ".js", ".java", ".ts", ".go", ".rb", ".php", ".cs", ".c", ".cpp", ".h", ".hpp", ".html", ".htm", ".css", ".sql", ".yaml", ".yml", ".json", ".xml", ".md", ".sh", ".bat", ".ps1")

            def is_supported_file(filename: str) -> bool:
                return filename.lower().endswith(SUPPORTED_EXTS)

            def truncate_content(content: str, max_size: int, filename: str) -> str:
                if len(content) <= max_size:
                    return content
                st.info(f"📄 File '{filename}' was truncated as it exceeds the size limit.")
                return f"{content[:max_size]}\n\n... [Content truncated] ..."

            code_contents: List[Dict[str, str]] = []
            total_content_size = 0

            for idx, uploaded_file in enumerate(uploaded_files):
                progress_bar.progress((idx + 1) / len(uploaded_files))
                status_text.text(f"Processing file {idx + 1}/{len(uploaded_files)}: {uploaded_file.name}")

                if uploaded_file.name.lower().endswith('.zip'):
                    try:
                        with zipfile.ZipFile(io.BytesIO(uploaded_file.read()), 'r') as z:
                            for zip_info in z.infolist():
                                if zip_info.is_dir() or not is_supported_file(zip_info.filename):
                                    continue
                                if total_content_size >= MAX_CONTENT_SIZE:
                                    st.warning("Total content size limit reached. Some files from the zip were skipped.")
                                    break
                                file_content = z.read(zip_info.filename).decode("utf-8", errors="replace")
                                file_content = truncate_content(file_content, MAX_FILE_SIZE, zip_info.filename)
                                code_contents.append({"filename": zip_info.filename, "content": file_content})
                                total_content_size += len(file_content)
                    except Exception as e:
                        st.error(f"Error processing zip '{uploaded_file.name}': {str(e)}")
                else:
                    try:
                        if total_content_size >= MAX_CONTENT_SIZE:
                            st.warning("Total content size limit reached. Skipping remaining files.")
                            break
                        file_content = uploaded_file.getvalue().decode("utf-8", errors="replace")
                        file_content = truncate_content(file_content, MAX_FILE_SIZE, uploaded_file.name)
                        code_contents.append({"filename": uploaded_file.name, "content": file_content})
                        total_content_size += len(file_content)
                    except Exception as e:
                        st.error(f"Error processing '{uploaded_file.name}': {str(e)}")

            if not code_contents:
                st.error("No valid code files found.")
                st.stop()
        
        # This is the high-quality prompt from the "OLD" script
        prompt_parts = [
            """# Code Review Request

You are an expert software engineer conducting a comprehensive code review.

## Thinking Process:
Follow these steps in your analysis:
1.  **Initial Assessment**: Understand each file's purpose and role.
2.  **Deep Analysis**: Examine code structure, patterns, error handling, security, and performance.
3.  **Issue Prioritization**: Categorize issues using this exact scale:
    - **CRITICAL**: Issues that could lead to security breaches, data loss, or system failures.
    - **HIGH**: Significant problems affecting functionality, maintainability, or performance.
    - **MEDIUM**: Issues that should be addressed but don't immediately impact operation.
    - **LOW**: Minor improvements, style suggestions, or documentation enhancements.
4.  **Recommendation Formulation**: For each issue, provide a specific, actionable recommendation with code examples where helpful.

## Output Format:
1.  **Executive Summary** (A brief overall assessment).
2.  **File-by-File Analysis**: For each file, provide its purpose, strengths, issues found (organized by priority), and specific recommendations.
3.  **Overall Recommendations**: Discuss cross-cutting concerns and architectural suggestions.

Focus on providing actionable insights. Balance criticism with recognition of good practices.
""",
            "\n\n---\n\n"
        ]
        for item in code_contents:
            prompt_parts.append(f"Filename: {item['filename']}\n\n```\n{item['content']}\n```\n\n---\n\n")

        prompt = "".join(prompt_parts)

        # Send to OpenRouter with streaming support
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://your-app-domain.com",
                "X-Title": "AI-Powered Code Review"
            }
            messages = [
                {"role": "system", "content": "You are an expert software engineer providing a code review."},
                {"role": "user", "content": prompt}
            ]
            payload = {
                "model": "x-ai/grok-4",
                "messages": messages,
                "stream": True
            }

            st.subheader("📊 Code Review Results")
            review_placeholder = st.empty()
            review_text = ""

            with st.spinner("🧠 Grok-4 is analyzing..."):
                response = requests.post(url, headers=headers, json=payload, stream=True, timeout=600)
                response.raise_for_status()

                for line in response.iter_lines():
                    if line:
                        decoded = line.decode('utf-8')
                        if decoded.startswith("data: "):
                            try:
                                if "[DONE]" in decoded:
                                    break
                                data = json.loads(decoded[6:])
                                if "choices" in data and data["choices"][0]["delta"].get("content"):
                                    chunk = data["choices"][0]["delta"]["content"]
                                    review_text += chunk
                                    review_placeholder.markdown(review_text)
                            except json.JSONDecodeError:
                                continue

            if review_text:
                review_placeholder.empty()
                tab1, tab2, tab3 = st.tabs(["📝 Full Review", "📋 Summary", "🔍 Raw Prompt"])
                with tab1:
                    st.markdown(review_text)
                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    st.download_button("💾 Download Review", review_text, f"code_review_{timestamp}.md", "text/markdown")
                with tab2:
                    summary_match = re.search(r'executive summary.*?(?=##|\Z)', review_text, re.IGNORECASE | re.DOTALL)
                    st.markdown(summary_match.group(0) if summary_match else "Could not generate a summary. See Full Review.")
                with tab3:
                    st.code(prompt, language="markdown")
            else:
                st.error("No response received from the API.")

        except Exception as e:
            st.error(f"An error occurred during the API call: {str(e)}")
            if "401" in str(e):
                st.warning("Authentication error: Invalid API key.")
            elif "quota" in str(e).lower() or "rate" in str(e).lower():
                st.warning("You may have exceeded your API quota or rate limits.")

# --- Sidebar ---
st.sidebar.header("📚 How to Use")
st.sidebar.markdown("""
1.  Upload your code files or a zip archive.
2.  Click the "Analyze Code" button.
3.  Review the results as they stream in.
4.  Download the report for future reference.
""")
