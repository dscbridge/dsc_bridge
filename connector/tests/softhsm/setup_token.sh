#!/bin/bash
# Test only: a SoftHSM token holding a self-signed "DSC BRIDGE TEST SIGNER" certificate. PIN = $DSC_TEST_PIN
# (default 123456). It is a plain software file, nothing like a real DSC - it only lets the signing flow run.
set -e
PIN="${DSC_TEST_PIN:-123456}"
M="${SOFTHSM_LIB:-/usr/lib/softhsm/libsofthsm2.so}"
LABEL="DSC BRIDGE TEST"
if [ -z "$SOFTHSM2_CONF" ] && [ ! -w /var/lib/softhsm/tokens ]; then
  # not root (CI runner): keep the token in a folder of our own
  mkdir -p /tmp/dscbridge-softhsm-tokens
  echo "directories.tokendir = /tmp/dscbridge-softhsm-tokens" > /tmp/dscbridge-softhsm2.conf
  export SOFTHSM2_CONF=/tmp/dscbridge-softhsm2.conf
fi
if ! softhsm2-util --show-slots 2>/dev/null | grep -q "$LABEL"; then
  softhsm2-util --init-token --free --label "$LABEL" --so-pin "$PIN" --pin "$PIN" >/dev/null
  T=$(mktemp -d)
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/key.pem" -out "$T/cert.pem" -days 400 \
    -subj "/C=IN/O=Example Traders/CN=DSC BRIDGE TEST SIGNER" -addext "keyUsage=digitalSignature,nonRepudiation" 2>/dev/null
  openssl pkcs8 -topk8 -nocrypt -in "$T/key.pem" -outform DER -out "$T/key.der"
  openssl x509 -in "$T/cert.pem" -outform DER -out "$T/cert.der"
  pkcs11-tool --module "$M" --login --pin "$PIN" --write-object "$T/key.der" --type privkey --id 01 --label dsc >/dev/null
  pkcs11-tool --module "$M" --login --pin "$PIN" --write-object "$T/cert.der" --type cert --id 01 --label dsc >/dev/null
  rm -rf "$T"
fi
echo "test token ready ($LABEL)"
