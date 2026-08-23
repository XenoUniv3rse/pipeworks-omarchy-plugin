#!/usr/bin/env python3
"""Development launcher. Installed systems get the `pipeworks` command instead."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeworks.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
