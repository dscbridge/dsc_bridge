from frappe.tests.utils import FrappeTestCase

# no test records for the linked doctypes: these tests make what they need themselves
test_ignore = ["DocType", "Print Format", "Module Def"]


class TestDSCBridgeDocumentType(FrappeTestCase):
	pass
