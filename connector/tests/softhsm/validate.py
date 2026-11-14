"""Print every signature in a PDF: intact / valid / signer / reason / location / page count. Exit 1 if none is valid."""

import sys

from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

r = PdfFileReader(open(sys.argv[1], "rb"), strict=False)
good = 0
for s in r.embedded_signatures:
	st = validate_pdf_signature(s, ValidationContext(allow_fetching=False))
	print(
		"SIG", s.field_name, "intact", st.intact, "valid", st.valid, "trusted", st.trusted,
		"signer", st.signing_cert.subject.human_friendly, "reason", s.sig_object.get("/Reason"),
		"loc", s.sig_object.get("/Location"), "pages", r.root["/Pages"]["/Count"],
	)
	good += int(bool(st.intact and st.valid))
sys.exit(0 if good else 1)
