import hashlib
import os
import re
import configparser
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

import sys as _sys
_APP_DIR = Path(_sys.executable).parent if getattr(_sys, "frozen", False) else Path(__file__).parent.parent
ACTIVATION_FILE = _APP_DIR / "activation.dat"
# 开发时通过 .env 设置 WM_PRIVATE_KEY=xxx；发布时编译进 exe 前替换
_PRIVATE_KEY = os.environ.get("WM_PRIVATE_KEY", "WM_DEFAULT_KEY_2026")

VALID_PREFIXES = {"BAS": "基础版", "STD": "标准版"}


def _code_hash(prefix: str, seq: str) -> str:
    raw = f"{_PRIVATE_KEY}-{prefix}-{seq}"
    h = hashlib.sha256(raw.encode()).hexdigest().upper()
    return f"{h[0:6]}-{h[6:12]}-{h[12:18]}-{h[18:24]}"


def _is_valid_format(code: str) -> bool:
    return bool(re.match(r"^(BAS|STD)-[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}$", code))


def is_activated() -> bool:
    # 本地测试模式：自动激活
    if os.environ.get("WM_DEBUG") == "1":
        return True
    if not ACTIVATION_FILE.exists():
        return False
    try:
        cfg = configparser.ConfigParser()
        cfg.read(ACTIVATION_FILE, encoding="utf-8")
        code = cfg.get("activation", "code", fallback="")
        if not _is_valid_format(code):
            return False
        # 重新验证 hash，防止手写激活文件绕过
        prefix = code[:3]
        code_part = code[4:]
        for i in range(1, 10000):
            if _code_hash(prefix, f"{i:04d}") == code_part:
                return True
        return False
    except Exception:
        return False


def verify_code(code: str) -> dict:
    code = code.strip().upper()
    if not _is_valid_format(code):
        return {"ok": False, "reason": "格式错误，应为 BAS/STD-XXXXXX-XXXXXX-XXXXXX-XXXXXX"}

    prefix = code[:3]
    code_part = code[4:]

    for i in range(1, 10000):
        seq = f"{i:04d}"
        if _code_hash(prefix, seq) == code_part:
            version = VALID_PREFIXES[prefix]
            save_activation(code, version)
            return {"ok": True, "version": version}

    return {"ok": False, "reason": "注册码无效，请确认输入正确或联系客服"}


def save_activation(code: str, version: str):
    cfg = configparser.ConfigParser()
    cfg["activation"] = {"code": code, "version": version}
    with open(ACTIVATION_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


def get_version() -> str:
    try:
        cfg = configparser.ConfigParser()
        cfg.read(ACTIVATION_FILE, encoding="utf-8")
        return cfg.get("activation", "version", fallback="基础版")
    except Exception:
        return "基础版"


def generate_batch(count: int = 20, prefix: str = "BAS") -> list[str]:
    """开发者工具：批量生成注册码，不随程序发布。"""
    return [f"{prefix}-{_code_hash(prefix, f'{i:04d}')}" for i in range(1, count + 1)]


if __name__ == "__main__":
    # 生成测试用注册码
    codes = generate_batch(5, "BAS")
    print("基础版测试注册码：")
    for c in codes:
        print(" ", c)
    print()
    codes = generate_batch(5, "STD")
    print("标准版测试注册码：")
    for c in codes:
        print(" ", c)
