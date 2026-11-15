#!/usr/bin/env python3
import sys
import shutil
from pathlib import Path

OUTPUT_DIR = Path("output")

def main():
    if len(sys.argv) != 2:
        print("用法: python3 assemble_ci.py <ipa_path>")
        sys.exit(1)

    ipa_path = Path(sys.argv[1])
    if not ipa_path.exists():
        print(f"文件不存在: {ipa_path}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUTPUT_DIR / ipa_path.name
    shutil.copy2(ipa_path, dest)
    print(f"已复制 IPA 到: {dest}")

if __name__ == "__main__":
    main()
