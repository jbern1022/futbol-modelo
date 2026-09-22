"""
dixon_coles was extracted to its own standalone package
(packages/dixon-coles, see that package's README) rather than living
under src/models/ -- tests here import it as `from dixon_coles import
...`, same as any real consumer would. Every script that touches it
already does its own sys.path.insert (see e.g.
scripts/generate_slate.py); this is the equivalent for pytest
collection, which doesn't run through any one script's setup.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "packages", "dixon-coles", "src"))
