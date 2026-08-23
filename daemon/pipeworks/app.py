"""Entry point.

Kept deliberately thin: lifecycle lives in application.py, wiring in service.py.
"""
import sys

from .application import run


def main():
    return run(sys.argv)
