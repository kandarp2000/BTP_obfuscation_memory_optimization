"""Build the plain (non-obfuscated) C program for a test, like run_tests.pl does.

Usage: python3 native_ref.py <prog.c> <out_binary>
Reads <prog>.info, writes a C main() that reads the inputs from argv and prints
the outputs one per line (same format as the OBSCURE interpreter), compiles it.
"""
import re
import subprocess
import sys

c_src, out_bin = sys.argv[1], sys.argv[2]
info = {}
for line in open(c_src[:-2] + ".info"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        info[k.strip()] = v.strip()
types = [t.strip() for t in info["INPUT_TYPES"].split(",")]

c_vars, args, end_prints, proto = [], [], [], []
for n, t in enumerate(types):
    m = re.match(r"^unsigned int\s*\[\s*(\d+)\s*\]\s*(\+?)\s*$", t)
    if m:
        size, inout = int(m.group(1)), m.group(2) == "+"
        c_vars.append(f"unsigned int v{n}[{size}]; v{n}[0]")
        c_vars += [f"v{n}[{i}]" for i in range(1, size)]
        if inout:
            end_prints += [f'printf("%u\\n", v{n}[{i}]);' for i in range(size)]
        args.append(f"v{n}")
        proto.append(f"unsigned int v{n}[{size}]")
    else:
        c_vars.append(f"unsigned int v{n}")
        args.append(f"v{n}")
        proto.append(f"unsigned int v{n}")

reads = "\n    ".join(f"{v} = strtoul(argv[{i + 1}], 0, 10);" for i, v in enumerate(c_vars))
call = f"{info['MAIN']}({','.join(args)})"
if info.get("VOID_MAIN", "").strip().lower() in ("", "0", "false"):  # like run_tests.pl: any other value means void
    call = f'printf("%u\\n", {call})'
main_c = f"""#include <stdlib.h>
#include <stdio.h>
int {info['MAIN']}({','.join(proto)});
int main(int argc, char** argv) {{
    {reads}
    {call};
    {' '.join(end_prints)}
    return 0;
}}
"""
open(out_bin + "_main.c", "w").write(main_c)
subprocess.run(["gcc", "-w", "-O1", out_bin + "_main.c", c_src, "-o", out_bin], check=True)
print(info["INPUT_COUNT"], info.get("OUTPUT_COUNT", "1"))
