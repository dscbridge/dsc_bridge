app_name = "dsc_bridge"
app_title = "DSC Bridge"
app_publisher = "DSC Bridge"
app_description = "Sign ERP PDFs with the USB DSC token on your own computer"
app_email = "dscbridge@example.com"
app_license = "mit"
app_logo_url = "/assets/dsc_bridge/images/logo.svg"

# Works on plain Frappe; ERPNext is not required (Sales Invoice is pre-configured when it is there).
required_apps = ["frappe"]

# The "Sign with DSC" button on the configured document types (form + print page).
# A plain file, no bundle: it needs no asset build and no extra request per form.
app_include_js = "/assets/dsc_bridge/js/dsc_bridge.js"

# The settings go to the browser with the session boot (frappe.boot.dsc_bridge)
boot_session = "dsc_bridge.boot.boot_session"

before_install = "dsc_bridge.install.before_install"
after_install = "dsc_bridge.install.after_install"
after_migrate = "dsc_bridge.install.after_migrate"
