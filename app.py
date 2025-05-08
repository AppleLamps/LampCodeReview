# Install necessary libraries
import streamlit as st
import requests
from dotenv import load_dotenv
import os
import json
# Load environment variables from .env file
load_dotenv()

# Import time module for progress bar simulation
import time

# --- Streamlit app layout ---

st.set_page_config(layout="wide") # Use wide layout

st.title("🧠 AI-Powered Code Review with Gemini 2.5 (OpenRouter)")

# Use expanders for detailed explanations
with st.expander("About This Tool & How It Works"):
    st.write("""
    ## Advanced Code Analysis with AI Thinking

    Upload your code files for a comprehensive, professional review powered by Google's Gemini 2.5 model via OpenRouter with advanced thinking capabilities.

    ### How It Works:
    The AI uses a multi-step thinking process to analyze your code, similar to how an expert developer would approach a code review:

    1. 🔍 **Initial Assessment**: Understands each file's purpose and identifies languages/frameworks
    2. 🧩 **Deep Analysis**: Examines code structure, patterns, relationships, and implementation details
    3. ⚖️ **Issue Prioritization**: Categorizes findings by severity and impact
    4. 💡 **Recommendation Formulation**: Develops specific, actionable improvements with examples
    """)

with st.expander("What This Tool Analyzes For"):
    st.write("""
    ### This Tool Analyzes Your Code For:

    - ⚠️ **Security vulnerabilities** and potential risks
    - 🚀 **Performance bottlenecks** and optimization opportunities
    - 🏗️ **Architecture and design pattern** recommendations
    - 📝 **Code quality** and maintainability assessment
    - ✅ **Best practices** and industry standards compliance

    Get expert-level insights to improve your codebase with prioritized, actionable recommendations.
    """)

# API Key input
env_api_key = os.getenv("OPENROUTER_API_KEY")
if env_api_key:
    api_key = env_api_key
    st.info("API costs covered by @lamps_apple on 𝕏.")
else:
    api_key = st.text_input("Enter your OpenRouter API Key", type="password")

if not api_key:
    st.warning("Please enter your OpenRouter API key to proceed.")
