import os
import sys

from .read_version import read_version
from .strato.api.user import get_me

try:
    # hack: プラグイン実行環境では必ず失敗する。型推論を効かせるためのコード
    from .vendor import sentry_sdk
except Exception:
    # to import vendored dependencies
    VENDOR_DIR = os.path.join(os.path.dirname(__file__), "vendor")
    if VENDOR_DIR not in sys.path:
        sys.path.append(VENDOR_DIR)

    import sentry_sdk


def init_sentry():
    try:
        user_info = get_me()
        sentry_sdk.init(
            dsn="https://ee1792defe1a9bcbd0142de036712f1f@o4504721342136320.ingest.us.sentry.io/4510384287449089",
            send_default_pii=True,
            release=read_version(),
        )
        sentry_sdk.set_user({"id": user_info.id})
    except Exception:
        pass


def capture_exception(e: Exception):
    try:
        sentry_sdk.capture_exception(e)
    except Exception:
        pass
