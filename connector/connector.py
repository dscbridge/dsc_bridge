#!/usr/bin/env python3
"""DSC Bridge Connector.

A small program that runs on the user's own computer. The ERP's "Sign with DSC" button (the DSC Bridge app for
Frappe / ERPNext) sends it the document's PDF; it signs the PDF with the DSC USB token plugged into THIS computer and
sends the signed PDF back. The ERP then attaches it to the document. The token's private key never leaves the token;
the PIN is used once per signing and never stored or sent anywhere.

Universal: it talks to the token through PKCS#11, the standard interface every DSC token driver provides (ePass2003,
ProxKey / WatchData, mToken, SafeNet, HYP2003, TrustKey, ...). The certificate is read off the token every time, so
a new or renewed DSC needs nothing here. A token brand whose driver sits in an unusual place only needs its PKCS#11
library path in config.json.

Endpoints (127.0.0.1 only, never reachable from another machine):
  GET  /         -> a small status page for people
  GET  /status   -> token + certificate on the pendrive, as JSON (no PIN needed on most tokens)
  POST /sign     -> body = PDF bytes; headers X-Pin, X-Reason, X-Location, X-Field-Name; reply = signed PDF bytes
"""
import asyncio
import concurrent.futures
import datetime as dt
import io
import itertools
import json
import logging
import os
import platform
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
CONFIG_PATH = os.environ.get("DSC_CONFIG", os.path.join(HERE, "config.json"))

DEFAULT_CONFIG = {
    "port": 47831,
    # "" = find the token driver by itself (see KNOWN_LIBS); a path here wins.
    "pkcs11_lib": "",
    # which token to use when more than one is plugged in ("" = the first one that holds a certificate)
    "token_label": "",
    # the ERP sites that may call this connector: a list of origins such as ["https://erp.example.com"], or ["*"]
    # for any site (the PIN is still asked for every signing and only this computer can reach the connector)
    "allowed_origins": ["*"],
    # where the signature stamp goes, in PDF points from the bottom-left corner.
    # "auto" = on every page that carries one of stamp_labels (each copy of an invoice, not an e-Way bill page after
    # it), in the box above that label; a print without the label: bottom right of the last page.
    # Or a fixed [x1, y1, x2, y2] on those same pages.
    "stamp_box": "auto",
    # the words under the signature box on the print (letters only are compared, case does not matter)
    "stamp_labels": ["Authorised Signatory", "Authorized Signatory"],
    "default_reason": "Digitally signed",
    "default_location": "",
    "log_file": os.path.join(HERE, "connector.log"),
}

# PKCS#11 driver files shipped by the common Indian DSC tokens (plus OpenSC and SoftHSM for tests)
KNOWN_LIBS = {
    "Windows": [
        r"C:\Windows\System32\eps2003csp11.dll",          # ePass2003
        r"C:\Windows\System32\eps2003csp11v2.dll",
        r"C:\Windows\System32\ShuttleCsp11_3003.dll",     # ePass3003
        r"C:\Windows\System32\wdpkcs.dll",                # ProxKey / WatchData
        r"C:\Windows\System32\SignatureP11.dll",
        r"C:\Windows\System32\eTPKCS11.dll",              # SafeNet eToken
        r"C:\Windows\System32\CryptoIDA_pkcs11.dll",      # mToken CryptoID
        r"C:\Windows\System32\mtoken_pkcs11.dll",
        r"C:\Windows\System32\HYP2003_PKCS11.dll",        # Hyp2003
        r"C:\Windows\System32\TRUSTKEYP11_ND_v34.dll",    # TrustKey
        r"C:\Windows\System32\aetpkss1.dll",              # Aladdin / Gemalto
        r"C:\Program Files\OpenSC Project\OpenSC\pkcs11\opensc-pkcs11.dll",
        r"C:\Program Files (x86)\OpenSC Project\OpenSC\pkcs11\opensc-pkcs11.dll",
    ],
    "Linux": [
        "/usr/lib/softhsm/libsofthsm2.so",
        "/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so",
        "/usr/lib/aarch64-linux-gnu/softhsm/libsofthsm2.so",
        "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
        "/usr/lib/opensc-pkcs11.so",
    ],
    "Darwin": [
        # Mac drivers of the DSC tokens: the token's own Mac driver, else OpenSC
        "/usr/local/lib/libcastle.1.0.0.dylib",            # ePass2003 / Feitian family (Mac)
        "/usr/local/lib/libcastle_v2.1.0.0.dylib",
        "/usr/local/lib/libeTPkcs11.dylib",                # SafeNet eToken (Mac)
        "/usr/local/lib/libwdpkcs.dylib",                  # ProxKey / WatchData (Mac)
        "/Library/OpenSC/lib/opensc-pkcs11.so",            # OpenSC (also reads HYP2003 / ePass2003)
        "/usr/local/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/softhsm/libsofthsm2.so",        # tests only
        "/usr/local/lib/softhsm/libsofthsm2.so",
    ],
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    if os.environ.get("DSC_PKCS11_LIB"):
        cfg["pkcs11_lib"] = os.environ["DSC_PKCS11_LIB"]
    if os.environ.get("DSC_PORT"):
        cfg["port"] = int(os.environ["DSC_PORT"])
    if os.environ.get("DSC_LOG"):
        cfg["log_file"] = os.environ["DSC_LOG"]
    return cfg


CFG = load_config()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    # pythonw (the hidden start on Windows) has no console: then the log file only
    handlers=[logging.FileHandler(CFG["log_file"], encoding="utf-8")] + ([logging.StreamHandler(sys.stdout)] if sys.stdout else []),
)
log = logging.getLogger("dsc")
LOCK = threading.Lock()   # one signing at a time: a token has one session


