"""Unit tests of the connector that need no token: stamp fitting, label search, certificate choice, origin rules."""

import datetime as dt
import io

import connector


def minimal_pdf(texts, size=(595, 842)):
	"""A one-page PDF whose content stream shows each (text, x, y, pt) in Helvetica, like a printed invoice."""
	content = (
		b"BT "
		+ b" ".join(
			b"/F1 %d Tf 1 0 0 1 %d %d Tm (%s) Tj" % (pt, x, y, t.encode("latin1")) for t, x, y, pt in texts
		)
		+ b" ET"
	)
	objs = [
		b"<< /Type /Catalog /Pages 2 0 R >>",
		b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
		% size,
		b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
		b"<< /Length %d >>stream\n" % len(content) + content + b"\nendstream",
	]
	out = io.BytesIO()
	out.write(b"%PDF-1.4\n")
	offsets = []
	for i, body in enumerate(objs, 1):
		offsets.append(out.tell())
		out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
	xref = out.tell()
	out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
	for off in offsets:
		out.write(b"%010d 00000 n \n" % off)
	out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
	return out.getvalue()


def reader(pdf):
	from pyhanko.pdf_utils.reader import PdfFileReader

	return PdfFileReader(io.BytesIO(pdf), strict=False)


def self_signed(cn="TEST SIGNER", org="Example Traders", sign_usage=None, serial=4660):
	from cryptography import x509
	from cryptography.hazmat.primitives import hashes
	from cryptography.hazmat.primitives.asymmetric import rsa
	from cryptography.x509.oid import NameOID

	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	name = x509.Name(
		[
			x509.NameAttribute(NameOID.COMMON_NAME, cn),
			x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
			x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
		]
	)
	now = dt.datetime.now(dt.timezone.utc)
	b = (
		x509.CertificateBuilder()
		.subject_name(name)
		.issuer_name(name)
		.public_key(key.public_key())
		.serial_number(serial)
		.not_valid_before(now - dt.timedelta(days=1))
		.not_valid_after(now + dt.timedelta(days=365))
	)
	if sign_usage is not None:
		b = b.add_extension(
			x509.KeyUsage(
				digital_signature=sign_usage,
				content_commitment=sign_usage,
				key_encipherment=not sign_usage,
				data_encipherment=False,
				key_agreement=False,
				key_cert_sign=False,
				crl_sign=False,
				encipher_only=False,
				decipher_only=False,
			),
			critical=True,
		)
	return b.sign(key, hashes.SHA256())


def test_text_width_and_wrap():
	assert connector.text_width("", 10) == 0
	assert connector.text_width("iii", 10) < connector.text_width("WWW", 10)
	lines = connector.wrap_text("one two three four five six", 10, 60)
	assert len(lines) > 1 and " ".join(lines) == "one two three four five six"


def test_fit_name_fills_the_box():
	size, lines = connector.fit_name("SHAMMI KUMAR AGARWAL", 100, 60)
	assert 3 < size <= 26
	assert all(connector.text_width(ln, size) <= 100.5 for ln in lines)
	assert " ".join(lines) == "SHAMMI KUMAR AGARWAL"


def test_fit_details_never_overflows():
	size, lines = connector.fit_details(
		["Digitally signed by A", "DN: cn=A c=IN o=B", "Date: 2026-01-01"], 120, 40
	)
	assert 3.5 <= size <= 7.0
	assert len(lines) * size * 1.18 <= 40.01


def test_stamp_labels_from_config(monkeypatch):
	monkeypatch.setitem(connector.CFG, "stamp_labels", ["Authorised Signatory", " signed-for ", ""])
	assert connector.stamp_labels() == ["authorisedsignatory", "signedfor"]
	monkeypatch.setitem(connector.CFG, "stamp_labels", None)
	assert connector.stamp_labels() == ["authorisedsignatory", "authorizedsignatory"]


def test_label_box_found_above_the_label(monkeypatch):
	monkeypatch.setitem(connector.CFG, "stamp_box", "auto")
	pdf = minimal_pdf(
		[("For Example Traders", 420, 120, 9), ("Authorised Signatory", 430, 50, 9), ("Total", 40, 300, 9)]
	)
	spots = connector.sign_spots(reader(pdf))
	assert len(spots) == 1
	page, (x1, y1, x2, y2) = spots[0]
	assert page == 0
	assert y1 > 50 and y2 > y1 and y2 <= 120  # above the label, below "For ..."
	assert x2 - x1 <= connector.STAMP_WIDTH and x2 > 430


def test_label_box_ignores_text_drawn_after_the_label(monkeypatch):
	# a footer line after the signature label (drawn later, far left) must not pull the box to the left
	monkeypatch.setitem(connector.CFG, "stamp_box", "auto")
	pdf = minimal_pdf(
		[("For Example Traders", 420, 120, 9), ("Authorised Signatory", 444, 50, 9), ("E. & O.E.", 46, 30, 7)]
	)
	page, (x1, y1, x2, y2) = connector.sign_spots(reader(pdf))[0]
	assert x2 > 444 and x2 - x1 == connector.STAMP_WIDTH


def test_sign_spots_fallback_bottom_right_without_label(monkeypatch):
	monkeypatch.setitem(connector.CFG, "stamp_box", "auto")
	pdf = minimal_pdf([("Hello", 40, 700, 12)])
	assert connector.sign_spots(reader(pdf)) == [(0, (595 - 270, 44, 595 - 42, 104))]


def test_sign_spots_fixed_box(monkeypatch):
	monkeypatch.setitem(connector.CFG, "stamp_box", [10, 20, 210, 80])
	pdf = minimal_pdf([("Authorised Signatory", 430, 50, 9)])
	assert connector.sign_spots(reader(pdf)) == [(0, (10, 20, 210, 80))]


def test_cert_info_and_stamp_details():
	cert = self_signed()
	info = connector.cert_info(cert)
	assert info["cn"] == "TEST SIGNER" and info["org"] == "Example Traders" and info["serial"] == "1234"
	assert info["expired"] is False
	when = dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
	lines = connector.stamp_details(cert, "Tax Invoice", "Delhi", when)
	assert lines[0] == "Digitally signed by TEST SIGNER"
	assert lines[1] == "DN: cn=TEST SIGNER c=IN o=Example Traders"
	assert lines[2:] == ["Reason: Tax Invoice", "Location: Delhi", "Date: 2026-01-02 03:04+05:30"]


def test_pick_signing_cert_prefers_signing_key_usage():
	certs = [
		(b"\x01", self_signed("SAME NAME", sign_usage=False, serial=1), "enc"),
		(b"\x02", self_signed("SAME NAME", sign_usage=True, serial=2), "sig"),
	]
	assert connector.pick_signing_cert(certs)[2] == "sig"
	assert connector.pick_signing_cert(certs, private_ids={b"\x02"})[2] == "sig"
	assert connector.pick_signing_cert([]) is None


class _Req:
	"""Just enough of a request for Handler._origin_ok."""

	def __init__(self, origin):
		self.headers = {"Origin": origin} if origin is not None else {}


def test_origin_rules(monkeypatch):
	ok = connector.Handler._origin_ok
	monkeypatch.setitem(connector.CFG, "allowed_origins", ["*"])
	assert ok(_Req("https://erp.example.com")) == "https://erp.example.com"
	assert ok(_Req(None)) == "*"
	monkeypatch.setitem(connector.CFG, "allowed_origins", ["https://erp.example.com"])
	assert ok(_Req("https://erp.example.com")) == "https://erp.example.com"
	assert ok(_Req("https://evil.example.net")) is None
	assert ok(_Req(None)) is None
