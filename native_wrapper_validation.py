import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--candidate", choices=["PR_05", "PR_06"], required=True)
parser.add_argument("--compiler", choices=["msvc", "clang"], required=True)
args = parser.parse_args()
source = Path.cwd()
evidence = source / "evidence"
evidence.mkdir(exist_ok=True)
records = []


def run(name, command):
    with (evidence / (name + ".log")).open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    records.append({"name": name, "command": command, "exit_code": result.returncode})
    (evidence / "commands.json").write_text(json.dumps(records, indent=2))
    configure_details = (
        source / "build-native" / "CMakeFiles" / "CMakeConfigureLog.yaml"
    )
    if configure_details.exists():
        shutil.copy2(configure_details, evidence / "CMakeConfigureLog.yaml")
    if result.returncode:
        print((evidence / (name + ".log")).read_text(errors="replace")[-6000:])
        raise SystemExit(result.returncode)


cmake = shutil.which("cmake")
ctest = shutil.which("ctest")
assert cmake and ctest
build = source / "build-native"
# Use the Ubuntu system Clang toolchain with its own standard-library paths.
# Pixi's Linux activation otherwise supplies flags for its GCC sysroot.
toolchain_flags = []
if args.compiler == "clang":
    inherited_flags = {
        key: os.environ.pop(key, "")
        for key in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS")
    }
    (evidence / "inherited-toolchain-flags.json").write_text(
        json.dumps(inherited_flags, indent=2)
    )
    system_math = Path("/usr/lib/x86_64-linux-gnu/libm.so")
    assert system_math.is_file()
    toolchain_flags = ["-DCMath_LIBRARY=" + str(system_math)]

compiler = (
    ["-DCMAKE_C_COMPILER=clang", "-DCMAKE_CXX_COMPILER=clang++"]
    if args.compiler == "clang"
    else ["-DCMAKE_C_COMPILER=cl", "-DCMAKE_CXX_COMPILER=cl"]
)
run(
    "configure",
    [
        cmake,
        "-S",
        str(source),
        "-B",
        str(build),
        "-GNinja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        "-DITK_BUILD_DEFAULT_MODULES=OFF",
        "-DBUILD_EXAMPLES=OFF",
        "-DBUILD_TESTING=" + ("ON" if args.candidate == "PR_05" else "OFF"),
        "-DITK_WRAP_PYTHON=ON",
        "-DITK_USE_SYSTEM_SWIG=ON",
        "-DITK_USE_SYSTEM_CASTXML=ON",
        "-DITK_WRAP_float=ON",
        "-DITK_WRAP_IMAGE_DIMS=2;3",
        "-DPython3_EXECUTABLE=" + sys.executable,
        "-DModule_"
        + ("ITKBridgeNumPy" if args.candidate == "PR_05" else "ITKCommon")
        + "=ON",
        *compiler,
        *toolchain_flags,
    ],
)
entries = json.loads((build / "compile_commands.json").read_text())
common = [
    entry for entry in entries if "ITKCommonPython.dir" in entry.get("command", "")
]
assert common
if args.candidate == "PR_06" and args.compiler == "clang":
    for entry in common:
        tokens = entry.get("arguments") or shlex.split(entry["command"])
        assert ("-w" in tokens) == (Path(entry["file"]).suffix == ".cpp"), entry
        assert "-fno-strict-aliasing" in tokens, entry
(evidence / "ITKCommonPython-commands.json").write_text(json.dumps(common, indent=2))
targets = ["ITKCommonPython"]
if args.candidate == "PR_05":
    targets += [
        "ITKBridgeNumPyPython",
        "ITKPyBasePython",
        "itkTestDriver",
        "copy_python_files",
    ]
run("build", [cmake, "--build", str(build), "--target", *targets, "--parallel", "2"])
if args.candidate == "PR_05":
    run(
        "vector-container-ctest",
        [
            ctest,
            "--test-dir",
            str(build),
            "-R",
            "^itkPyVectorContainerTest$",
            "--output-on-failure",
            "-V",
        ],
    )
(evidence / "result.json").write_text(
    json.dumps(
        {
            "candidate": args.candidate,
            "compiler": args.compiler,
            "status": "PASSED",
            "commands": records,
        },
        indent=2,
    )
)
