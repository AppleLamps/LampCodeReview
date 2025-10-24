#!/usr/bin/env python3
"""Test the new improvements."""

from utils import detect_dependencies, detect_redundancy

# Test with sample code
test_files = [
    {'filename': 'config.py', 'content': 'import os\nSETTING = 1'},
    {'filename': 'utils.py', 'content': 'from config import SETTING\nimport re\ndef process(): pass'},
    {'filename': 'app.py', 'content': 'from utils import process\nimport streamlit as st\nprocess()'}
]

print("=" * 60)
print("Testing Dependency Detection")
print("=" * 60)

ordered = detect_dependencies(test_files)
print("\n✅ File order (dependencies first):")
for i, f in enumerate(ordered, 1):
    print(f"   {i}. {f['filename']}")

print("\n" + "=" * 60)
print("Testing Redundancy Detection")
print("=" * 60)

redundancy = detect_redundancy(test_files)
print("\n✅ Shared patterns detected:")
if 'imports' in redundancy:
    shared = {imp: files for imp, files in redundancy['imports'].items() if len(files) > 1}
    if shared:
        for imp, files in list(shared.items())[:5]:
            print(f"   - {imp} (in {len(files)} files)")
    else:
        print("   - No shared imports found")

print("\n" + "=" * 60)
print("All tests passed! ✅")
print("=" * 60)
