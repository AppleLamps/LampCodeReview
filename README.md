# 🤖 Grok-4 Code Review (via OpenRouter)

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-ff69b4.svg)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Streamlit web application that leverages xAI's Grok-4 model (accessed via the OpenRouter API) to perform comprehensive, professional code reviews. This tool simulates an expert developer's thinking process to provide actionable insights into your codebase.

## Overview

This application allows you to upload multiple code files and receive a detailed analysis covering:

- ⚠️ **Security vulnerabilities**
- 🚀 **Performance bottlenecks**
- 🏗️ **Architecture and design patterns**
- 📝 **Code quality and maintainability**
- ✅ **Best practices and standards compliance**

The AI uses a structured, multi-step thinking process (defined in the prompt) to ensure a thorough and insightful review, similar to how a senior engineer would approach the task.

## Features

- **AI-Powered Analysis:** Utilizes the `x-ai/grok-4` model via OpenRouter for cutting-edge code understanding.
- **Structured Thinking Process:** Guides the AI through steps like Initial Assessment, Deep Analysis, Issue Prioritization, and Recommendation Formulation.
- **Multi-File Upload:** Analyze multiple related code files simultaneously for context-aware reviews.
- **Wide Language Support:** Accepts common file extensions (`.py`, `.js`, `.java`, `.ts`, `.go`, `.rb`, `.php`, `.cs`, `.c`, `.cpp`, `.html`, `.css`, `.sql`, etc.).
- **API Key Management:** Securely uses your OpenRouter API key (reads from `.env` file or prompts for input).
- **Dependency Auto-Installation:** Automatically installs missing required libraries (`streamlit`, `requests`, `python-dotenv`) on first run.
- **File Size Handling:** Implements limits (50MB total, 50MB per file) and truncates oversized files with a notification.
- **User-Friendly Interface:** Built with Streamlit for an interactive web experience.
- **Progress Indicators:** Shows spinners and a progress bar during analysis.
- **Detailed & Summarized Results:** Provides a full review and an executive summary tab.
- **Downloadable Reports:** Allows downloading the full review as a Markdown file.
- **Robust Error Handling:** Catches common API and file processing errors with informative messages.

## How It Works

1. **Input:** The user provides their OpenRouter API key and uploads one or more code files via the Streamlit interface.
2. **Preparation:** The script reads the content of the uploaded files. It checks file sizes, truncates large files if necessary, and notes any issues.
3. **Prompt Construction:** A detailed prompt is constructed. It includes:
    - Instructions defining the AI's role as an expert reviewer.
    - A specific multi-step "Thinking Process" for the AI to follow.
    - The desired output format (Executive Summary, File-by-File Analysis, Overall Recommendations).
    - The content of each uploaded file, clearly delimited.
4. **API Call:** The script sends the constructed prompt and file contents to the OpenRouter API, targeting the `x-ai/grok-4` model.
5. **Response Processing:** The AI analyzes the code based on the prompt and returns a structured code review.
6. **Output:** The application displays the AI-generated review in the Streamlit interface, separated into "Full Review" and "Summary" tabs. A download button is provided for the full report.

## Prerequisites

- **Python:** Version 3.7 or higher.
- **pip:** Python package installer (usually comes with Python).
- **OpenRouter Account:** Sign up at [OpenRouter.ai](https://openrouter.ai/).
- **OpenRouter API Key:** Obtain an API key from your OpenRouter dashboard. Ensure your key/account has access to the `x-ai/grok-4` model and sufficient credits.

## Installation

1. **Clone the Repository (Optional):**
    If you have the script as part of a repository:

    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

    If you only have the `app.py` file, navigate to the directory containing the file.

2. **Install Dependencies:**
    The script attempts to auto-install dependencies. However, it's good practice to install them manually, especially in virtual environments:

    ```bash
    pip install streamlit requests python-dotenv
    ```

    - `streamlit`: For creating the web application interface.
    - `requests`: For making API calls to OpenRouter.
    - `python-dotenv`: For loading the API key from a `.env` file.

## Configuration

The application requires your OpenRouter API key. You have two options:

1. **`.env` File (Recommended):**
    - Create a file named `.env` in the same directory as the script (`app.py`).
    - Add your API key to the file like this:

        ```env
        OPENROUTER_API_KEY=sk-or-v1-abc...xyz
        ```

    - The application will automatically load the key from this file. **Ensure `.env` is added to your `.gitignore` file if using version control.**

2. **Manual Input:**
    - If no `.env` file is found or the key isn't defined there, the application will prompt you to enter the API key directly in the web interface when you run it. This key is used only for the current session and is not stored persistently by the application.

## Usage

1. **Run the Streamlit App:**
    Open your terminal, navigate to the directory containing `app.py`, and run:

    ```bash
    streamlit run app.py
    ```

    This will start the web server and open the application in your default web browser.

2. **Enter API Key:** If you haven't configured a `.env` file, paste your OpenRouter API key into the input field.

3. **Upload Code Files:** Click the "Browse files" button or drag and drop your code files onto the uploader. Select one or more files you want reviewed.

4. **Analyze:** Click the "🔍 Analyze Code" button.

5. **Wait:** Observe the progress indicators. Analysis time depends on the number and size of files and the current API response time.

6. **Review Results:** Once complete, the analysis will appear in two tabs:
    - **📝 Full Review:** The complete, detailed review generated by the AI.
    - **📋 Summary:** An executive summary extracted from the full review.

7. **Download Report (Optional):** Click the "💾 Download Full Review" button to save the analysis as a Markdown (`.md`) file.

## Technology Stack

- **Language:** Python 3
- **Web Framework:** Streamlit
- **API Interaction:** Requests
- **AI Model Provider:** OpenRouter API
- **AI Model:** xAI Grok-4 Flash Preview (with thinking) (`x-ai/grok-4`)
- **Environment Variables:** python-dotenv

## Limitations and Error Handling

- **API Costs:** Using the OpenRouter API incurs costs based on token usage. Be mindful of the size of the code you upload.
- **API Rate Limits/Quotas:** You might encounter errors if you exceed your OpenRouter API rate limits or run out of credits.
- **Model Availability:** The specific Grok-4 model might occasionally be unavailable or experience high load.
- **Context Window & Truncation:** While Grok-4 has a large context window, extremely large codebases might still exceed limits. The script truncates individual files over 50MB and limits the total payload size, which might lead to incomplete analysis for very large inputs. A warning is displayed if the AI response appears truncated.
- **AI Hallucinations:** Like all LLMs, Grok-4 can sometimes make errors or "hallucinate" information. Always critically evaluate the suggestions provided.
- **Content Filters:** Code containing potentially sensitive or harmful patterns might trigger API content filters, resulting in an error or refused analysis.
- **Network Issues:** Standard network errors can occur during the API call.

The script includes basic error handling for API responses (e.g., invalid key, quota errors) and file processing issues.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
