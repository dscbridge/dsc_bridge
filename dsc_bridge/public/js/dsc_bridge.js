// DSC Bridge: "Sign with DSC" on the configured document types (form + print page).
//
// The USB DSC token sits in the user's own computer, so the signing is done there by the DSC Bridge Connector
// (a small program at http://127.0.0.1:47831). This script reads the connector's status (which token and
// certificate are plugged in), asks for the print format and the PIN, fetches the document's PDF from this site,
// sends it to the connector and attaches the signed PDF ("<name>-DSC.pdf") to the document. The PIN goes only to
// the connector on the same computer; this site never sees it.
(function () {
	if (window.dsc_bridge_loaded) return;
	window.dsc_bridge_loaded = true;

	const CFG = (frappe.boot && frappe.boot.dsc_bridge) || null;
	if (!CFG || !CFG.enabled || !CFG.doctypes) return;
	const DOCTYPES = Object.keys(CFG.doctypes);
	if (!DOCTYPES.length) return;
	const CONNECTOR = (CFG.connector_url || "http://127.0.0.1:47831").replace(/\/+$/, "");
	const SUFFIX = CFG.file_suffix == null ? "-DSC" : CFG.file_suffix;
	const REPO = CFG.repo_url || "https://github.com/dsc-bridge/dsc_bridge";

	function not_running() {
		return (
			__("The DSC Bridge Connector is not running on this computer.") +
			"<br>" +
			__("Start it (it runs at {0}) and plug in the DSC token, then try again.", [frappe.utils.escape_html(CONNECTOR)]) +
			`<br><a href="${REPO}/releases/latest" target="_blank" rel="noopener">${__("Download the connector")}</a>`
		);
	}

	function status() {
		const ctrl = new AbortController();
		const t = setTimeout(() => ctrl.abort(), 4000);
		return fetch(CONNECTOR + "/status", { signal: ctrl.signal, cache: "no-store" })
			.then((r) => r.json())
			.finally(() => clearTimeout(t));
	}

	function rule_of(doctype) {
		return CFG.doctypes[doctype] || {};
	}

	function can_sign(frm) {
		// the print page hands over a plain {doctype, docname, doc, meta} object, not a full form
		if (!frm || !frm.doc || frm.doc.__islocal || (typeof frm.is_new === "function" && frm.is_new())) return false;
		if (!DOCTYPES.includes(frm.doctype)) return false;
		if (frm.doc.docstatus === 2) return false;
		if (rule_of(frm.doctype).submitted_only && frm.doc.docstatus !== 1) return false;
		try {
			if (!frappe.model.can_print(frm.doctype, frm)) return false;
		} catch (e) {
			// older builds without can_print: the server checks the print permission anyway
		}
		return true;
	}

	function print_formats(frm) {
		let list = [];
		try {
			list = frappe.meta.get_print_formats(frm.doctype) || [];
		} catch (e) {
			list = [];
		}
		if (!list.length) list = [frm.meta.default_print_format || "Standard"];
		return list;
	}

	function default_format(frm, current) {
		const list = print_formats(frm);
		if (current && list.includes(current)) return current;
		const preset = rule_of(frm.doctype).print_format;
		if (preset && list.includes(preset)) return preset;
		if (frm.meta.default_print_format && list.includes(frm.meta.default_print_format)) return frm.meta.default_print_format;
		return list[0];
	}

	function default_location(frm) {
		const field = CFG.location_field;
		if (field && frm.doc[field]) {
			// "07-Delhi" (Indian place of supply) -> "Delhi"
			return String(frm.doc[field]).replace(/^\d+-/, "");
		}
		return CFG.default_location || "";
	}

	function default_reason(frm) {
		return rule_of(frm.doctype).reason || CFG.default_reason || "";
	}

	function signer_line(st) {
		if (!st) return "";
		const esc = frappe.utils.escape_html;
		const c = st.cert;
		if (!c) {
			return `<div class="text-muted">${__("Token")}: ${esc((st.token && st.token.label) || "-")}</div>`;
		}
		const who = esc(c.cn || c.org || "?");
		const till = esc(c.valid_to || "");
		const tok = esc((st.token && (st.token.label || st.token.model)) || "");
		return (
			`<div style="margin-bottom:8px"><b>${__("Signing as")}:</b> ${who}` +
			(till ? ` <span class="text-muted">(${__("valid till")} ${till})</span>` : "") +
			(tok ? `<br><span class="text-muted">${__("Token")}: ${tok}</span>` : "") +
			`</div>`
		);
	}

	async function do_sign(frm, v, letterhead) {
		const doctype = frm.doctype;
		const name = frm.doc.name;
		const params = { doctype: doctype, name: name, format: v.print_format, no_letterhead: 0 };
		if (letterhead) params.letterhead = letterhead;
		const r1 = await fetch("/api/method/frappe.utils.print_format.download_pdf?" + $.param(params), {
			credentials: "same-origin",
		});
		if (!r1.ok) throw new Error(__("The PDF could not be made (HTTP {0}).", [r1.status]));
		const pdf = await r1.arrayBuffer();

		let r2;
		try {
			r2 = await fetch(CONNECTOR + "/sign", {
				method: "POST",
				headers: {
					"Content-Type": "application/pdf",
					"X-Pin": v.pin,
					"X-Reason": v.reason || "",
					"X-Location": v.location || "",
					"X-Field-Name": "DSCBridge",
					"X-File-Name": name,
				},
				body: pdf,
			});
		} catch (e) {
			throw new Error(not_running());
		}
		if (!r2.ok) {
			const e = await r2.json().catch(() => ({}));
			throw new Error(e.error || __("Signing failed (HTTP {0}).", [r2.status]));
		}
		const signed = await r2.blob();
		const signer = r2.headers.get("X-Signer") || "";
		const cert = r2.headers.get("X-Signer-Info") || "";

		const fname = name.replace(/[^A-Za-z0-9._-]+/g, "_") + SUFFIX + ".pdf";
		const fd = new FormData();
		fd.append("file", signed, fname);
		fd.append("doctype", doctype);
		fd.append("name", name);
		fd.append("print_format", v.print_format || "");
		fd.append("reason", v.reason || "");
		fd.append("location", v.location || "");
		fd.append("signer", signer);
		fd.append("cert", cert);
		const r3 = await fetch("/api/method/dsc_bridge.api.attach_signed_pdf", {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
			body: fd,
			credentials: "same-origin",
		});
		const j = await r3.json().catch(() => ({}));
		if (!r3.ok) {
			let msg = "";
			try {
				msg = (JSON.parse(j._server_messages || "[]").map((m) => JSON.parse(m).message) || []).join("<br>");
			} catch (e) {
				msg = "";
			}
			throw new Error(msg || __("The signed PDF could not be attached (HTTP {0}).", [r3.status]));
		}
		return { file_url: j.message && j.message.file_url, signer: signer, fname: (j.message && j.message.file_name) || fname };
	}

	function open_dialog(frm, current_format, letterhead, after) {
		if (!frm.doc || frm.doc.__islocal) {
			frappe.show_alert({ message: __("Save the document first"), indicator: "orange" });
			return;
		}
		if (rule_of(frm.doctype).submitted_only && frm.doc.docstatus !== 1) {
			frappe.msgprint(__("Submit the document first. A DSC is put on the final document only."));
			return;
		}
		frappe.dom.freeze(__("Reading the DSC token..."));
		status()
			.then((st) => {
				frappe.dom.unfreeze();
				if (!st || (!st.ok && !st.cert)) {
					frappe.msgprint({ title: __("DSC"), indicator: "red", message: (st && st.error) || not_running() });
					return;
				}
				const d = new frappe.ui.Dialog({
					title: __("Sign {0} with DSC", [frm.doc.name]),
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "who",
							options:
								signer_line(st) +
								(st.error ? `<div class="text-danger">${frappe.utils.escape_html(st.error)}</div>` : ""),
						},
						{
							fieldtype: "Select",
							fieldname: "print_format",
							label: __("Print Format"),
							options: print_formats(frm).join("\n"),
							default: default_format(frm, current_format),
							reqd: 1,
						},
						{
							// a Data field shown as a password: Frappe's Password control would send the value to the
							// server to rate its strength, and the PIN must never leave this computer
							fieldtype: "Data",
							fieldname: "pin",
							label: __("DSC PIN"),
							reqd: 1,
							description: __("Used once on this computer to sign. Not saved anywhere, never sent to the server."),
						},
						{ fieldtype: "Column Break" },
						{ fieldtype: "Data", fieldname: "reason", label: __("Reason"), default: default_reason(frm) },
						{ fieldtype: "Data", fieldname: "location", label: __("Location"), default: default_location(frm) },
					],
					primary_action_label: __("Sign and Attach"),
					primary_action(v) {
						d.get_primary_btn().prop("disabled", true).text(__("Signing..."));
						do_sign(frm, v, letterhead)
							.then((r) => {
								d.hide();
								frappe.show_alert(
									{ message: __("Signed by {0} and attached as {1}", [r.signer || "DSC", r.fname]), indicator: "green" },
									8
								);
								if (after) after(r);
							})
							.catch((e) => {
								d.get_primary_btn().prop("disabled", false).text(__("Sign and Attach"));
								frappe.msgprint({ title: __("DSC"), indicator: "red", message: e.message || String(e) });
							});
					},
				});
				d.show();
				const $pin = d.fields_dict.pin && d.fields_dict.pin.$input;
				if ($pin) $pin.attr({ type: "password", autocomplete: "off", inputmode: "numeric" });
			})
			.catch(() => {
				frappe.dom.unfreeze();
				frappe.msgprint({ title: __("DSC"), indicator: "red", message: not_running() });
			});
	}

	/* the form: a "Sign with DSC" button on every signable document */
	DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (!can_sign(frm)) return;
				frm.add_custom_button(__("Sign with DSC"), () => {
					open_dialog(frm, null, null, () => frm.reload_doc());
				});
			},
		});
	});

	/* the print page: the same button in the sidebar, signing the print format and letterhead chosen there */
	function render_button(pv) {
		if (!pv || !pv.sidebar || !pv.frm) return;
		let $btn = pv.sidebar.find(".dsc-bridge-btn");
		if (!can_sign(pv.frm)) {
			$btn.hide();
			return;
		}
		if (!$btn.length) {
			$btn = $(
				`<button class="btn btn-default btn-sm btn-block dsc-bridge-btn" style="margin: 4px 0 8px;">${__(
					"Sign with DSC"
				)}</button>`
			);
			if (pv.sidebar_dynamic_section && pv.sidebar_dynamic_section.length) {
				$btn.insertAfter(pv.sidebar_dynamic_section);
			} else {
				$btn.appendTo(pv.sidebar);
			}
			$btn.on("click", () => {
				const pv2 = $btn.data("pv");
				let fmt = null;
				let lh = null;
				try {
					fmt = pv2.selected_format ? pv2.selected_format() : null;
				} catch (e) {
					fmt = null;
				}
				try {
					lh = pv2.get_letterhead ? pv2.get_letterhead() : null;
				} catch (e) {
					lh = null;
				}
				open_dialog(pv2.frm, fmt, lh, null);
			});
		}
		$btn.data("pv", pv);
		$btn.show();
	}

	function patch(PV) {
		if (!PV || PV.prototype.dsc_bridge_patched) return;
		PV.prototype.dsc_bridge_patched = true;
		const orig_show = PV.prototype.show;
		PV.prototype.show = function () {
			const out = orig_show.apply(this, arguments);
			try {
				render_button(this);
			} catch (e) {
				console.error("dsc_bridge", e);
			}
			return out;
		};
	}

	frappe.provide("frappe.ui.form");
	if (frappe.ui.form.PrintView) {
		patch(frappe.ui.form.PrintView);
	} else {
		let PV;
		Object.defineProperty(frappe.ui.form, "PrintView", {
			configurable: true,
			enumerable: true,
			get() {
				return PV;
			},
			set(v) {
				PV = v;
				patch(v);
			},
		});
	}

	// for other scripts: frappe.dsc_bridge.sign(frm)
	frappe.provide("frappe.dsc_bridge");
	frappe.dsc_bridge.sign = (frm, after) => open_dialog(frm, null, null, after || (() => frm.reload_doc()));
	frappe.dsc_bridge.status = status;
})();
