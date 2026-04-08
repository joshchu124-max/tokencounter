"""PyInstaller runtime hook for TokenCounter.

Sets TIKTOKEN_CACHE_DIR so tiktoken can find bundled encoding files
when running from a PyInstaller bundle.
"""

import os
import sys

if getattr(sys, "_MEIPASS", None):
    tiktoken_cache = os.path.join(sys._MEIPASS, "tiktoken_cache")
    if os.path.isdir(tiktoken_cache):
        os.environ["TIKTOKEN_CACHE_DIR"] = tiktoken_cache
