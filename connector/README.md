# DSC Bridge Connector

The small program that signs on the user's own computer. The ERP's **Sign with DSC** button (DSC Bridge app for
Frappe / ERPNext) sends it the document's PDF; it signs the PDF with the DSC USB token plugged into this computer
and sends the signed PDF back; the ERP attaches it. The private key never leaves the token; the PIN is used once per
signing and is never stored or sent anywhere. It listens on `http://127.0.0.1:47831` only: no other computer can
reach it.

Any DSC token works: ePass2003, HYP2003 (HyperPKI), ProxKey / WatchData, mToken, SafeNet, TrustKey, Gemalto and
others. The connector talks to the token through PKCS#11 (the interface every token driver provides), picks the
driver that actually sees the plugged-in token and reads the certificate off the token each time, so a new, renewed
or other-company DSC needs nothing here.

## Windows 10/11 (one-click kit)

1. The token's own driver must be on the PC. It already is wherever that DSC is used for GST, Income Tax or MCA
   filing; otherwise install it from the token's CD drive or the token maker's website. Plug in the token.
2. Download `DSC_Bridge_Connector_Windows_<version>.zip`, right-click → **Extract All** → open the folder →
   double-click **install.bat** (if Windows asks "Do you want to run this file?" → **Run**).
3. The browser opens `http://127.0.0.1:47831/`: it shows the token and the certificate name and validity.
4. In the ERP, click **Sign with DSC** on a submitted document. The first time, Chrome asks to allow "local
   network" access → **Allow**.

It installs into `%LOCALAPPDATA%\DSCBridge` (no admin rights needed) and starts with Windows. Nothing else to
install: Python and the signing libraries are inside the zip. A newer kit: run its `install.bat` again.

| File | What |
|---|---|
| `install.bat` | one-time install (copies itself to `%LOCALAPPDATA%\DSCBridge`, start with Windows, opens the status page) |
| `start.vbs` / `stop.bat` | start (hidden) / stop |
| `uninstall.bat` | stop it and take it out of start-up |
| `connector.py` | the connector; `python\` + `lib\` = the Python and libraries it runs on |
| `config.json` | made on first run, see below |
| `connector.log` | log of every signing and error (never the PIN) |

## Mac

1. Install the token's **Mac driver** from the token maker (for HYP2003 / ePass2003 the Feitian or Hypersecu
   driver; for SafeNet the SafeNet Authentication Client; for ProxKey the WatchData driver). **Restart the Mac after
   installing a Feitian / Hypersecu driver**: it needs a system setting that only takes effect after a restart;
   without it the token is read but signing fails. If macOS says the token's disk is not readable, click
   **Ignore** (never Initialise): that disk holds the Windows driver only.
2. Download `DSC_Bridge_Connector_Mac_<version>.zip`, unzip, put the folder anywhere (for example Documents) and
   double-click **install.command** (first time: right-click → Open → Open). It makes a Python environment inside
   the folder and starts the connector with the Mac. Python 3 is needed (https://www.python.org/downloads/macos/).
3. Open `http://127.0.0.1:47831/` in Chrome to check. Do not move the folder afterwards (run install.command again
   if you do).

`start.command` / `stop.command` / `uninstall.command` do what their names say.

## Linux

```
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python connector.py
```
Set `pkcs11_lib` in `config.json` to the token's `.so` when it is not found by itself (OpenSC:
`/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so`).

## config.json

Written next to the connector on the first run.

| Key | Default | Meaning |
|---|---|---|
| `port` | `47831` | the local port; change it in DSC Bridge Settings too |
| `pkcs11_lib` | `""` | path of the token driver's PKCS#11 library; `""` = find it by itself |
| `token_label` | `""` | which token to use when several are plugged in; `""` = the first that holds a certificate |
| `allowed_origins` | `["*"]` | the ERP sites that may call the connector, e.g. `["https://erp.example.com"]`; `"*"` = any site |
| `stamp_box` | `"auto"` | where the stamp goes: `"auto"` = the box above the `stamp_labels` text on every page that has it; or a fixed `[x1, y1, x2, y2]` in PDF points from the bottom-left |
| `stamp_labels` | `["Authorised Signatory", "Authorized Signatory"]` | the words under the signature box on your print |
| `default_reason` / `default_location` | `"Digitally signed"` / `""` | used when the ERP sends none |
| `log_file` | `connector.log` | the log |

Environment variables for tests and special setups: `DSC_CONFIG`, `DSC_PORT`, `DSC_PKCS11_LIB`, `DSC_LOG`,
`DSC_BIND` (bind address; keep the default `127.0.0.1` on any real computer).

## Endpoints

| | |
|---|---|
| `GET /` | status page for people |
| `GET /status` | JSON: `ok`, `version`, `os`, `lib`, `token {label, manufacturer, model, serial}`, `cert {cn, org, issuer, serial, valid_from, valid_to, expired}`, `error` |
| `POST /sign` | body = PDF; headers `X-Pin` (required), `X-Reason`, `X-Location`, `X-Field-Name`, `X-File-Name`; reply = signed PDF, headers `X-Signer`, `X-Signer-Info` (JSON). 401 wrong PIN, 503 token / driver problem, 400 not a PDF |

## If something does not work

- **"DSC token driver (PKCS#11 library) not found"**: install the token's driver, then start the connector again. A
  driver in an unusual place: its full path in `config.json` → `pkcs11_lib`.
- **"DSC token not found" / "Token could not be read"**: take the token out, plug it in again, retry.
- **"Wrong PIN" / "PIN is locked"**: the token's PIN. A locked PIN is unlocked with the token maker's utility only.
- **"The DSC Bridge Connector is not running"**: start it (Windows `start.vbs`, Mac `start.command`) or restart.
- Signing fails right after a Mac driver install: restart the Mac.
- Anything else: `connector.log`.

## Tests

`pytest connector/tests` needs no token. `connector/tests/softhsm/` runs the whole signing against a software token
(SoftHSM) in Docker: `docker build -t dscbridge-softhsm -f connector/tests/softhsm/Dockerfile connector` then
`docker run --rm -v "$PWD/connector:/app" dscbridge-softhsm bash tests/softhsm/run_sign_test.sh`.

## Building the kits

`build_kits.sh` makes the release zips; see the comment at its top for the Windows parts (embeddable Python 3.11
+ the wheels of `requirements-kit.txt`).
