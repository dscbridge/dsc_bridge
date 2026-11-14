import os
import sys
import tempfile

# the connector reads (and writes) config.json next to itself at import: keep tests away from a real config
_tmp = tempfile.mkdtemp(prefix="dscbridge-test-")
os.environ.setdefault("DSC_CONFIG", os.path.join(_tmp, "config.json"))
os.environ.setdefault("DSC_LOG", os.path.join(_tmp, "connector.log"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
