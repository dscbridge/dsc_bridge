import frappe
from frappe.tests.utils import FrappeTestCase

# no test records for the linked doctypes: these tests make what they need themselves
test_ignore = ["DocType", "User", "Role"]


class TestDSCSignLog(FrappeTestCase):
	def test_log_names_and_links(self):
		log = frappe.get_doc(
			{
				"doctype": "DSC Sign Log",
				"reference_doctype": "Role",
				"reference_name": "System Manager",
				"signed_by": "Administrator",
				"signer_name": "TEST SIGNER",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(log.name.startswith("DSC-SIGN-"))
		self.assertEqual(frappe.db.get_value("DSC Sign Log", log.name, "reference_name"), "System Manager")
