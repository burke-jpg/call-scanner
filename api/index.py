"""Vercel serverless entry point — wraps the Flask app."""

import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app
