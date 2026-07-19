import streamlit as st
import requests
import os
import time
import re
import logging
from datetime import datetime
from typing import List, Any

from config import (
    MAX_TOTAL_SIZE, MAX_FILE_SIZE, SUPPORTED_EXTS, MODEL_OPTIONS, RATE_LIMIT_SECONDS,
    SYSTEM_PROMPT, IDE_INSTRUCTIONS_PROMPT
)
from review_service import prepare_review
from reviewer import stream_grok_review, StreamCancellationToken
from openrouter_client import validate_and_estimate_tokens, estimate_cost


def display_about_section():
    """Display the about section with tool description."""
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


def handle_api_key():
    """Handle API key retrieval and validation."""
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

    return api_key, api_key_source


def handle_file_upload():
    """Handle file upload section."""
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
    return uploaded_files


def handle_review_settings():
    """Handle review mode and model selection."""
    st.markdown("### ⚙️ Review Settings")
    col1, col2 = st.columns(2)

    with col1:
        review_mode = st.radio(
            "Select review mode:",
            ["Standard Review", "Refactor", "IDE Implementation Instructions"],
            help="Standard: Comprehensive analysis. Refactor: Focus on modularization and cleanup. IDE: Step-by-step instructions for Cursor/Trae AI."
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
        elif review_mode == "Refactor":
            st.info("🧩 Refactor mode focuses on identifying files and modules to refactor, improve cohesion, reduce coupling, and propose modular structure without changing behavior.")

    return review_mode, selected_model


def initialize_session_state():
    """Initialize all session state variables with default values."""
    defaults = {
        'review_complete': False,
        'review_result': "",
        'user_prompt': "",
        'selected_review_mode': "Standard Review",
        'selected_model': "x-ai/grok-4",
        'last_review_time': None,
        'upload_warnings': []
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def check_rate_limit():
    """Check if enough time has passed since last review."""
    if 'last_review_time' not in st.session_state or st.session_state.last_review_time is None:
        return True
    
    time_since_last = datetime.now() - st.session_state.last_review_time
    return time_since_last.total_seconds() >= RATE_LIMIT_SECONDS


def start_review(api_key, uploaded_files, review_mode, selected_model):
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
    
    # Prepare review: process files, build prompt, and validate
    with st.spinner("Processing uploaded files..."):
        code_contents, warnings, user_prompt, request_id, validation_tuple = prepare_review(
            uploaded_files=uploaded_files,
            review_mode=review_mode,
            selected_model=selected_model,
        )
    is_valid, size_message, estimated_tokens = validation_tuple

    # Show any warnings from processing
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

    # Persist session state
    st.session_state.upload_warnings = warnings
    st.session_state.user_prompt = user_prompt
    st.session_state.selected_review_mode = review_mode
    st.session_state.selected_model = selected_model
    st.session_state.request_id = request_id

    # Enhanced Request Preview UI
    with st.expander("📊 Request Preview & Details", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Files", len(code_contents))
        with col2:
            st.metric("Est. Tokens", f"~{estimated_tokens:,}")
        with col3:
            st.metric("Model", selected_model.split('/')[-1])
        with col4:
            st.metric("Est. Cost", f"${estimate_cost(estimated_tokens, selected_model):.4f}")

        # Token utilization bar
        max_tokens = 200000
        utilization = estimated_tokens / max_tokens
        st.progress(min(utilization, 1.0))
        st.caption(f"Token utilization: {utilization*100:.1f}% of {max_tokens:,} limit")

        # Validation result
        if not is_valid:
            st.error(f"❌ {size_message}")
            return
        elif "⚠️" in size_message or utilization > 0.75:
            st.warning(f"⚠️ {size_message}")
        else:
            st.success(f"✅ Request size OK: ~{estimated_tokens:,} tokens")

        # Request ID for diagnostics
        st.caption(f"🔖 Request ID: `{request_id}`")

        # File details
        st.markdown("**Files to be analyzed:**")
        for i, item in enumerate(code_contents, 1):
            lines = item['content'].count('\n')
            chars = len(item['content'])
            ext = item['filename'].split('.')[-1] if '.' in item['filename'] else 'txt'
            st.write(f"{i}. **{item['filename']}** — {lines:,} lines, {chars:,} chars ({ext})")

        # Processing warnings
        if warnings:
            st.markdown("**⚠️ Processing Notes:**")
            for w in warnings:
                st.caption(f"• {w}")

        # Action buttons
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔍 Preview Full Prompt", use_container_width=True):
                st.session_state.show_prompt_preview = True
        with col_b:
            if st.button("📋 Copy Prompt to Clipboard", use_container_width=True):
                st.code(user_prompt, language="markdown")
                st.success("Prompt displayed above — copy from the code block")

        # Show full prompt preview if requested
        if st.session_state.get("show_prompt_preview", False):
            with st.expander("📄 Full Prompt Preview", expanded=True):
                st.markdown(f"**System Prompt:** `{review_mode} mode`")
                st.code(user_prompt, language="markdown")
                if st.button("Close Preview"):
                    st.session_state.show_prompt_preview = False
                    st.rerun()

    # Determine if using IDE instructions mode
    use_ide_instructions = review_mode == "IDE Implementation Instructions"

    # Start streaming review directly (single click from the top-level button)
    cancel_token = StreamCancellationToken()
    st.session_state.active_cancel_token = cancel_token

    progress_bar = st.progress(0)
    result_container = st.empty()
    cancel_placeholder = st.empty()

    full_response = ""
    chunk_count = 0
    finished = False

    try:
        iterator = stream_grok_review(
            api_key, user_prompt, use_ide_instructions,
            model=st.session_state.selected_model,
            file_count=len(code_contents),
            review_mode=review_mode,
            cancel_token=cancel_token,
        )
        while not finished:
            try:
                with cancel_placeholder.container():
                    cancel_clicked = st.button("⏹️ Cancel", key=f"cancel_{request_id}")
                if cancel_clicked:
                    cancel_token.cancel()
                chunk = next(iterator)
                chunk_count += 1
                full_response += chunk
                progress = min(chunk_count / 100, 0.95)
                progress_bar.progress(progress)
                result_container.markdown(full_response)
            except StopIteration:
                finished = True
            except Exception as e:
                st.error(f"❌ Streaming failed: {e}")
                finished = True
                break
    except Exception as e:
        st.error(f"❌ Streaming failed: {e}")

    # Complete the progress bar
    progress_bar.progress(1.0)
    time.sleep(0.3)
    progress_bar.empty()
    cancel_placeholder.empty()

    # Store the result
    st.session_state.review_result = full_response
    st.session_state.review_complete = True
    st.session_state.pop("active_cancel_token", None)
    st.rerun()


def display_results():
    """Display the review results."""
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
                # Read the review mode from session state to select prompt
                mode_used = st.session_state.get("selected_review_mode")
                if mode_used == "IDE Implementation Instructions":
                    current_prompt = IDE_INSTRUCTIONS_PROMPT
                elif mode_used == "Refactor":
                    from config import REFACTOR_SYSTEM_PROMPT  # local import to avoid top-level cycle
                    current_prompt = REFACTOR_SYSTEM_PROMPT
                else:
                    current_prompt = SYSTEM_PROMPT
                st.markdown(f"```markdown\n{current_prompt}\n```")
            with st.expander("User Prompt (Your Code)"):
                st.code(st.session_state.user_prompt, language="markdown")
            with st.expander("Run Configuration"):
                st.write({
                    "model": st.session_state.get("selected_model", "x-ai/grok-4"),
                    "review_mode": st.session_state.get("selected_review_mode", "Standard Review"),
                    "api_key_source": api_key_source or "unknown",
                    "upload_warnings": st.session_state.get("upload_warnings", []),
                })


# --- Main App Logic ---
st.set_page_config(layout="wide", page_title="AI Code Review")
st.title("🤖 AI Code Review")
st.subheader("Powered by OpenRouter")

display_about_section()

api_key, api_key_source = handle_api_key()

if api_key:
    uploaded_files = handle_file_upload()
    review_mode, selected_model = handle_review_settings()
    
    # Initialize session state
    initialize_session_state()
    
    # Analyze Button
    if st.button("🚀 Analyze Code", type="primary", use_container_width=True):
        start_review(api_key, uploaded_files, review_mode, selected_model)

    # Display Results
    display_results()
