#!/usr/bin/env python3
"""Alias kept for old commands: the quotation checker is quote_check.py (printed page numbers read from each PDF)."""
import os, runpy, sys
sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quote_check.py")
runpy.run_path(sys.argv[0], run_name="__main__")