# ── PKCS#11 ──────────────────────────────────────────────────────────────────
def candidate_libs():
    """Every token driver (PKCS#11 library) on this computer, the known ones first; config.json's pkcs11_lib wins."""
    if CFG.get("pkcs11_lib"):
        return [CFG["pkcs11_lib"]] if os.path.exists(CFG["pkcs11_lib"]) else []
    out = [p for p in KNOWN_LIBS.get(platform.system(), []) if os.path.exists(p)]
    if platform.system() == "Windows":
        # any other token driver that follows the usual naming (…pkcs11….dll, eps2003csp11….dll, …P11.dll)
        dirs = (r"C:\Windows\System32",)
        ok = lambda low: low.endswith(".dll") and ("pkcs11" in low or "csp11" in low or low.endswith(("p11.dll", "p11v2.dll")))
    elif platform.system() == "Darwin":
        dirs = ("/usr/local/lib", "/Library/OpenSC/lib", "/opt/homebrew/lib")
        ok = lambda low: "pkcs" in low and low.endswith((".dylib", ".so")) and "softhsm" not in low
    else:
        dirs, ok = (), None
    for d in dirs:
        try:
            for n in sorted(os.listdir(d)):
                p = os.path.join(d, n)
                if ok(n.lower()) and p not in out:
                    out.append(p)
        except OSError:
            pass
    return out


_LAST_LIB = [None]


def find_lib():
    """The driver to use. A PC often has the drivers of several token brands (ePass, ProxKey, mToken …), so take the
    one that actually sees a plugged-in token (before, the first driver on the list won even when the
    pendrive was another brand); with no token plugged in, the first driver there is."""
    import pkcs11
    libs = candidate_libs()
    if _LAST_LIB[0] in libs:
        libs.remove(_LAST_LIB[0])
        libs.insert(0, _LAST_LIB[0])
    for p in libs:
        try:
            if list(pkcs11.lib(p).get_tokens()):
                _LAST_LIB[0] = p
                return p
        except Exception:
            continue
    return libs[0] if libs else None


def cert_info(x509):
    from cryptography.x509.oid import NameOID

    def one(name, oid):
        try:
            return name.get_attributes_for_oid(oid)[0].value
        except (IndexError, ValueError):
            return ""
    nb = getattr(x509, "not_valid_before_utc", None) or x509.not_valid_before
    na = getattr(x509, "not_valid_after_utc", None) or x509.not_valid_after
    return {
        "cn": one(x509.subject, NameOID.COMMON_NAME),
        "org": one(x509.subject, NameOID.ORGANIZATION_NAME),
        "issuer": one(x509.issuer, NameOID.COMMON_NAME),
        "serial": format(x509.serial_number, "x"),
        "valid_from": nb.strftime("%Y-%m-%d"),
        "valid_to": na.strftime("%Y-%m-%d"),
        "expired": na.replace(tzinfo=None) < dt.datetime.utcnow(),
    }


def open_token(lib_path):
    import pkcs11
    lib = pkcs11.lib(lib_path)
    tokens = list(lib.get_tokens())
    want = (CFG.get("token_label") or "").strip()
    if want:
        tokens = [t for t in tokens if (t.label or "").strip() == want]
    if not tokens:
        raise LookupError("DSC token not found. Plug in the DSC pendrive and try again.")
    return lib, tokens


