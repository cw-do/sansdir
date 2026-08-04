#!/bin/bash
# Build a private TeX tree with the packages the ORNL template needs but that
# the analysis cluster's stock TeX Live 2020 does not ship.
#
#   ./fetch-texdeps.sh            # populates /tmp/texdeps/tl (~40 MB)
#   export TEXMFHOME=/tmp/texdeps/tl
#   export PATH="/tmp/texdeps/tl/bin/x86_64-linux:$PATH"   # for biber
#   make
#
# Nothing outside $DEST is touched: the system TeX installation is left alone.
# Fedora's tlmgr refuses --usermode installs on this host, which is why the
# packages are fetched straight from the CTAN tlnet archive instead.
#
# IMPORTANT: l3kernel, l3packages, and l3backend are deliberately NOT fetched.
# The current versions require a newer LaTeX format than the 2020 one installed
# here and abort with "Mismatched LaTeX support files detected"; the system's
# own expl3 works with the acro version below.

set -euo pipefail

DEST="${1:-/tmp/texdeps/tl}"
MIRROR="https://ctan.math.illinois.edu/systems/texlive/tlnet/archive"

# Required by ornltm.cls itself.
CLASS_DEPS="wallpaper adjustbox collectbox emptypage acro tocloft framed
            seqsplit everysel xkeyval translations"

# Required by the report preamble.
REPORT_DEPS="threeparttable multirow wrapfig
             biblatex biblatex-chicago logreq xpatch xstring hyphenat"

# Times-family fonts the class selects.
FONT_DEPS="newtx newtxsf txfonts fontaxes"

# The biblatex backend binary.
BIN_DEPS="biber.x86_64-linux"

mkdir -p "$DEST"
cd "$DEST"

for pkg in $CLASS_DEPS $REPORT_DEPS $FONT_DEPS $BIN_DEPS; do
  printf '%-24s ' "$pkg"
  code=$(curl -sSL -w '%{http_code}' -o "$pkg.tar.xz" "$MIRROR/$pkg.tar.xz" || echo 000)
  if [ "$code" = "200" ]; then
    tar xf "$pkg.tar.xz"
    rm -f "$pkg.tar.xz"
    echo "ok"
  else
    echo "FAILED (http $code)"
  fi
done

rm -rf tlpkg
echo
echo "Tree ready at $DEST"
echo "  export TEXMFHOME=$DEST"
echo "  export PATH=\"$DEST/bin/x86_64-linux:\$PATH\""
