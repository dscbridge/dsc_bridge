import frappe
from frappe.tests.utils import FrappeTestCase

# no test records for the linked doctypes: these tests make what they need themselves
test_ignore = ["DocType", "Print Format", "Module Def"]


class TestDSCBridgeSettings(FrappeTestCase):
	def settings(self):
		return frappe.get_single("DSC Bridge Settings")

	def test_connector_url_must_be_http(self):
		s = self.settings()
		s.connector_url = "127.0.0.1:47831"
		self.assertRaises(frappe.ValidationError, s.save)

	def test_trailing_slash_is_dropped(self):
		s = self.settings()
		s.connector_url = "http://127.0.0.1:47831/"
		s.save()
		self.assertEqual(frappe.get_single("DSC Bridge Settings").connector_url, "http://127.0.0.1:47831")

	def test_duplicate_document_type_rejected(self):
		s = self.settings()
		s.append("document_types", {"document_type": "Note"})
		s.append("document_types", {"document_type": "Note"})
		self.assertRaises(frappe.ValidationError, s.save)

	def test_print_format_must_match_document_type(self):
		# any existing print format of another doctype, paired with Note, must be refused
		other = frappe.get_all("Print Format", filters={"doc_type": ["!=", "Note"]}, pluck="name", limit=1)
		if not other:
			self.skipTest("no Print Format on this site")
		s = self.settings()
		s.append("document_types", {"document_type": "Note", "print_format": other[0]})
		self.assertRaises(frappe.ValidationError, s.save)
