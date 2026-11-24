#!/bin/sh
# Environment used for the experiments (only needed when pycparser/pysodium/
# graphviz/swig/libsodium-dev cannot be installed, as in our test machine).
# It does NOT change the compiler: it provides the three Python modules the
# compiler imports, and builds the interpreter against the system libsodium.
#   - graphviz.py : no-op stand-in (graphviz is only used by debug plots)
#   - pysodium.py : crypto_box_seal through ctypes on the system libsodium
#   - schwaemm/   : ctypes binding to compiler/schwaemm (replaces the SWIG build)
# Usage (from the repository root):  . env_shims/setup_env.sh
HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "$PWD/env_shims")
[ -f "$HERE/graphviz.py" ] || HERE="$PWD/env_shims"
SRC="$PWD/compiler/schwaemm/schwaemm"
gcc -O2 -fPIC -shared -I"$SRC" "$SRC/schwaemm.c" "$SRC/sparkle.c" "$SRC/wrapper.c" \
    -o "$HERE/schwaemm/libschwaemm.so"
SODIUM=$(ldconfig -p | awk '/libsodium.so/ {print $NF; exit}')
make -s -C runtime CFLAGS="-O3 -I$HERE/include" LIBS="$SODIUM -lm"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONHASHSEED=0
echo "environment ready (PYTHONPATH=$PYTHONPATH)"
