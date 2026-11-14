// DSC Bridge Settings: filters on the document-type table, connector download links, a connector check.
frappe.ui.form.on("DSC Bridge Settings", {
	setup(frm) {
		frm.set_query("document_type", "document_types", () => ({
			filters: { istable: 0, issingle: 0 },
		}));
		frm.set_query("print_format", "document_types", (doc, cdt, cdn) => ({
			filters: { doc_type: locals[cdt][cdn].document_type || "", disabled: 0 },
		}));
	},

	refresh(frm) {
		const boot = frappe.boot.dsc_bridge || {};
		const repo = boot.repo_url || "https://github.com/dscbridge/dsc_bridge";
		const url = frappe.utils.escape_html(frm.doc.connector_url || "http://127.0.0.1:47831");
		frm.get_field("connector_help").$wrapper.html(`
			<p>${__("Every user who signs needs the small <b>DSC Bridge Connector</b> on their own computer: it reads the USB DSC token through the token's driver and signs the PDF there. The token's private key never leaves the token; the PIN never leaves that computer.")}</p>
			<p>
				<a href="${repo}/releases/latest" target="_blank" rel="noopener">${__("Download the connector (Windows one-click kit, Mac kit)")}</a> &middot;
				<a href="${repo}#readme" target="_blank" rel="noopener">${__("Setup guide")}</a> &middot;
				<a href="${url}/" target="_blank" rel="noopener">${__("Open the connector status page on this computer")}</a>
			</p>
			<p class="text-muted">${__("Browsers: Chrome, Edge and Firefox reach a connector on the same computer from an HTTPS site; Safari does not.")}</p>
		`);
	},

	test_connector(frm) {
		const base = (frm.doc.connector_url || "http://127.0.0.1:47831").replace(/\/+$/, "");
		const ctrl = new AbortController();
		const t = setTimeout(() => ctrl.abort(), 4000);
		frappe.dom.freeze(__("Asking the connector on this computer..."));
		fetch(base + "/status", { signal: ctrl.signal, cache: "no-store" })
			.then((r) => r.json())
			.then((st) => {
				const esc = frappe.utils.escape_html;
				const lines = [
					`<b>${__("Connector")}:</b> ${__("running")} (v${esc(st.version || "?")}, ${esc(st.os || "")})`,
					`<b>${__("Token driver")}:</b> ${esc(st.lib || __("not found"))}`,
					`<b>${__("Token")}:</b> ${esc((st.token && (st.token.label || st.token.model)) || __("not plugged in"))}`,
					`<b>${__("Certificate")}:</b> ${
						st.cert ? `${esc(st.cert.cn || "")} (${__("valid till")} ${esc(st.cert.valid_to || "")})` : "-"
					}`,
				];
				if (st.error) lines.push(`<span class="text-danger">${esc(st.error)}</span>`);
				frappe.msgprint({
					title: __("DSC Bridge Connector"),
					indicator: st.ok ? "green" : "orange",
					message: lines.join("<br>"),
				});
			})
			.catch(() => {
				frappe.msgprint({
					title: __("DSC Bridge Connector"),
					indicator: "red",
					message: __("No connector answered at {0}. Install and start it on this computer, then try again.", [
						frappe.utils.escape_html(base),
					]),
				});
			})
			.finally(() => {
				clearTimeout(t);
				frappe.dom.unfreeze();
			});
	},
});
