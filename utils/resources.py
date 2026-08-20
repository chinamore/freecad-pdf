"""Resolve bundled assets both in dev runs and PyInstaller builds."""
import os
import sys


def resource_path(relative):
    base = getattr(sys, "_MEIPASS",
                   os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    return os.path.join(base, relative)
