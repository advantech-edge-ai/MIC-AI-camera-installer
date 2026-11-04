#!/bin/bash
#==============================================================================
# install_driver.sh <staged package dir> <install dir>
#
# The only part of the tool that runs as root (via pkexec / sudo). Copies an
# already downloaded, verified and extracted driver package into
# /opt/advantech/camera_framework/vendors/... and runs its installer, the same
# way Chris's online_mode.sh does:
#   install.sh -> install_binaries.sh -> apt-get install ./*.deb
# The vendor installer may reboot the machine when it finishes.
#==============================================================================
set -eo pipefail

VENDORS_DIR="/opt/advantech/camera_framework/vendors"

src="$1"
dest="$2"

die() { echo "[ERR ] $*" >&2; exit 2; }

[[ "${EUID}" -eq 0 ]] || die "must run as root"
[[ -n "${src}" && -d "${src}" ]] || die "package dir not found: ${src}"
case "${dest}" in
    "${VENDORS_DIR}"/*) ;;
    *) die "refusing install dir outside ${VENDORS_DIR}: ${dest}" ;;
esac
[[ "${dest}" != *"/../"* && "${dest}" != *"/.." ]] || die "refusing install dir with '..': ${dest}"

echo "[INFO] Installing into ${dest}"
rm -rf "${dest}"
mkdir -p "${dest}"
cp -R --preserve=mode,timestamps "${src}/." "${dest}/"
chown -R root:root "${dest}"
chmod +x "${dest}"/*.sh 2>/dev/null || true

cd "${dest}"
if [[ -f install.sh ]]; then
    echo "[INFO] Running install.sh"
    exec bash ./install.sh
elif [[ -f install_binaries.sh ]]; then
    echo "[INFO] Running install_binaries.sh"
    exec bash ./install_binaries.sh
else
    echo "[INFO] Installing .deb packages"
    exec apt-get install -y ./*.deb
fi