def read_certs(session):
    """Every X.509 certificate on the token: [(CKA_ID bytes, x509, label)]."""
    import pkcs11
    from pkcs11 import Attribute, ObjectClass
    from cryptography import x509
    out = []
    for obj in session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
        try:
            der = obj[Attribute.VALUE]
            cert = x509.load_der_x509_certificate(bytes(der))
        except Exception:
            continue
        try:
            cid = bytes(obj[Attribute.ID] or b"")
        except Exception:
            cid = b""
        try:
            label = obj[Attribute.LABEL] or ""
        except Exception:
            label = ""
        out.append((cid, cert, label))
    return out


def pick_signing_cert(certs, private_ids=None):
    """The user's own signing certificate: has a private key on the token (when known), not a CA, newest valid first."""
    from cryptography.x509.oid import ExtensionOID
    def is_ca(c):
        try:
            return bool(c.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca)
        except Exception:
            return False
    def can_sign(c):
        # Indian class-3 DSCs hold a signing + an encryption certificate with the same name and dates (seen on
        # HYP2003): the encryption one (key encipherment only) must never sign.
        try:
            ku = c.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
            return bool(ku.digital_signature or ku.content_commitment)
        except Exception:
            return True
    cands = [t for t in certs if not is_ca(t[1])]
    signers = [t for t in cands if can_sign(t[1])]
    if signers:
        cands = signers
    if private_ids:
        with_key = [t for t in cands if t[0] and t[0] in private_ids]
        if with_key:
            cands = with_key
    if not cands:
        cands = list(certs)
    cands.sort(key=lambda t: (cert_info(t[1])["expired"], -(getattr(t[1], "not_valid_after_utc", None) or t[1].not_valid_after).timestamp()))
    return cands[0] if cands else None


def status():
    lib_path = find_lib()
    out = {"ok": False, "version": VERSION, "os": platform.system(), "lib": lib_path, "token": None, "cert": None, "error": None}
    if not lib_path:
        out["error"] = "DSC token driver (PKCS#11 library) not found on this computer. Install the token's driver or set pkcs11_lib in config.json."
        return out
    try:
        _lib, tokens = open_token(lib_path)
        tok = tokens[0]
        def g(*names):
            for n in names:
                v = getattr(tok, n, None)
                if v:
                    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
            return ""
        out["token"] = {"label": g("label").strip(), "manufacturer": g("manufacturer_id", "manufacturer").strip(),
                        "model": g("model").strip(), "serial": g("serial", "serial_number").strip()}
        with tok.open() as session:      # no PIN: certificates are public objects on most tokens
            certs = read_certs(session)
        chosen = pick_signing_cert(certs)
        if chosen:
            out["cert"] = cert_info(chosen[1])
            out["cert"]["label"] = chosen[2]
            out["cert_count"] = len(certs)
            out["ok"] = not out["cert"]["expired"]
            if out["cert"]["expired"]:
                out["error"] = "The certificate on this DSC has expired (%s)." % out["cert"]["valid_to"]
        else:
            out["ok"] = True   # token there; certificate may need the PIN to be read
            out["error"] = "No certificate could be read without the PIN; signing will read it with the PIN."
    except LookupError as e:
        out["error"] = str(e)
    except Exception as e:
        log.exception("status failed")
        out["error"] = ("Token could not be read (%s). Take the DSC pendrive out, plug it in again and retry."
                        % (str(e) or e.__class__.__name__))
    return out


