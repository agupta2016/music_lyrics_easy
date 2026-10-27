"""Make NVIDIA's pip-installed CUDA libraries visible to CTranslate2 on Windows.

`pip install -r requirements-gpu.txt` puts cuBLAS and cuDNN under
site-packages/nvidia/*/bin, which Windows doesn't search for DLLs. Without
this, Whisper fails with "Library cublas64_12.dll is not found".
"""

import ctypes
import glob
import logging
import os
import site
import sys

log = logging.getLogger(__name__)

# Loaded up front so CTranslate2's later lookups by bare name find them in the process.
_PRELOAD = ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll")


def nvidia_dll_dirs() -> list[str]:
    roots = site.getsitepackages() + [site.getusersitepackages()]
    dirs: list[str] = []
    for root in roots:
        for path in sorted(glob.glob(os.path.join(root, "nvidia", "*", "bin"))):
            if os.path.isdir(path) and path not in dirs:
                dirs.append(path)
    return dirs


def register_nvidia_libraries() -> list[str]:
    """Add the NVIDIA DLL folders to the search path. Returns the folders added."""
    if sys.platform != "win32":
        return []
    dirs = nvidia_dll_dirs()
    if not dirs:
        return []
    os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
    for path in dirs:
        try:
            os.add_dll_directory(path)
        except (AttributeError, OSError):
            pass
    for name in _PRELOAD:
        for path in dirs:
            candidate = os.path.join(path, name)
            if os.path.exists(candidate):
                try:
                    ctypes.CDLL(candidate)
                except OSError as exc:
                    log.warning("Couldn't load %s: %s", candidate, exc)
                break
    return dirs


def cuda_available() -> bool:
    try:
        import ctranslate2
    except ImportError:
        return False
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
