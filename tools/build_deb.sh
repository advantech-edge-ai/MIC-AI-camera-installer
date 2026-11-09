#!/bin/bash
# Build build/advantech-camera-installer_<version>_all.deb with dpkg-deb.
#   bash tools/build_deb.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="advantech-camera-installer"
VERSION="$(python3 -c "import sys; sys.path.insert(0, '${ROOT}'); import camera_installer as c; print(c.__version__)")"
LIBDIR="/usr/lib/${PKG}"
STAGE="${ROOT}/build/${PKG}_${VERSION}_all"

rm -rf "${STAGE}"
mkdir -p "${STAGE}/DEBIAN" "${STAGE}${LIBDIR}" "${STAGE}/usr/bin" "${STAGE}/usr/share/applications"

# python package (sources only; tools/ and tests/ stay out)
(cd "${ROOT}" && find camera_installer -type f \( -name '*.py' -o -name '*.sh' -o -name '*.png' -o -name '*.svg' \) \
    -not -path '*/__pycache__/*' -print0 | xargs -0 -I{} install -D -m 644 {} "${STAGE}${LIBDIR}/{}")
chmod 755 "${STAGE}${LIBDIR}/camera_installer/helpers/install_driver.sh"

cat > "${STAGE}/usr/bin/${PKG}" <<EOF
#!/bin/sh
PYTHONPATH=${LIBDIR} exec /usr/bin/python3 -m camera_installer "\$@"
EOF
chmod 755 "${STAGE}/usr/bin/${PKG}"

for size in 48 64 128 192; do
    install -D -m 644 "${ROOT}/camera_installer/assets/app_icon_${size}.png" \
        "${STAGE}/usr/share/icons/hicolor/${size}x${size}/apps/${PKG}.png"
done

cat > "${STAGE}/usr/share/applications/${PKG}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Advantech Camera Driver Installer
Comment=Install camera drivers for Advantech MIC-AI systems
Exec=${PKG}
Icon=${PKG}
StartupWMClass=Advantech-camera-installer
Terminal=false
Categories=System;Settings;
EOF

cat > "${STAGE}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Architecture: all
Maintainer: Advantech <ChunYu.Chen@advantech.com>
Depends: python3 (>= 3.8), python3-tk, pkexec | policykit-1
Section: utils
Priority: optional
Description: Advantech camera driver installer for MIC-AI Jetson systems
 Detects the device model and JetPack version, lists compatible camera
 drivers from the MIC-AI-camera-driver GitHub repository, then downloads,
 verifies and installs the selected driver.
EOF

# no stale bytecode left behind on remove
cat > "${STAGE}/DEBIAN/prerm" <<EOF
#!/bin/sh
set -e
find ${LIBDIR} -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
EOF
chmod 755 "${STAGE}/DEBIAN/prerm"

cat > "${STAGE}/DEBIAN/postinst" <<EOF
#!/bin/sh
set -e
gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
EOF
chmod 755 "${STAGE}/DEBIAN/postinst"

dpkg-deb --root-owner-group --build "${STAGE}" "${ROOT}/build/${PKG}_${VERSION}_all.deb"
# unversioned copy for the permanent releases/latest/download/... link
cp "${ROOT}/build/${PKG}_${VERSION}_all.deb" "${ROOT}/build/${PKG}_all.deb"
