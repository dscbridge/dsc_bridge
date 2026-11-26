import frappe
from frappe.tests.utils import FrappeTestCase

from dsc_bridge import api

# no test records for the linked doctypes: these tests make what they need themselves
test_ignore = ["ToDo", "DocType", "User", "Role", "Print Format", "Module Def", "File"]


def make_pdf(signed):
	"""A valid one-page PDF (Frappe parses uploads with pypdf); with signed=True it carries a signature field
	and a /Sig dictionary with a ByteRange, the marks validate_signed_pdf looks for."""
	objs = [
		b"<< /Type /Catalog /Pages 2 0 R"
		+ (b" /AcroForm << /Fields [4 0 R] /SigFlags 3 >>" if signed else b"")
		+ b" >>",
		b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
		+ (b" /Annots [4 0 R]" if signed else b"")
		+ b" >>",
	]
	if signed:
		objs += [
			b"<< /Type /Annot /Subtype /Widget /FT /Sig /T (Sig1) /Rect [0 0 0 0] /F 132 /P 3 0 R /V 5 0 R >>",
			b"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /ETSI.CAdES.detached /ByteRange [0 0 0 0] /Contents <00> >>",
		]
	out = bytearray(b"%PDF-1.4\n")
	offsets = []
	for i, body in enumerate(objs, 1):
		offsets.append(len(out))
		out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
	xref = len(out)
	out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
	for off in offsets:
		out += b"%010d 00000 n \n" % off
	out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
	return bytes(out)


SIGNED = make_pdf(signed=True)
UNSIGNED = make_pdf(signed=False)
CERT = '{"cn": "TEST SIGNER", "org": "Example Traders", "serial": "1234", "valid_to": "2027-01-01", "version": "1.0.0"}'


def enable(doctype, submitted_only=0):
	settings = frappe.get_single("DSC Bridge Settings")
	settings.enabled = 1
	settings.keep_log = 1
	if not any(r.document_type == doctype for r in settings.document_types):
		settings.append(
			"document_types", {"document_type": doctype, "submitted_only": submitted_only, "reason": "Test"}
		)
	settings.save(ignore_permissions=True)


class TestAttach(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		enable("ToDo")

	def setUp(self):
		frappe.set_user("Administrator")

	def todo(self):
		return frappe.get_doc({"doctype": "ToDo", "description": "DSC Bridge test"}).insert()

	def test_boot_settings_shape(self):
		boot = api.boot_settings()
		self.assertEqual(boot["enabled"], 1)
		self.assertIn("ToDo", boot["doctypes"])
		self.assertEqual(boot["doctypes"]["ToDo"]["reason"], "Test")
		self.assertTrue(boot["connector_url"].startswith("http"))
		self.assertEqual(api.get_settings()["version"], boot["version"])

	def test_attach_signed_pdf_and_log(self):
		doc = self.todo()
		out = api.attach(
			"ToDo",
			doc.name,
			SIGNED,
			print_format="Standard",
			reason="Test",
			location="Delhi",
			signer="TEST SIGNER",
			cert=CERT,
		)
		self.assertTrue(out["file_name"].endswith("-DSC.pdf"))
		file_doc = frappe.get_doc("File", {"attached_to_doctype": "ToDo", "attached_to_name": doc.name})
		self.assertEqual(file_doc.file_url, out["file_url"])
		self.assertEqual(file_doc.is_private, 1)
		with open(file_doc.get_full_path(), "rb") as f:
			self.assertEqual(f.read(), SIGNED)
		log = frappe.get_doc("DSC Sign Log", out["log"])
		self.assertEqual(log.reference_name, doc.name)
		self.assertEqual(log.signed_by, "Administrator")
		self.assertEqual(log.signer_name, "TEST SIGNER")
		self.assertEqual(log.signer_org, "Example Traders")
		self.assertEqual(str(log.certificate_valid_to), "2027-01-01")
		self.assertEqual(log.file, out["file_url"])
		self.assertEqual(log.file_size, len(SIGNED))
		self.assertEqual(log.connector_version, "1.0.0")

	def test_no_log_when_switched_off(self):
		settings = frappe.get_single("DSC Bridge Settings")
		settings.keep_log = 0
		settings.save(ignore_permissions=True)
		try:
			out = api.attach("ToDo", self.todo().name, SIGNED)
			self.assertIsNone(out["log"])
		finally:
			settings.keep_log = 1
			settings.save(ignore_permissions=True)

	def test_unsigned_pdf_rejected(self):
		doc = self.todo()
		self.assertRaises(frappe.ValidationError, api.attach, "ToDo", doc.name, UNSIGNED)
		self.assertRaises(frappe.ValidationError, api.attach, "ToDo", doc.name, b"hello")
		self.assertRaises(frappe.ValidationError, api.attach, "ToDo", doc.name, b"")

	def test_doctype_not_enabled_rejected(self):
		self.assertRaises(frappe.ValidationError, api.attach, "Role", "System Manager", SIGNED)

	def test_disabled_settings_rejected(self):
		settings = frappe.get_single("DSC Bridge Settings")
		settings.enabled = 0
		settings.save(ignore_permissions=True)
		try:
			self.assertRaises(frappe.ValidationError, api.attach, "ToDo", self.todo().name, SIGNED)
		finally:
			settings.enabled = 1
			settings.save(ignore_permissions=True)

	def test_submitted_only_rule(self):
		settings = frappe.get_single("DSC Bridge Settings")
		row = next(r for r in settings.document_types if r.document_type == "ToDo")
		row.submitted_only = 1
		settings.save(ignore_permissions=True)
		try:
			# a ToDo is never submitted (docstatus 0)
			self.assertRaises(frappe.ValidationError, api.attach, "ToDo", self.todo().name, SIGNED)
		finally:
			row.submitted_only = 0
			settings.save(ignore_permissions=True)

	def test_user_without_print_permission_rejected(self):
		doc = self.todo()
		email = "dsc-bridge-nobody@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Nobody",
					"send_welcome_email": 0,
					"user_type": "Website User",
				}
			).insert(ignore_permissions=True)
		frappe.set_user(email)
		try:
			self.assertRaises(frappe.PermissionError, api.attach, "ToDo", doc.name, SIGNED)
		finally:
			frappe.set_user("Administrator")

	def test_safe_file_name(self):
		self.assertEqual(api.safe_file_name("ACC-SINV-2026/00001", "-DSC"), "ACC-SINV-2026_00001-DSC.pdf")
		self.assertEqual(api.safe_file_name("2026-27/7720", ""), "2026-27_7720.pdf")
		self.assertEqual(api.safe_file_name("///", "-DSC"), "document-DSC.pdf")
