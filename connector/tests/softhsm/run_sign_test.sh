#!/bin/bash
# End to end: start the connector on the SoftHSM token, POST a PDF to /sign, validate the signed PDF.
# Runs in the softhsm Docker image or on any Linux with softhsm2 + opensc + requirements.txt installed.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
export DSC_TEST_PIN="${DSC_TEST_PIN:-123456}"
export DSC_PKCS11_LIB="${SOFTHSM_LIB:-/usr/lib/softhsm/libsofthsm2.so}"
export DSC_CONFIG="${DSC_CONFIG:-/tmp/dscbridge-test-config.json}"
export DSC_LOG="${DSC_LOG:-/tmp/dscbridge-test.log}"
export DSC_PORT="${DSC_PORT:-47899}"
if [ -z "$SOFTHSM2_CONF" ] && [ ! -w /var/lib/softhsm/tokens ]; then
  mkdir -p /tmp/dscbridge-softhsm-tokens
  echo "directories.tokendir = /tmp/dscbridge-softhsm-tokens" > /tmp/dscbridge-softhsm2.conf
  export SOFTHSM2_CONF=/tmp/dscbridge-softhsm2.conf
fi
bash "$HERE/setup_token.sh"
python "$HERE/../../connector.py" &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
H="python $HERE/dscb_http.py"
B="http://127.0.0.1:$DSC_PORT"
for i in $(seq 1 30); do $H GET "$B/status" >/dev/null 2>&1 && break; sleep 0.5; done
echo "--- /status"; $H GET "$B/status"; echo
$H GET "$B/status" | python -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] and d["cert"]["cn"]=="DSC BRIDGE TEST SIGNER", d'
python -c "
import sys; sys.path.insert(0, '$HERE/..')
from test_connector import minimal_pdf
open('/tmp/dscbridge-sample.pdf','wb').write(minimal_pdf([('For Example Traders', 420, 120, 9), ('Authorised Signatory', 430, 50, 9), ('Invoice INV-0001', 40, 780, 12)]))
"
echo "--- /sign"
code=$($H POST "$B/sign" /tmp/dscbridge-signed.pdf "Content-Type=application/pdf" "X-Pin=$DSC_TEST_PIN" "X-Reason=Tax Invoice" \
  "X-Location=Delhi" "X-File-Name=INV-0001" "Origin=https://erp.example.com" @/tmp/dscbridge-sample.pdf)
echo "HTTP $code"; test "$code" = "200"
python "$HERE/validate.py" /tmp/dscbridge-signed.pdf
echo "--- wrong PIN must be refused with 401"
code=$($H POST "$B/sign" /tmp/dscbridge-x.json "Content-Type=application/pdf" "X-Pin=000000" @/tmp/dscbridge-sample.pdf)
echo "HTTP $code"; test "$code" = "401"
echo "--- a non-PDF must be refused with 400"
code=$($H POST "$B/sign" /tmp/dscbridge-x.json "Content-Type=application/pdf" "X-Pin=$DSC_TEST_PIN" "=hello")
echo "HTTP $code"; test "$code" = "400"
echo "--- status page"
$H GET "$B/" | grep -q "DSC Bridge Connector"
echo "ALL SIGN TESTS PASSED"
