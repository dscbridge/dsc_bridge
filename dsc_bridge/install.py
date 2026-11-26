import frappe

PRINT_FORMAT = "DSC Bridge Invoice"
MARKER = "dsc_bridge print format"


def before_install():
	"""A bench that built its module map before this app was added to apps.txt would skip the sync of this app's
	DocTypes (frappe.local.app_modules is filled once per process). Rebuild it so install-app always syncs."""
	frappe.cache.delete_value(["app_modules", "module_app", "installed_app_modules", "module_installed_app"])
	frappe.setup_module_map()


def after_install():
	"""First settings. Sales Invoice is pre-configured when ERPNext is installed; more document types
	are added in DSC Bridge Settings."""
	settings = frappe.get_single("DSC Bridge Settings")
	if settings.get("document_types"):
		return
	settings.enabled = 1
	settings.connector_url = settings.connector_url or "http://127.0.0.1:47831"
	settings.file_suffix = settings.file_suffix or "-DSC"
	settings.keep_log = 1
	settings.default_reason = settings.default_reason or "Digitally signed"
	settings.location_field = settings.location_field or "place_of_supply"
	if frappe.db.exists("DocType", "Sales Invoice"):
		settings.append(
			"document_types",
			{"document_type": "Sales Invoice", "submitted_only": 1, "reason": "Tax Invoice"},
		)
	settings.flags.ignore_permissions = True
	settings.save()
	ensure_print_format()


def after_migrate():
	ensure_print_format()


def ensure_print_format():
	"""A ready invoice print format with the signature box the connector stamps ("For <company>" over
	"Authorised Signatory"). Made when ERPNext is there; refreshed on migrate while it still carries our marker,
	so a user's own edit of it is never overwritten."""
	if not frappe.db.exists("DocType", "Sales Invoice") or not frappe.db.exists("Module Def", "DSC Bridge"):
		return
	html = frappe.read_file(
		frappe.get_app_path("dsc_bridge", "templates", "print_formats", "dsc_bridge_invoice.html")
	)
	if frappe.db.exists("Print Format", PRINT_FORMAT):
		current = frappe.db.get_value("Print Format", PRINT_FORMAT, "html") or ""
		if MARKER in current and current != html:
			# only the template text changes: no document events, so site-specific guards on Print Format stay quiet
			frappe.db.set_value("Print Format", PRINT_FORMAT, "html", html)
			frappe.clear_document_cache("Print Format", PRINT_FORMAT)
		return
	frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": PRINT_FORMAT,
			"doc_type": "Sales Invoice",
			"module": "DSC Bridge",
			"standard": "No",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"html": html,
			"font_size": 9,
			"margin_top": 10,
			"margin_bottom": 10,
			"margin_left": 10,
			"margin_right": 10,
			"disabled": 0,
		}
	).insert(ignore_permissions=True)
