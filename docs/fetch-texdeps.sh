#!/bin/bash
# Build a private TeX tree with the packages the ORNL template needs but that
# the analysis cluster's stock TeX Live 2020 does not ship.
#
#   ./fetch-texdeps.sh            # populates /tmp/texdeps/tl (~40 MB)
#   export TEXMFHOME=/tmp/texdeps/tl
#   export PATH="/tmp/texdeps/tl/bin/x86_64-linux:$PATH"   # for biber
#   eval "$(./fetch-texdeps.sh --libnsl-env)"   # only if biber needs libnsl.so.1
#   make
#
# Nothing outside $DEST is touched: the system TeX installation is left alone.
# Fedora's tlmgr refuses --usermode installs here, which is why the packages
# are fetched straight from a TeX Live snapshot instead.
#
# IMPORTANT: l3kernel, l3packages, and l3backend are deliberately NOT fetched.
# The current versions require a newer LaTeX format than the 2020 one installed
# here and abort with "Mismatched LaTeX support files detected"; the system's
# own expl3 works with the acro version below.
#
# IMPORTANT: the mirror below is a *dated* historic snapshot
# (texlive.info/tlnet-archive), not the live CTAN mirror. The live mirror's
# packages drift forward in time and eventually stop being mutually
# compatible with this host's TeX Live 2020 format -- that happened once
# already (2026-08: a live-mirror `tocloft` required LaTeX format
# 2023-11-01 and broke the build). Pinning to one dated snapshot makes the
# whole set internally consistent and the build reproducible. Bump the date
# only if a needed package is missing from it; re-verify with `make` after.

set -euo pipefail

SNAPSHOT_DATE="2021/06/01"   # verified to carry every package below
MIRROR="https://www.texlive.info/tlnet-archive/${SNAPSHOT_DATE}/tlnet/archive"

if [ "${1:-}" = "--libnsl-env" ]; then
  # biber (built against an older glibc) dynamically links libnsl.so.1,
  # which glibc dropped years ago. Modern distros ship the ABI-compatible
  # replacement under a different soname (e.g. RHEL 9's libnsl2 package
  # gives libnsl.so.3). Rather than guess a path, ask the dynamic linker
  # what is actually installed and symlink a compat shim to it.
  DEST="${2:-/tmp/texdeps/tl}"
  # awk's early `exit` can close its end of the pipe while ldconfig is
  # still writing, so ldconfig gets SIGPIPE; with pipefail that fails the
  # whole pipeline and, under `set -e`, kills the script before anything
  # is printed. Turn pipefail off for just this one intentionally-partial
  # read.
  set +o pipefail
  found="$(ldconfig -p 2>/dev/null | awk '/libnsl\.so\./{print $NF; exit}')"
  set -o pipefail
  if [ -z "$found" ]; then
    echo "# no libnsl.so.* found by ldconfig -- install libnsl2 (or equivalent)," >&2
    echo "# or run biber on a host that already has it." >&2
    exit 1
  fi
  compat="$DEST/lib-compat"
  mkdir -p "$compat"
  ln -sf "$found" "$compat/libnsl.so.1"
  echo "export LD_LIBRARY_PATH=\"$compat\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}\""
  exit 0
fi

DEST="${1:-/tmp/texdeps/tl}"

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
