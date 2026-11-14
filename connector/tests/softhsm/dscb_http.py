"""Tiny HTTP client for the sign test (no curl in slim images): http.py GET url | POST url outfile [header=value ...] [@file]"""

import json
import sys
import urllib.error
import urllib.request

method, url = sys.argv[1], sys.argv[2]
out = sys.argv[3] if method == "POST" else None
headers, body = {}, None
for a in sys.argv[4:]:
	if a.startswith("@"):
		body = open(a[1:], "rb").read()
	elif a.startswith("="):
		body = a[1:].encode()
	else:
		k, v = a.split("=", 1)
		headers[k] = v
req = urllib.request.Request(url, data=body, headers=headers, method=method)
try:
	with urllib.request.urlopen(req, timeout=120) as r:
		data, code = r.read(), r.status
except urllib.error.HTTPError as e:
	data, code = e.read(), e.code
if out:
	open(out, "wb").write(data)
	print(code)
else:
	sys.stdout.write(data.decode("utf-8", "replace"))
