# Changelog

## 1.0.0 — 2026-11-14

First public release.

- Sign with DSC on configurable document types (form and print page), signed PDF attached to the document.
- DSC Bridge Settings (document types, defaults, connector URL) and DSC Sign Log.
- Connector 1.0.0: PKCS#11 (any USB token), PAdES signatures with pyHanko, Adobe-style stamp on every copy's
  "Authorised Signatory" box or a fixed box, status page, configurable allowed origins and stamp labels.
- Kits: Windows one-click (embedded Python), Mac (venv + LaunchAgent).
