# SPDX-License-Identifier: MIT OR Apache-2.0
"""`python -m bug_age`: the same command line as the installed `bug-age` command."""
import sys

from .cli import main

sys.exit(main())
