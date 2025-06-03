#!/usr/bin/env python3
"""pytest設定ファイル"""

import sys
import os
from pathlib import Path

# プロジェクトルートを取得
project_root = Path(__file__).parent.parent

# プロジェクトルートをPythonパスに追加
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# パッケージとしてインポートできるように設定
sys.modules["qgis_plugin"] = sys.modules["__main__"] if "__main__" in sys.modules else None

