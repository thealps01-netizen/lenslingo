"""cfg.py — LensLingo kullanıcı ayarları (settings.json).

Ayarları %LOCALAPPDATA%/LensLingo/settings.json içinde saklar; uygulama
kaynak koddan çalışırken proje kökünde tutar. updater.py atlanan sürümü
('skipped_version') burada saklar; kendi ayarlarını da buraya ekleyebilirsin.
"""

import json
import os
import sys

from logger import get_logger

_log = get_logger("cfg")

if getattr(sys, "frozen", False):
    _BASE = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.dirname(sys.executable)),
        "LensLingo",
    )
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

CFG_PATH = os.path.join(_BASE, "settings.json")


def load_cfg() -> dict:
    """settings.json'u oku (yoksa boş sözlük döndür)."""
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        _log.warning("settings.json okunamadı: %s", e)
        return {}


def save_cfg(cfg: dict) -> None:
    """settings.json'a yaz."""
    try:
        os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.warning("settings.json yazılamadı: %s", e)
