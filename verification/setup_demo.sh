#!/bin/bash
# One-time setup (inside WSL Ubuntu / Linux). Creates ~/btp_demo with:
#   original/  the ORIGINAL OBSCURE code (the first commit of this repository)
#   memopt/    the MEMORY-OPTIMIZED compiler (the current code of this repository)
#   pylib/     pycparser 2.22 (the only Python package the compiler needs)
#   shims/     env_shims (pysodium, graphviz, schwaemm stand-ins) + libschwaemm.so
# and builds the interpreter (secure-element simulator) for both.
# Needs: git, python3, gcc, make, perl and the libsodium shared library (libsodium23).
# Re-run it after changing the compiler code.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
D="$HOME/btp_demo"
mkdir -p "$D"; cd "$D"
rm -rf original memopt pylib shims
BASE=$(git -C "$REPO" rev-list --max-parents=0 HEAD)
mkdir original; git -C "$REPO" archive "$BASE" | tar -x -C original
mkdir memopt; tar -C "$REPO" --exclude=.git --exclude=report --exclude=verification -cf - . | tar -x -C memopt
find original memopt -name __pycache__ -prune -exec rm -rf {} +
find original memopt -name '*.o' -delete
mkdir pylib
python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
    "$HERE/pycparser-2.22-py3-none-any.whl" pylib
cp -r memopt/env_shims shims
SRC="$D/memopt/compiler/schwaemm/schwaemm"
gcc -O2 -fPIC -shared -I"$SRC" "$SRC/schwaemm.c" "$SRC/sparkle.c" "$SRC/wrapper.c" \
    -o shims/schwaemm/libschwaemm.so
SODIUM=$(ls /lib/x86_64-linux-gnu/libsodium.so.* | head -1)
for R in original memopt; do
  ( cd $R/compiler && rm -f compiler.py && ln -s src/main.py compiler.py )
  make -s -C $R/runtime CFLAGS="-O3 -w -I$D/shims/include" LIBS="$SODIUM -lm"
done
rm -rf interp    # per-SE interpreters are rebuilt on demand by compare_mem.py
echo "setup OK: $D"