def sign_pdf(pdf_bytes, pin, reason, location, field_name):
    import pkcs11
    from pkcs11 import Attribute, ObjectClass
    from pyhanko.sign import signers, fields
    from pyhanko.sign.pkcs11 import PKCS11Signer
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.layout import BoxConstraints
    from pyhanko.pdf_utils.reader import PdfFileReader

    lib_path = find_lib()
    if not lib_path:
        raise LookupError("DSC token driver (PKCS#11 library) not found on this computer.")
    _lib, tokens = open_token(lib_path)
    tok = tokens[0]
    try:
        try:
            # read-write session first: some token drivers will not sign in a read-only one
            session = tok.open(rw=True, user_pin=pin)
        except (pkcs11.exceptions.PinIncorrect, pkcs11.exceptions.PinLocked):
            raise
        except pkcs11.exceptions.PKCS11Error:
            session = tok.open(user_pin=pin)
    except pkcs11.exceptions.PinIncorrect:
        raise PermissionError("Wrong PIN.")
    except pkcs11.exceptions.PinLocked:
        raise PermissionError("The DSC PIN is locked. Unlock it with the token's own utility.")
    with session:
        certs = read_certs(session)
        priv_ids = set()
        for obj in session.get_objects({Attribute.CLASS: ObjectClass.PRIVATE_KEY}):
            try:
                priv_ids.add(bytes(obj[Attribute.ID] or b""))
            except Exception:
                pass
        chosen = pick_signing_cert(certs, priv_ids)
        if not chosen:
            raise LookupError("No signing certificate found on this DSC token.")
        cid, cert, label = chosen
        info = cert_info(cert)
        if info["expired"]:
            raise LookupError("The certificate on this DSC has expired (%s)." % info["valid_to"])
        others = [c for i, c, l in certs if (i, l) != (cid, label)]
        from asn1crypto import x509 as asn1x509
        ca_chain = [asn1x509.Certificate.load(c.public_bytes(encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.DER)) for c in others]
        kw = dict(ca_chain=ca_chain, embed_roots=True)
        if cid:
            kw.update(cert_id=cid, key_id=cid)
        else:
            kw.update(cert_label=label or None, key_label=label or None)
        meta = signers.PdfSignatureMetadata(field_name=field_name, reason=reason or None, location=location or None,
                                            md_algorithm="sha256")
        spots = sign_spots(PdfFileReader(io.BytesIO(pdf_bytes), strict=False))
        log.info("stamp on page(s) %s", [ix + 1 for ix, _ in spots])
        style = bill_stamp_style(info["cn"], stamp_details(cert, reason, location, dt.datetime.now().astimezone()))
        # Indian tokens under the CCA rule ask for the PIN again for every signature (CKA_ALWAYS_AUTHENTICATE on the
        # key): then the PIN goes once more right after C_SignInit (context-specific login). The key's flags go to
        # the log (never the PIN) so a token that still refuses shows why.
        always_auth = False
        find = {Attribute.CLASS: ObjectClass.PRIVATE_KEY}
        find.update({Attribute.ID: cid} if cid else {Attribute.LABEL: label})
        for key in session.get_objects(find):
            flags = {}
            for a in ("ALWAYS_AUTHENTICATE", "SIGN", "SIGN_RECOVER", "DECRYPT", "SENSITIVE", "EXTRACTABLE", "KEY_TYPE"):
                try:
                    flags[a] = key[getattr(Attribute, a)]
                except Exception as e:
                    flags[a] = "? %s" % e.__class__.__name__
            log.info("signing key %s: %s (rw session %s)", label or cid.hex(), flags, session.rw)
            always_auth = always_auth or flags.get("ALWAYS_AUTHENTICATE") is True
        # HYP2003 on Mac: the Feitian driver fails "hash + sign on the token" (CKM_SHA256_RSA_PKCS) with
        # CKR_DEVICE_ERROR. Hashing here and letting the token do only the key step (CKM_RSA_PKCS, as Windows / Adobe
        # do) works on every token and gives the same signature, so it goes first; the on-token hash is the fallback.
        failed = []
        for again in ((True, False) if always_auth else (False, True)):
            for raw in (True, False):
                signer = PKCS11Signer(session, use_raw_mechanism=raw, base_sign_kwargs={"pin": pin} if again else None, **kw)
                w = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
                # the signature field itself sits on the first copy; the other copies carry the same stamp as page
                # content, added before signing, so the signature covers them too
                for ix, box in spots[1:]:
                    size = BoxConstraints(width=box[2] - box[0], height=box[3] - box[1])
                    style.create_stamp(w, size, {}).apply(ix, box[0], box[1])
                fields.append_signature_field(w, fields.SigFieldSpec(sig_field_name=field_name, on_page=spots[0][0], box=spots[0][1]))
                out = io.BytesIO()
                way = ("hash here" if raw else "hash on token") + (" + PIN again" if again else "")
                try:
                    run_on_this_thread(signers.PdfSigner(meta, signer=signer, stamp_style=style).async_sign_pdf(w, output=out))
                except pkcs11.exceptions.PKCS11Error as e:
                    failed.append("%s: %s" % (way, str(e) or e.__class__.__name__))
                    log.warning("token refused to sign (%s): %r", way, e)
                    continue
                log.info("signed (%s)", way)
                return out.getvalue(), info
        raise RuntimeError("the DSC token refused to sign (%s)" % "; ".join(failed))


class _ThisThread(concurrent.futures.ThreadPoolExecutor):
    """An 'executor' that runs the job at once on the calling thread."""
    def submit(self, fn, *args, **kwargs):
        f = concurrent.futures.Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as e:
            f.set_exception(e)
        return f


