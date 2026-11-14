import frappe

from dsc_bridge.api import boot_settings


def boot_session(bootinfo):
	"""Put the DSC Bridge settings on frappe.boot so the button needs no extra request."""
	if frappe.session.user == "Guest":
		return
	try:
		bootinfo.dsc_bridge = boot_settings()
	except Exception:
		# e.g. a migration that has not created the settings yet: the button simply stays away
		bootinfo.dsc_bridge = None
