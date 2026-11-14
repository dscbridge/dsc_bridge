# Privacy Policy — DSC Bridge

*Last updated: 14 November 2026*

DSC Bridge is an app for Frappe / ERPNext plus a small connector program for the user's computer. This is what it
does with data.

**Data stays on your systems.** The app runs inside your own Frappe site. The connector runs on your users'
computers and listens on the local address only (`127.0.0.1`). Neither sends any data to the publisher of DSC
Bridge or to any third party. There is no telemetry, no usage reporting, no update check.

**What the app stores on your site:** the signed PDF, attached to the document as a private file, and a DSC Sign
Log entry (document, user, time, the certificate's name, organisation, serial number and validity, reason,
location, print format, file name and size, connector version). You can turn the log off in DSC Bridge Settings.
Site administrators control retention under your own data policies.

**What the connector handles:** the PDF it is asked to sign (in memory, not kept), the certificate read from the
token, and the token PIN, which is used once for that signing and never stored or written to the log. The
connector writes a log file on the user's computer (`connector.log`) with the time, file name, signer name and any
errors.

**Marketplace and support:** if you install DSC Bridge from the Frappe Cloud Marketplace, Frappe Cloud's own
privacy policy covers your account and billing. If you write to us for support, we use what you send only to help
you and do not share it.

**Changes** to this policy are published in this repository.
