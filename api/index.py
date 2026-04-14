"""Vercel entrypoint for the AI Control Pane FastAPI app."""

import os
import sys

from fastapi import FastAPI


CURRENT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.dirname(CURRENT_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    # Add the backend package directory so Vercel can import the FastAPI app.
    sys.path.insert(0, BACKEND_DIR)

from app.main import app as backend_app


app = FastAPI()
app.mount("/api", backend_app)