else:
    # File uploader with improved guidance
    st.subheader("📁 Upload Your Code Files")

    with st.expander("Tips for Uploading Files"):
        st.info("""
        **Tips for best results:**
        - Upload related files together for context-aware analysis
        - Include main implementation files, not just configuration or data files
        - For large projects, focus on specific modules or components at a time
        """)

    import zipfile
    import io

    # Accept code files or a zip archive
    uploaded_files = st.file_uploader(
    "Select code files or a .zip archive to analyze",
    accept_multiple_files=True,
    type=["py", "js", "java", "ts", "go", "rb", "php", "cs", "c", "cpp", "h", "hpp", "html", "htm", "css", "sql", "yaml", "yml", "json", "xml", "md", "sh", "bat", "ps1", "zip"]
    )

    # Analysis button with improved styling
    col1, col2 = st.columns([3, 1])
    with col2:
        analyze_button = st.button("🔍 Analyze Code", type="primary", use_container_width=True)

    if analyze_button:
        if not uploaded_files:
            st.warning("⚠️ Please upload some code files first before analyzing.")
        else:
            with st.spinner("🔄 Analyzing your code... This may take a moment depending on the size and complexity of your files."):
                # Add a progress bar for better user experience
                progress_bar = st.progress(0)
                for i in range(100):
                    # Simulate progress
                    progress_bar.progress(i + 1)
                    if i < 30:
                        # Quick progress at start
                        time.sleep(0.01)
                    elif i < 60:
                        # Slower in the middle where "analysis" happens
                        time.sleep(0.03)
                    else:
                        # Quicker towards the end
                        time.sleep(0.01)

                st.success("✅ Analysis complete! Displaying results below.")

                # Prepare content for the model with size management
                code_contents = []
                total_content_size = 0
                MAX_CONTENT_SIZE = 50 * 1024 * 1024  # 50 MB total
                MAX_FILE_SIZE = 50 * 1024 * 1024    # 50 MB per individual file

                # Supported file extensions
                SUPPORTED_EXTS = (".py", ".js", ".java", ".ts", ".go", ".rb", ".php", ".cs", ".c", ".cpp", ".h", ".hpp", ".html", ".htm", ".css", ".sql", ".yaml", ".yml", ".json", ".xml", ".md", ".sh", ".bat", ".ps1")

                def is_supported_file(filename):
                    return filename.lower().endswith(SUPPORTED_EXTS)

                for uploaded_file in uploaded_files:
                    if uploaded_file.name.lower().endswith('.zip'):
                        try:
                            with zipfile.ZipFile(io.BytesIO(uploaded_file.read())) as z:
                                for zip_info in z.infolist():
                                    if zip_info.is_dir():
                                        continue
                                    if is_supported_file(zip_info.filename):
                                        try:
                                            file_content = z.read(zip_info.filename).decode("utf-8", errors="replace")
                                            file_size = len(file_content)
                                            if total_content_size + file_size > MAX_CONTENT_SIZE:
                                                st.warning(f"⚠️ File '{zip_info.filename}' skipped due to total content size limits. Try analyzing fewer files at once.")
                                                continue
                                            if file_size > MAX_FILE_SIZE:
                                                truncated_content = file_content[:MAX_FILE_SIZE]
                                                truncated_content += f"\n\n... [Content truncated - file is {file_size} bytes, showing first {MAX_FILE_SIZE} bytes] ...\n"
                                                code_contents.append({
                                                "filename": f"{zip_info.filename} (truncated)",
                                                "content": truncated_content
                                                })
                                                st.info(f"📄 File '{zip_info.filename}' was truncated for analysis as it exceeds size limits. Only the first portion will be analyzed.")
                                                total_content_size += len(truncated_content)
                                            else:
                                                code_contents.append({
                                                "filename": zip_info.filename,
                                                "content": file_content
                                                })
                                                total_content_size += file_size
                                        except Exception as file_error:
                                            st.error(f"⚠️ Error processing file '{zip_info.filename}' in zip: {str(file_error)}")
                                            continue
                        except Exception as zip_error:
                            st.error(f"⚠️ Error reading zip file '{uploaded_file.name}': {str(zip_error)}")
                            continue
                    else:
                        try:
                            # To read file as string:
                            file_content = uploaded_file.getvalue().decode("utf-8")
                            file_size = len(file_content)

                            # Check if this file would exceed our total size limit
                            if total_content_size + file_size > MAX_CONTENT_SIZE:
                                st.warning(f"⚠️ File '{uploaded_file.name}' skipped due to total content size limits. Try analyzing fewer files at once.")
                                continue

                            # Handle large files by truncating with a note
                            if file_size > MAX_FILE_SIZE:
                                truncated_content = file_content[:MAX_FILE_SIZE]
                                truncated_content += f"\n\n... [Content truncated - file is {file_size} bytes, showing first {MAX_FILE_SIZE} bytes] ...\n"

                                code_contents.append({
                                "filename": f"{uploaded_file.name} (truncated)",
                                "content": truncated_content
                                })

                                st.info(f"📄 File '{uploaded_file.name}' was truncated for analysis as it exceeds size limits. Only the first portion will be analyzed.")
                                total_content_size += len(truncated_content)
                            else:
                                # Add the full file content
                                code_contents.append({
                                "filename": uploaded_file.name,
                                "content": file_content
                                })
                                total_content_size += file_size
                        except Exception as file_error:
                            st.error(f"⚠️ Error processing file '{uploaded_file.name}': {str(file_error)}")
                            continue

            if not code_contents:
                st.warning("No readable file content found.")
            else:
                try:
                    # Construct the prompt optimized for Gemini 2.5's thinking capabilities
                    prompt_parts = [
                    """# Code Review Request

You are an expert software engineer conducting a comprehensive code review. I'll provide you with code files to analyze. Take your time to think through each step of the analysis process.

## Thinking Process:
Follow these steps in your analysis:

1. **Initial Assessment**:
   - First, understand what each file does and its purpose in the overall system
   - Identify the programming language and frameworks used
   - Note the general structure and organization patterns

2. **Deep Analysis** (for each file):
   - Examine the code structure and flow
   - Identify functions, classes, and their relationships
   - Look for design patterns or architectural approaches
   - Check for code smells and anti-patterns
   - Assess error handling and edge cases
   - Evaluate security considerations
   - Consider performance implications
   - Review adherence to language/framework best practices

3. **Issue Prioritization**:
   - CRITICAL: Issues that could lead to security breaches, data loss, or system failures
   - HIGH: Significant problems affecting functionality, maintainability, or performance
   - MEDIUM: Issues that should be addressed but don't immediately impact system operation
   - LOW: Minor improvements, style suggestions, or documentation enhancements

4. **Recommendation Formulation**:
   - For each issue, develop a specific, actionable recommendation
   - Where appropriate, provide code examples showing how to implement improvements
   - Consider trade-offs between different approaches
   - Ensure recommendations align with modern best practices

## Output Format:
1. **Executive Summary** (2-3 sentences providing an overall assessment)
2. **File-by-File Analysis**:
   - Purpose and role of the file
   - Strengths and good practices identified
   - Issues found (organized by priority)
   - Specific recommendations with code examples where helpful
3. **Overall Recommendations**:
   - Cross-cutting concerns
   - Architectural suggestions
   - Next steps for improvement

Balance criticism with recognition of good practices. Focus on providing actionable insights rather than just identifying problems.
""",
                    "\n\n---\n\n"
                    ]
                    for item in code_contents:
                        prompt_parts.append(f"Filename: {item['filename']}\n\n```\n{item['content']}\n```\n\n---\n\n")

                    # Send prompt to OpenRouter API
                    with st.spinner("🧠 AI is analyzing your code... This may take a minute for larger files..."):
                        status_placeholder = st.empty()
                        status_placeholder.info("Starting code analysis...")

                        try:
                            # OpenRouter API endpoint and headers
                            url = "https://openrouter.ai/api/v1/chat/completions"
                            headers = {
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://your-app-domain.com",  # Optional, set to your app's domain if you have one
                            "X-Title": "AI-Powered Code Review"
                            }
                            # Prepare the messages for OpenRouter (system + user)
                            messages = [
                            {
                            "role": "system",
                            "content": "You are an expert software engineer conducting a comprehensive code review. Take your time to think through each step of the analysis process."
                            },
                            {
                            "role": "user",
                            "content": "".join(prompt_parts)
                            }
                            ]
                            payload = {
                            "model": "google/gemini-2.5-pro-preview-05-06",
                            "messages": messages,
                            "max_tokens": 65535,
                            "temperature": 0.2,
                            "top_p": 0.85
                            }

                            status_placeholder.info("Sending code and prompt to OpenRouter...")

                            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=600)
                            if response.status_code != 200:
                                raise Exception(f"OpenRouter API error: {response.status_code} - {response.text}")

                            result = response.json()
                            # Extract the review text from the response
                            review_text = None
                            if "choices" in result and result["choices"]:
                                review_text = result["choices"][0]["message"]["content"]
                            else:
                                raise Exception("No response content from OpenRouter.")

                            status_placeholder.success("Analysis complete! Rendering results...")

                        except Exception as e:
                            st.error(f"⚠️ An error occurred during analysis: {str(e)}")
                            if "API key" in str(e).lower() or "authentication" in str(e).lower():
                                st.warning("Please check that your OpenRouter API key is valid and has access to the Gemini model.")
                            elif "quota" in str(e).lower() or "rate" in str(e).lower():
                                st.warning("You may have exceeded your API quota or rate limits. Please try again later.")
                            elif "model" in str(e).lower():
                                st.warning("The specified model may not be available. Try using a different Gemini model version.")
                            elif "content" in str(e).lower() or "safety" in str(e).lower():
                                st.warning("The content may have triggered safety filters. Please ensure your code doesn't contain sensitive or prohibited content.")
                            else:
                                st.info("Try uploading fewer files or smaller files if the error persists.")
                            review_text = None

                        status_placeholder.empty()

                        # Display the review with improved formatting
                        st.subheader("📊 Professional Code Review Results")

                        tab1, tab2 = st.tabs(["📝 Full Review", "📋 Summary"])

                        if not review_text:
                            st.error("Could not retrieve text from OpenRouter response.")
                            st.info("Try with fewer or smaller files, or try again later.")

                        # Check for potential truncation
                        if review_text and (
                            review_text.endswith("...") or
                            "I'll continue with" in review_text[-100:] or
                            not any(review_text.lower().endswith(end) for end in ['.', '!', '?', '?', ':', ';', ')', '}', ']'])
                        ):
                            st.warning("⚠️ The review might be truncated due to length limitations. Consider analyzing fewer files at once for more complete results.")

                        if review_text:
                            with tab1:
                                st.markdown(review_text)
                                timestamp = time.strftime("%Y%m%d-%H%M%S")
                                st.download_button(
                                    label="💾 Download Full Review",
                                    data=review_text,
                                    file_name=f"code_review_{timestamp}.md",
                                    mime="text/markdown",
                                )
                            with tab2:
                                import re
                                summary_match = re.search(r'executive summary.*?(?=##|\Z)', review_text, re.IGNORECASE | re.DOTALL)
                                if summary_match:
                                    st.markdown(summary_match.group(0))
                                else:
                                    paragraphs = review_text.split('\n\n')
                                    summary = '\n\n'.join(paragraphs[:3]) + "\n\n*(See Full Review tab for complete details)*"
                                    st.markdown(summary)
                except Exception as e:
                    st.error(f"⚠️ An error occurred during prompt construction or analysis: {str(e)}")

