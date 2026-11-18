"""`python -m harness ...` (what installed hooks call, so no PATH setup is needed)."""

from .cli import main

raise SystemExit(main())
