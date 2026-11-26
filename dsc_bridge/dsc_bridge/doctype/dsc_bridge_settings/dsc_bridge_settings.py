import frappe
from frappe import _
from frappe.model.document import Document


class DSCBridgeSettings(Document):
	def validate(self):
		self.connector_url = (self.connector_url or "").strip().rstrip("/")
		if not self.connector_url.startswith(("http://", "https://")):
			frappe.throw(_("Connector URL must start with http:// or https://"))
		seen = set()
		for row in self.document_types:
			if row.document_type in seen:
				frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, row.document_type))
			seen.add(row.document_type)
			if (
				row.print_format
				and frappe.db.get_value("Print Format", row.print_format, "doc_type") != row.document_type
			):
				frappe.throw(
					_("Row {0}: Print Format {1} is not for {2}.").format(
						row.idx, row.print_format, row.document_type
					)
				)

	def on_update(self):
		# the settings travel to the browser with the session boot (hooks.boot_session), and Frappe caches the
		# boot per user: drop it so every user gets the new settings on the next page load
		frappe.cache.delete_value("bootinfo")