# --- Sidebar for instructions and info ---
st.sidebar.header("📚 How to Use")
st.sidebar.markdown("""
1.  **Upload Code Files**: Select one or more code files for analysis
2.  **Run Analysis**: Click the "Analyze Code" button and wait for results
3.  **Review Results**: Examine the detailed analysis and recommendations
4.  **Download Report**: Save the review for future reference or sharing
""")

st.sidebar.header("💡 Tips for Better Results")
st.sidebar.markdown("""
- For large projects, analyze related modules separately
- Include relevant configuration files for context
- Consider uploading interface definitions along with implementations
""")

st.sidebar.header("🔑 API Key Security")
st.sidebar.markdown("Don't worry about API keys! LampCodeReview is FREE!")

st.sidebar.header("🚀 Running Locally")
st.sidebar.code("""
# Clone the repository (if applicable)
git clone https://github.com/AppleLamps/LampCodeReview.git
cd LampCodeReview

# Install dependencies
pip install streamlit requests

# Run the app
streamlit run app.py
""")

st.sidebar.markdown("""
<div style="text-align: center; margin-top: 20px; color: gray; font-size: 0.8em;">
Powered by Google Gemini AI (via OpenRouter) | Created with Streamlit | v1.0.0
</div>
""", unsafe_allow_html=True)
