"""Server side of DSC Bridge: the settings for the browser, and attaching the signed PDF.

The signing itself never happens here. The user's browser fetches the document's PDF from this site, hands it to
the DSC Bridge Connector running on the user's own computer (where the USB token is plugged in), and posts the
signed PDF back to attach_signed_pdf. The token PIN and the private key never reach this server.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from dsc_bridge import __version__

# Home of the project: README, connector downloads (Releases), issues
REPO_URL = "https://github.com/dscbridge/dsc_bridge"
MAX_PDF_BYTES = 50 * 1024 * 1024


def boot_settings():
	"""The settings the browser needs, as a plain dict (also sent with the session boot)."""
	settings = frappe.get_cached_doc("DSC Bridge Settings")
	doctypes = {}
	for row in settings.get("document_types") or []:
		if row.document_type:
			doctypes[row.document_type] = {
				"print_format": row.print_format or None,
				"submitted_only": cint(row.submitted_only),
				"reason": row.reason or None,
			}
	return {
		"enabled": cint(settings.enabled),
		"connector_url": (settings.connector_url or "http://127.0.0.1:47831").rstrip("/"),
		"file_suffix": settings.file_suffix if settings.file_suffix is not None else "-DSC",
		"default_reason": settings.default_reason or "",
		"default_location": settings.default_location or "",
		"location_field": settings.location_field or "",
		"keep_log": cint(settings.keep_log),
		"doctypes": doctypes,
		"repo_url": REPO_URL,
		"version": __version__,
	}


@frappe.whitelist()
def get_settings():
	return boot_settings()


@frappe.whitelist()
def attach_signed_pdf(doctype, name, print_format=None, reason=None, location=None, signer=None, cert=None):
	"""Attach the signed PDF (multipart field "file") to the document and write a DSC Sign Log entry."""
	upload = frappe.request.files.get("file") if getattr(frappe, "request", None) and frappe.request.files else None
	if upload is None:
		frappe.throw(_("No signed PDF was received."))
	content = upload.stream.read()
	return attach(
		doctype,
		name,
		content,
		print_format=print_format,
		reason=reason,
		location=location,
		signer=signer,
		cert=cert,
	)


def attach(doctype, name, content, print_format=None, reason=None, location=None, signer=None, cert=None):
	"""Attach signed PDF bytes to a document the user may print, and log it. Used by attach_signed_pdf and tests."""
	settings = boot_settings()
	if not settings["enabled"]:
		frappe.throw(_("DSC Bridge is disabled in DSC Bridge Settings."))
	rule = settings["doctypes"].get(doctype)
	if not rule:
		frappe.throw(_("{0} is not enabled for DSC signing in DSC Bridge Settings.").format(_(doctype)))
	doc = frappe.get_doc(doctype, name)
	# The right to print a document is the right to attach its signed print.
	doc.check_permission("print")
	if doc.docstatus == 2:
		frappe.throw(_("A cancelled document cannot be signed."))
	if rule["submitted_only"] and doc.docstatus != 1:
		frappe.throw(_("Only submitted {0} documents can be signed.").format(_(doctype)))
	validate_signed_pdf(content)

	if isinstance(cert, str):
		cert = json.loads(cert) if cert.strip() else {}
	cert = cert or {}

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": safe_file_name(name, settings["file_suffix"]),
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"folder": "Home/Attachments",
			"is_private": 1,
			"content": content,
		}
	).insert(ignore_permissions=True)

	log_name = None
	if settings["keep_log"]:
		log = frappe.get_doc(
			{
				"doctype": "DSC Sign Log",
				"reference_doctype": doctype,
				"reference_name": name,
				"signed_by": frappe.session.user,
				"signed_on": now_datetime(),
				"signer_name": (signer or cert.get("cn") or "")[:140],
				"signer_org": (cert.get("org") or "")[:140],
				"certificate_serial": (cert.get("serial") or "")[:140],
				"certificate_valid_to": cert.get("valid_to") or None,
				"print_format": (print_format or "")[:140],
				"reason": (reason or "")[:140],
				"location": (location or "")[:140],
				"file": file_doc.file_url,
				"file_size": len(content),
				"connector_version": (cert.get("version") or "")[:40],
			}
		).insert(ignore_permissions=True)
		log_name = log.name

	return {"file_url": file_doc.file_url, "file_name": file_doc.file_name, "log": log_name}


def validate_signed_pdf(content):
	if not content or content[:5] != b"%PDF-":
		frappe.throw(_("The file is not a PDF."))
	if len(content) > MAX_PDF_BYTES:
		frappe.throw(_("The signed PDF is larger than {0} MB.").format(MAX_PDF_BYTES // (1024 * 1024)))
	if b"/ByteRange" not in content or b"/Sig" not in content:
		frappe.throw(_("The PDF carries no digital signature."))


def safe_file_name(name, suffix):
	base = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "document"
	return f"{base}{suffix or ''}.pdf"
