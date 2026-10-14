"""Run at start-up by every Python process whose ``PYTHONPATH`` holds this folder (see
``worker_hooks.environment``): installs the test hooks, then runs the interpreter's own
``sitecustomize``, if any, which this module shadows."""

import importlib.machinery
import importlib.util
import os
import sys

import worker_hooks

worker_hooks.install_from_environment()

_here = os.path.dirname(os.path.abspath(__file__))
_rest = [p for p in sys.path if os.path.abspath(p or os.curdir) != _here]
_spec = importlib.machinery.PathFinder.find_spec("sitecustomize", _rest)
if _spec is not None and _spec.loader is not None:
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