def run_on_this_thread(coro):
    """pyHanko hands the token calls (find key, C_Sign) to worker threads. Some token drivers (Feitian / Hypersecu on
    Mac) tie the card connection to the thread that opened the session and fail C_Sign from another
    thread with CKR_DEVICE_ERROR, so every token call here stays on the thread that logged in."""
    loop = asyncio.new_event_loop()
    loop.set_default_executor(_ThisThread(max_workers=1))
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── The stamp on the bill ────────────────────────────────────────────────────
# Helvetica character widths (1/1000 em) for ASCII 32-126, to fit the text in the box
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]


def text_width(s, size):
    return sum(_HELV[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in s) * size / 1000.0


def wrap_text(s, size, width):
    lines, cur = [], ""
    for word in s.split():
        trial = (cur + " " + word).strip()
        if cur and text_width(trial, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur] if cur else lines


def fit_name(name, width, height):
    """The signer's name as big as the box allows: (font size, lines), broken where the widest line is narrowest."""
    words = name.split() or [""]
    best = None
    for n in range(1, min(len(words), 4) + 1):
        for breaks in itertools.combinations(range(1, len(words)), n - 1):
            cuts = (0,) + breaks + (len(words),)
            lines = [" ".join(words[a:b]) for a, b in zip(cuts, cuts[1:])]
            size = min(width / max(text_width(ln, 1) or 1 for ln in lines), height / (n * 1.08), 26)
            if best is None or size > best[0]:
                best = (size, lines)
    return best


def fit_details(paragraphs, width, height):
    """The small text: the biggest font (7 pt at most) at which every line and the whole block fit."""
    size = 7.0
    while True:
        lines = [ln for p in paragraphs for ln in wrap_text(p, size, width)]
        if size <= 3.5 or (len(lines) * size * 1.18 <= height and all(text_width(ln, size) <= width for ln in lines)):
            return size, lines
        size -= 0.1


def _pdf_string(s):
    b = s.encode("cp1252", "replace")
    return b"(" + b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def stamp_commands(name, details, width, height):
    """Left: the name, big. Right: the details, small. Both centred on the height, no border."""
    name_w = width * 0.44
    detail_x = name_w + width * 0.03
    out = [b"BT 0 g"]
    for x, (size, lines), leading in (
        (0, fit_name(name, name_w, height), 1.08),
        (detail_x, fit_details(details, width - detail_x, height), 1.18),
    ):
        y = (height + (len(lines) - 1) * leading * size - 0.718 * size) / 2
        for ln in lines:
            out.append(b"/F1 %.2f Tf 1 0 0 1 %.2f %.2f Tm %s Tj" % (size, x, y, _pdf_string(ln)))
            y -= leading * size
    out.append(b"ET")
    return b" ".join(out)


def stamp_details(cert, reason, location, when):
    """The lines an Adobe signature shows: signer, DN, reason, location, date."""
    from cryptography.x509.oid import NameOID

    def one(oid):
        vals = cert.subject.get_attributes_for_oid(oid)
        return vals[0].value if vals else ""
    dn = " ".join("%s=%s" % (k, one(oid)) for k, oid in (
        ("cn", NameOID.COMMON_NAME), ("c", NameOID.COUNTRY_NAME), ("l", NameOID.LOCALITY_NAME),
        ("o", NameOID.ORGANIZATION_NAME), ("ou", NameOID.ORGANIZATIONAL_UNIT_NAME), ("e", NameOID.EMAIL_ADDRESS),
    ) if one(oid))
    off = when.strftime("%z")
    return ["Digitally signed by %s" % one(NameOID.COMMON_NAME), "DN: %s" % dn, "Reason: %s" % (reason or ""),
            "Location: %s" % (location or ""), "Date: %s%s:%s" % (when.strftime("%Y-%m-%d %H:%M"), off[:3], off[3:5])]


def bill_stamp_style(name, details):
    """A pyHanko stamp style that draws stamp_commands(), for the signature field and for the page stamps."""
    from pyhanko.pdf_utils import content, generic
    from pyhanko.pdf_utils.generic import pdf_name
    from pyhanko.stamp.base import BaseStamp, BaseStampStyle

    class BillStamp(BaseStamp):
        def _render_inner_content(self):
            self.set_resource(category=content.ResourceType.FONT, name=pdf_name("/F1"), value=generic.DictionaryObject({
                pdf_name("/Type"): pdf_name("/Font"), pdf_name("/Subtype"): pdf_name("/Type1"),
                pdf_name("/BaseFont"): pdf_name("/Helvetica"), pdf_name("/Encoding"): pdf_name("/WinAnsiEncoding"),
            }))
            return [stamp_commands(name, details, float(self.box.width), float(self.box.height))]

    class BillStampStyle(BaseStampStyle):
        def create_stamp(self, writer, box, text_params):
            return BillStamp(writer=writer, style=self, box=box)

    return BillStampStyle(border_width=0)


# Just enough of a PDF content-stream reader to find a label on the page (the ERP's wkhtmltopdf draws glyph by glyph)
_PDF_TOKEN = re.compile(rb"<[0-9A-Fa-f\s]*>|\((?:\\.|[^\\()])*\)|/[^\s/<>\[\]()]+|\[|\]|[-+]?(?:\d+\.?\d*|\.\d+)|[A-Za-z'\"][A-Za-z0-9*]*")
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _obj(x):
    return x.get_object() if hasattr(x, "get_object") else x


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def _inherited(page, key):
    while page is not None:
        if key in page:
            return _obj(page[key])
        page = _obj(page["/Parent"]) if "/Parent" in page else None
    return None


def _font_map(font):
    """(bytes per character code, {code: text}) of a page font, from its /ToUnicode."""
    cmap = {}

    def text(hexa):
        return bytes.fromhex(hexa.decode()).decode("utf-16-be", "ignore")
    if "/ToUnicode" in font:
        data = _obj(font["/ToUnicode"]).data
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
            for code, val in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
                cmap[int(code, 16)] = text(val)
        for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
            for lo, hi, val in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                first = text(val)
                for i, code in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
                    cmap[code] = first[:-1] + chr(ord(first[-1]) + i) if first else ""
            for lo, vals in re.findall(rb"<([0-9A-Fa-f]+)>\s*<[0-9A-Fa-f]+>\s*\[(.*?)\]", block, re.S):
                for i, val in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", vals)):
                    cmap[int(lo, 16) + i] = text(val)
    return (2 if font.get("/Subtype") == "/Type0" else 1), cmap


def page_glyphs(page):
    """The text on a page in drawing order: [(text, x, y, size)], x / y / size in PDF points."""
    fonts = _obj((_inherited(page, "/Resources") or {}).get("/Font")) or {}
    contents = _obj(page["/Contents"])
    data = b"\n".join(_obj(c).data for c in (contents if isinstance(contents, list) else [contents]))
    maps, out, args, saved = {}, [], [], []
    ctm = tm = tlm = _IDENTITY
    fmap, size = None, 0.0

    def show(raw):
        nonlocal tm
        if not fmap or not isinstance(raw, bytes):
            return
        n, cmap = fmap
        for i in range(0, len(raw) - n + 1, n):
            code = int.from_bytes(raw[i:i + n], "big")
            m = _mul(tm, ctm)
            out.append((cmap.get(code, chr(code) if n == 1 else ""), m[4], m[5], abs(size * m[3])))
            tm = _mul((1.0, 0.0, 0.0, 1.0, size * 0.5, 0.0), tm)

    for match in _PDF_TOKEN.finditer(data):
        tok = match.group()
        first = tok[:1]
        if first == b"<":
            hexa = re.sub(rb"\s", b"", tok[1:-1]).decode()
            args.append(bytes.fromhex(hexa + "0" * (len(hexa) % 2)))
        elif first == b"(":
            args.append(re.sub(rb"\\(.)", rb"\1", tok[1:-1], flags=re.S))
        elif first == b"/":
            args.append(tok.decode("latin1"))
        elif first == b"[":
            args.append("[")
        elif first == b"]":
            at = len(args) - 1 - args[::-1].index("[") if "[" in args else 0
            args[at:] = [args[at + 1:]]
        elif first in b"+-.0123456789":
            args.append(float(tok))
        else:
            op = tok.decode("latin1")
            nums = [a for a in args if isinstance(a, float)]
            if op == "q":
                saved.append(ctm)
            elif op == "Q":
                ctm = saved.pop() if saved else ctm
            elif op == "cm" and len(nums) >= 6:
                ctm = _mul(tuple(nums[-6:]), ctm)
            elif op == "BT":
                tm = tlm = _IDENTITY
            elif op == "Tm" and len(nums) >= 6:
                tm = tlm = tuple(nums[-6:])
            elif op in ("Td", "TD") and len(nums) >= 2:
                tm = tlm = _mul((1.0, 0.0, 0.0, 1.0, nums[-2], nums[-1]), tlm)
            elif op == "Tf" and len(args) >= 2:
                name, size = args[-2], args[-1]
                if name not in maps:
                    maps[name] = _font_map(_obj(fonts[name])) if name in fonts else None
                fmap = maps[name]
            elif op == "Tj" and args:
                show(args[-1])
            elif op == "TJ" and args and isinstance(args[-1], list):
                for part in args[-1]:
                    show(part)
            args = []
    return out


STAMP_WIDTH = 232


def stamp_labels():
    """config stamp_labels as letters-only lower case, the way the page text is compared."""
    out = []
    for label in CFG.get("stamp_labels") or DEFAULT_CONFIG["stamp_labels"]:
        key = re.sub(r"[^a-z]", "", str(label).lower())
        if key and key not in out:
            out.append(key)
    return out


def label_box(page):
    """The stamp's box on a page with "Authorised Signatory": over the label, under "For <company>"; None without it."""
    glyphs = page_glyphs(page)
    letters = [(ch.lower(), g) for g in glyphs for ch in g[0] if ch.isalpha()]
    text = "".join(ch for ch, _ in letters)
    for label in stamp_labels():
        at = text.rfind(label)
        if at >= 0:
            break
    else:
        return None
    first, last = letters[at][1], letters[min(at + len(label), len(letters) - 1)][1]
    x2 = last[1] + last[3] * 0.55
    x1 = max(x2 - STAMP_WIDTH, 0)
    floor = first[2] + first[3] * 0.85 + 1
    above = [g for g in glyphs if g[0].strip() and x1 <= g[1] <= x2 + 2 and floor < g[2] < floor + 90]
    if above:
        lowest = min(above, key=lambda g: g[2])
        ceil = lowest[2] - lowest[3] * 0.3 - 1
    else:
        ceil = floor + 60
    ceil = max(floor + 30, min(ceil, floor + 76))
    return (int(x1), int(floor), int(x2), int(ceil))


def sign_spots(reader):
    """Where the stamp goes: [(page index, box)]. Every page that carries the label (each copy of an invoice), never
    an e-Way bill page after them. A print without the label: bottom right of the last page."""
    count = int(reader.root["/Pages"]["/Count"])
    fixed = CFG.get("stamp_box")
    fixed = tuple(int(v) for v in fixed) if isinstance(fixed, (list, tuple)) and len(fixed) == 4 else None
    spots = []
    try:
        for ix in range(count):
            box = label_box(reader.find_page_for_modification(ix)[0].get_object())
            if box:
                spots.append((ix, fixed or box))
    except Exception:
        log.exception("could not search the PDF for the signatory label")
        spots = []
    if spots:
        return spots
    width = 595.0
    try:
        mb = _inherited(reader.find_page_for_modification(count - 1)[0].get_object(), "/MediaBox")
        width = float(mb[2]) - float(mb[0])
    except Exception:
        log.warning("page size not read, using A4")
    return [(count - 1, fixed or (int(width - 270), 44, int(width - 42), 104))]


# ── HTTP ─────────────────────────────────────────────────────────────────────
STATUS_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>DSC Bridge Connector</title>
<style>body{font-family:system-ui,Segoe UI,Helvetica,Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#222}
h1{font-size:20px}table{border-collapse:collapse}td{padding:4px 12px 4px 0;vertical-align:top}.ok{color:#1a7f37}.bad{color:#b42318}
code{background:#f3f3f3;padding:1px 4px;border-radius:3px}</style></head><body>
<h1>DSC Bridge Connector <span id="v"></span></h1>
<p id="state">Reading the token...</p>
<table id="t"></table>
<p style="color:#666;font-size:13px">This page is served by the connector on this computer only (127.0.0.1). In the ERP, open a
document and click <b>Sign with DSC</b>. Log file: <code>connector.log</code> next to the connector.</p>
<script>
fetch("/status",{cache:"no-store"}).then(r=>r.json()).then(s=>{
 document.getElementById("v").textContent="v"+(s.version||"");
 var st=document.getElementById("state");
 st.textContent=s.ok?"Ready: the token and its certificate were read.":(s.error||"Not ready.");
 st.className=s.ok?"ok":"bad";
 var rows=[["Operating system",s.os],["Token driver",s.lib||"not found"],
  ["Token",s.token?[s.token.label,s.token.model,s.token.serial].filter(Boolean).join(" / "):"not plugged in"],
  ["Certificate",s.cert?s.cert.cn+(s.cert.org?" ("+s.cert.org+")":""):"-"],
  ["Valid",s.cert?s.cert.valid_from+" to "+s.cert.valid_to:"-"],["Issuer",s.cert?s.cert.issuer:"-"]];
 document.getElementById("t").innerHTML=rows.map(r=>"<tr><td><b>"+r[0]+"</b></td><td>"+String(r[1]==null?"":r[1]).replace(/[<>&]/g,c=>({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]))+"</td></tr>").join("");
}).catch(()=>{document.getElementById("state").textContent="The connector did not answer.";});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "DSCBridge/" + VERSION

    def _origin_ok(self):
        o = self.headers.get("Origin", "")
        allowed = CFG.get("allowed_origins") or []
        if "*" in allowed:
            return o or "*"
        return o if o in allowed else None

    def _cors(self, origin):
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pin, X-Reason, X-Location, X-Field-Name, X-File-Name")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Expose-Headers", "X-Signer, X-Signer-Info, X-Error")
            self.send_header("Access-Control-Max-Age", "600")

    def _json(self, code, body, origin=None):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors(origin)
        self.end_headers()
        self.wfile.write(data)

    def _html(self, code, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        origin = self._origin_ok()
        self.send_response(204 if origin else 403)
        self._cors(origin)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        origin = self._origin_ok()
        if self.headers.get("Origin") and not origin:
            self._json(403, {"ok": False, "error": "This site is not allowed to use the DSC connector."})
            return
        path = self.path.split("?")[0]
        if path == "/":
            self._html(200, STATUS_PAGE)
        elif path == "/status":
            with LOCK:
                self._json(200, status(), origin)
        else:
            self._json(404, {"ok": False, "error": "unknown path"}, origin)

    def do_POST(self):
        origin = self._origin_ok()
        if not origin:
            self._json(403, {"ok": False, "error": "This site is not allowed to use the DSC connector."})
            return
        if self.path.split("?")[0] != "/sign":
            self._json(404, {"ok": False, "error": "unknown path"}, origin)
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 50 * 1024 * 1024:
            self._json(400, {"ok": False, "error": "No PDF received."}, origin)
            return
        pdf = self.rfile.read(n)
        if not pdf.startswith(b"%PDF"):
            self._json(400, {"ok": False, "error": "The file sent is not a PDF."}, origin)
            return
        pin = self.headers.get("X-Pin", "")
        if not pin:
            self._json(400, {"ok": False, "error": "DSC PIN is required."}, origin)
            return
        reason = self.headers.get("X-Reason") or CFG["default_reason"]
        location = self.headers.get("X-Location") or CFG["default_location"]
        field = (self.headers.get("X-Field-Name") or "DSCBridge").strip() or "DSCBridge"
        fname = self.headers.get("X-File-Name") or "document"
        t0 = time.time()
        try:
            with LOCK:
                signed, info = sign_pdf(pdf, pin, reason, location, field)
        except PermissionError as e:
            log.warning("sign refused (%s): %s", fname, e)
            self._json(401, {"ok": False, "error": str(e)}, origin)
            return
        except LookupError as e:
            log.warning("sign refused (%s): %s", fname, e)
            self._json(503, {"ok": False, "error": str(e)}, origin)
            return
        except Exception as e:
            log.error("sign failed (%s): %s\n%s", fname, e, traceback.format_exc())
            self._json(500, {"ok": False, "error": "Signing failed: %s" % (str(e) or e.__class__.__name__)}, origin)
            return
        finally:
            pin = None
        log.info("signed %s (%d -> %d bytes) as %s in %.1fs", fname, len(pdf), len(signed), info["cn"], time.time() - t0)
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(signed)))
        self.send_header("X-Signer", info["cn"].encode("ascii", "replace").decode())
        self.send_header("X-Signer-Info", json.dumps({"cn": info["cn"], "org": info["org"], "serial": info["serial"],
                                                      "valid_to": info["valid_to"], "version": VERSION}, ensure_ascii=True))
        self._cors(origin)
        self.end_headers()
        self.wfile.write(signed)

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def main():
    port = int(CFG["port"])
    # always loopback on a real PC; DSC_BIND=0.0.0.0 only for the Docker test (its port is mapped to the host's 127.0.0.1)
    srv = ThreadingHTTPServer((os.environ.get("DSC_BIND") or "127.0.0.1", port), Handler)
    log.info("DSC Bridge Connector %s on http://%s:%d (driver: %s)", VERSION, srv.server_address[0], port, find_lib() or "not found")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
