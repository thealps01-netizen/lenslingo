# -*- coding: utf-8 -*-
"""
LensLingo — Canlı Ekran Çevirmeni  (PyQt6)
------------------------------------------
Ekranda seçtiğin bir bölgeyi sürekli izler, içindeki **her metin bloğunu**
EasyOCR ile bulur, etrafını bir kutu ile işaretler ve çeviriyi tam o metnin
altına yazar. İstersen tüm çeviriyi tek bir panelde de gösterebilir.

Akış:  Ekran bölgesi -> EasyOCR (kutular + metin) -> Çeviri -> Ekran üzerine çizim

Bağımlılıklar: PyQt6, easyocr, mss, deep-translator, numpy
"""

import sys
import time

import mss
import numpy as np

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QRectF, QPoint
from PyQt6.QtGui import (QColor, QPainter, QPen, QBrush, QFont, QFontMetrics,
                         QGuiApplication)
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton,
                             QComboBox, QSlider, QCheckBox, QVBoxLayout,
                             QHBoxLayout, QFrame, QRadioButton, QButtonGroup,
                             QGraphicsDropShadowEffect, QScrollArea)

# ---- Ağır import tembel yüklenir (uygulama hızlı açılsın diye) ----
try:
    from deep_translator import GoogleTranslator
except Exception:  # pragma: no cover
    GoogleTranslator = None

# ---- İskele altyapısı: loglama, crash handler, sürüm, otomatik güncelleme ----
import crash_handler
from logger import get_logger
from version import __version__
from updater import UpdateChecker, prompt_and_install

# GitHub deposu (otomatik güncelleme buradan sürüm kontrol eder)
GITHUB_USER = "thealps01-netizen"
GITHUB_REPO = "lenslingo"

_log = get_logger("main")


# ============================ Tema / Renkler ==============================
class C:
    BG       = "#0e1117"
    CARD     = "#161b22"
    CARD2    = "#1c2230"
    BORDER   = "#2a3140"
    TEXT     = "#e6edf3"
    MUTED    = "#8b949e"
    ACCENT   = "#4f8cff"
    ACCENT_H = "#6ba0ff"
    OK       = "#3fb950"
    ERR      = "#f85149"
    BOX      = "#00e5ff"   # ekranda metin kutusu rengi


OCR_LANGS = {
    "İngilizce (en)":  ["en"],
    "Türkçe (tr)":     ["tr"],
    "Almanca (de)":    ["de"],
    "Fransızca (fr)":  ["fr"],
    "İspanyolca (es)": ["es"],
    "Rusça (ru)":      ["ru"],
    "Japonca (ja)":    ["ja", "en"],
    "Korece (ko)":     ["ko", "en"],
    "Çince (ch_sim)":  ["ch_sim", "en"],
}

TARGET_LANGS = {
    "Türkçe":     "tr",
    "İngilizce":  "en",
    "Almanca":    "de",
    "Fransızca":  "fr",
    "İspanyolca": "es",
    "İtalyanca":  "it",
    "Rusça":      "ru",
}


# ============================ Arka plan işçisi ============================
class OcrWorker(QThread):
    boxes   = pyqtSignal(list)   # [(x1,y1,x2,y2,translated), ...] (logical px)
    pairs   = pyqtSignal(list)   # [(orijinal, çeviri), ...] — not modu
    status  = pyqtSignal(str, bool)  # (mesaj, hata_mi)
    stopped = pyqtSignal()

    def __init__(self, app, region_phys, origin, dpr, ocr_langs, target,
                 mode, interval, gpu):
        super().__init__()
        self.app = app
        self.region = region_phys
        self.ox, self.oy = origin           # logical bölge sol-üst
        self.dpr = dpr
        self.ocr_langs = ocr_langs
        self.target = target
        self.mode = mode
        self.interval = interval
        self.gpu = gpu
        self._running = True
        self._last_sig = None
        self._own = set()   # kendi ürettiğimiz çeviriler (tekrar çevirmeyi önler)

    def stop(self):
        self._running = False

    # -- çeviri (önbellekli) --
    def _translate(self, translator, text):
        cache = self.app.cache
        if text in cache:
            return cache[text]
        try:
            out = translator.translate(text) or text
        except Exception:
            return "[çeviri hatası]"
        cache[text] = out
        return out

    def run(self):
        # EasyOCR modelini gerektiğinde yükle (uygulamada önbelleğe alınır)
        reader = self.app.reader
        need = reader is None or getattr(reader, "_langs", None) != tuple(self.ocr_langs)
        if need:
            self.status.emit("EasyOCR modeli yükleniyor… (ilk sefer uzun sürebilir)", False)
            try:
                import torch
                use_gpu = bool(self.gpu and torch.cuda.is_available())
            except Exception:
                use_gpu = False
            try:
                import easyocr
                reader = easyocr.Reader(self.ocr_langs, gpu=use_gpu)
                reader._langs = tuple(self.ocr_langs)
                self.app.reader = reader
                self.status.emit(f"Model hazır (GPU={'açık' if use_gpu else 'kapalı'}).", False)
            except Exception as ex:
                self.status.emit(f"OCR yüklenemedi: {ex}", True)
                self.stopped.emit()
                return

        if GoogleTranslator is None:
            self.status.emit("deep-translator kurulu değil.", True)
            self.stopped.emit()
            return
        translator = GoogleTranslator(source="auto", target=self.target)

        with mss.mss() as sct:
            while self._running:
                t0 = time.time()
                try:
                    img = np.array(sct.grab(self.region))[:, :, :3]  # BGRA->BGR
                    results = reader.readtext(img, detail=1, paragraph=False)
                except Exception as ex:
                    self.status.emit(f"OCR hatası: {ex}", True)
                    time.sleep(0.5)
                    continue

                if not self._running:
                    break

                dets = []
                for det in results:
                    bbox, txt = det[0], det[1]
                    conf = det[2] if len(det) > 2 else 1.0
                    txt = (txt or "").strip()
                    # kendi çevirimizi ekrandan tekrar okuyup çevirmeyi önle
                    if txt and conf >= 0.35 and txt not in self._own:
                        dets.append((bbox, txt))
                # okuma sırası: yukarıdan aşağı, soldan sağa
                dets.sort(key=lambda d: (min(p[1] for p in d[0]),
                                         min(p[0] for p in d[0])))

                if not dets:
                    # Tarama boş döndü — son içeriği KORU (yanıp sönme/kaybolma olmasın)
                    self.status.emit("Metin bekleniyor…", False)
                elif self.mode == "box":
                    self._emit_boxes(dets, translator)
                else:
                    self._emit_pairs(dets, translator)

                # kalan süreyi küçük parçalar halinde bekle (Durdur'a hızlı tepki)
                remaining = self.interval - (time.time() - t0)
                while remaining > 0 and self._running:
                    time.sleep(min(0.1, remaining))
                    remaining -= 0.1
        self.stopped.emit()

    def _emit_boxes(self, dets, translator):
        sig = tuple(t for _, t in dets)
        if sig == self._last_sig:
            return
        self._last_sig = sig
        items = []
        for bbox, txt in dets:
            xs = [p[0] for p in bbox]; ys = [p[1] for p in bbox]
            # fiziksel piksel -> logical piksel + bölge kayması
            x1 = self.ox + int(min(xs) / self.dpr)
            x2 = self.ox + int(max(xs) / self.dpr)
            y1 = self.oy + int(min(ys) / self.dpr)
            y2 = self.oy + int(max(ys) / self.dpr)
            tr = self._translate(translator, txt)
            self._own.add(tr)   # ekrana yazdığımızı tekrar çevirme
            items.append((x1, y1, x2, y2, tr))
        self.boxes.emit(items)
        self.status.emit(f"{len(items)} metin çevrildi", False)

    def _emit_pairs(self, dets, translator):
        sig = tuple(t for _, t in dets)
        if sig == self._last_sig:        # ekran değişmedi → tekrar çizme
            return
        self._last_sig = sig
        pairs = []
        for _, txt in dets:
            tr = self._translate(translator, txt)
            self._own.add(tr)   # ekrana yazdığımızı tekrar çevirme
            pairs.append((txt, tr))
        self.pairs.emit(pairs)
        self.status.emit(f"{len(pairs)} not güncellendi", False)


# ============================ Bölge seçici ================================
class RegionSelector(QWidget):
    picked = pyqtSignal(int, int, int, int)  # logical: left, top, w, h
    closed = pyqtSignal()                     # pencere kapandığında (panel'i geri göster)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(QGuiApplication.primaryScreen().geometry())
        self._start = None
        self._end = None

    def paintEvent(self, _e):
        p = QPainter(self)
        # Tüm ekranı yarı saydam karart (canlı masaüstü altta görünür)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        p.setPen(QPen(QColor(C.TEXT)))
        p.setFont(QFont("Segoe UI", 15, QFont.Weight.DemiBold))
        p.drawText(QRect(0, 30, self.width(), 40),
                   Qt.AlignmentFlag.AlignHCenter,
                   "Çevrilecek alanı fareyle sürükleyerek seç   ·   ESC = iptal")
        if self._start is not None and self._end is not None:
            r = QRect(self._start, self._end).normalized()
            # Seçili alanı vurgula + cyan çerçeve
            p.fillRect(r, QColor(0, 229, 255, 45))
            p.setPen(QPen(QColor(C.BOX), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)

    def mousePressEvent(self, e):
        self._start = e.position().toPoint()
        self._end = self._start
        self.update()

    def mouseMoveEvent(self, e):
        self._end = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):
        self._end = e.position().toPoint()
        r = QRect(self._start, self._end).normalized()
        if r.width() > 10 and r.height() > 10:
            self.picked.emit(r.left(), r.top(), r.width(), r.height())
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)


# ============================ Kutu overlay ================================
class BoxOverlay(QWidget):
    """Tam ekran, şeffaf, tıklama-geçirgen. Kutular + altına çeviri çizer."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.items = []

    def set_items(self, items):
        self.items = items
        self.update()

    def clear(self):
        self.items = []
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
        p.setFont(font)
        fm = QFontMetrics(font)
        for (x1, y1, x2, y2, txt) in self.items:
            # 1) Orijinal metni işaretle
            p.setPen(QPen(QColor(C.BOX), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(x1, y1, x2 - x1, y2 - y1), 4, 4)

            # 2) Çeviriyi hemen altına, okunur zeminle yaz
            box_w = max(150, x2 - x1)
            rect = fm.boundingRect(QRect(0, 0, box_w, 400),
                                   Qt.TextFlag.TextWordWrap, txt)
            pad = 6
            bg = QRectF(x1, y2 + 4, rect.width() + pad * 2,
                        rect.height() + pad * 2)
            p.setPen(QPen(QColor(C.ACCENT), 1))
            p.setBrush(QBrush(QColor(13, 27, 42, 235)))
            p.drawRoundedRect(bg, 6, 6)
            p.setPen(QPen(QColor("#ffffff")))
            p.drawText(QRectF(bg.x() + pad, bg.y() + pad,
                              rect.width(), rect.height()),
                       int(Qt.TextFlag.TextWordWrap), txt)


# ============================ Not penceresi ==============================
class _DragBar(QFrame):
    """Pencereyi başlık çubuğundan sürüklemek için."""
    def __init__(self, win):
        super().__init__()
        self._win = win
        self._drag = None

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self._win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None


class NotesWindow(QWidget):
    """Ekranın sağında, yarı saydam, Yapışkan Notlar tarzı çeviri paneli.

    Bulunan her yazı parçası bir kart olur: üstte renkli şerit, altında
    orijinal metin ve çevirisi. İçerik yalnızca yeni bir tarama değişikliği
    onaylanınca güncellenir (aradaki boş taramalarda kaybolmaz)."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(self._qss())

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        card = QFrame(); card.setObjectName("NWCard"); root.addWidget(card)
        cv = QVBoxLayout(card); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(0)

        # ── Başlık çubuğu (sürüklenebilir) ──
        bar = _DragBar(self); bar.setObjectName("NWBar"); bar.setFixedHeight(46)
        bh = QHBoxLayout(bar); bh.setContentsMargins(16, 0, 10, 0)
        title = QLabel("Çeviri Notları"); title.setObjectName("NWTitle")
        btn_close = QPushButton("✕"); btn_close.setObjectName("NWClose")
        btn_close.setFixedSize(28, 28)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.hide)
        bh.addWidget(title); bh.addStretch(); bh.addWidget(btn_close)
        cv.addWidget(bar)

        # ── Kaydırılabilir kart listesi ──
        self._scroll = QScrollArea(); self._scroll.setObjectName("NWScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget(); inner.setObjectName("NWInner")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(12, 12, 12, 12); self._list.setSpacing(12)
        self._list.addStretch()
        self._scroll.setWidget(inner)
        cv.addWidget(self._scroll)

        self._empty = QLabel("Çeviri bekleniyor…")
        self._empty.setObjectName("NWEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list.insertWidget(0, self._empty)

    # ---- içerik ----
    def set_pairs(self, pairs):
        # eski kartları temizle (sondaki stretch hariç)
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for src, dst in pairs:
            self._list.insertWidget(self._list.count() - 1, self._note(src, dst))

    def _note(self, src, dst):
        note = QFrame(); note.setObjectName("NWNote")
        v = QVBoxLayout(note); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        strip = QFrame(); strip.setObjectName("NWStrip"); strip.setFixedHeight(4)
        v.addWidget(strip)
        body = QVBoxLayout(); body.setContentsMargins(14, 10, 14, 12); body.setSpacing(6)
        s = QLabel(src); s.setObjectName("NWSrc"); s.setWordWrap(True)
        d = QLabel(dst); d.setObjectName("NWDst"); d.setWordWrap(True)
        body.addWidget(s); body.addWidget(d)
        v.addLayout(body)
        return note

    # ---- yerleşim: ekranın sağına yasla ----
    def dock_right(self):
        scr = QGuiApplication.primaryScreen().availableGeometry()
        w = 360
        self.resize(w, scr.height() - 40)
        self.move(scr.right() - w - 14, scr.top() + 20)

    def _qss(self):
        return f"""
        #NWCard {{ background:rgba(16,18,24,225); border:1px solid {C.BORDER};
                   border-radius:14px; }}
        #NWBar {{ background:rgba(255,255,255,10);
                  border-top-left-radius:14px; border-top-right-radius:14px;
                  border-bottom:1px solid {C.BORDER}; }}
        #NWTitle {{ color:{C.TEXT}; font:700 15px 'Segoe UI'; }}
        #NWClose {{ background:transparent; color:{C.MUTED}; border:none;
                    font-size:15px; border-radius:14px; padding:0; }}
        #NWClose:hover {{ background:rgba(248,81,73,40); color:{C.ERR}; }}
        #NWScroll, #NWInner {{ background:transparent; border:none; }}
        #NWNote {{ background:rgba(32,36,46,235); border:1px solid {C.BORDER};
                   border-radius:10px; }}
        #NWStrip {{ background:{C.BOX};
                    border-top-left-radius:10px; border-top-right-radius:10px; }}
        #NWSrc {{ color:{C.MUTED}; font:400 12px 'Segoe UI'; }}
        #NWDst {{ color:#ffffff; font:600 15px 'Segoe UI'; }}
        #NWEmpty {{ color:{C.MUTED}; font:400 13px 'Segoe UI'; padding:28px; }}
        QScrollBar:vertical {{ background:transparent; width:9px; margin:4px 2px; }}
        QScrollBar::handle:vertical {{ background:{C.BORDER}; border-radius:4px;
                    min-height:30px; }}
        QScrollBar::handle:vertical:hover {{ background:{C.ACCENT}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
        """


# ============================ Kontrol paneli =============================
class ControlPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.reader = None
        self.cache = {}
        self.region_phys = None
        self.origin = (0, 0)
        self.dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        self.worker = None
        self.box_overlay = None
        self.panel_overlay = None

        self.setWindowTitle(f"LensLingo v{__version__}")
        self.setMinimumWidth(400)
        self.setStyleSheet(self._qss())
        self._build()

        # ── Açılışta arka planda güncelleme kontrolü (GitHub Releases) ──
        self._update_checker = UpdateChecker(GITHUB_USER, GITHUB_REPO)
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.start()

    def _on_update_available(self, tag, url, notes):
        _log.info("Güncelleme bulundu: %s", tag)
        prompt_and_install(tag, url, notes, parent=self)

    # --------------------------------------------------------------- QSS
    def _qss(self):
        return f"""
        QWidget {{ background:{C.BG}; color:{C.TEXT};
                   font-family:'Segoe UI'; font-size:13px; }}
        #Card {{ background:{C.CARD}; border:1px solid {C.BORDER};
                 border-radius:12px; }}
        #Title {{ font-size:20px; font-weight:600; }}
        #Sub, #Section {{ color:{C.MUTED}; }}
        #Section {{ font-size:11px; font-weight:600; letter-spacing:1px; }}
        QPushButton {{ background:{C.CARD2}; border:1px solid {C.BORDER};
                       border-radius:10px; padding:11px; font-weight:600; }}
        QPushButton:hover {{ border-color:{C.ACCENT}; }}
        QPushButton#Primary {{ background:{C.ACCENT}; border:none; color:white;
                               padding:14px; font-size:14px; }}
        QPushButton#Primary:hover {{ background:{C.ACCENT_H}; }}
        QPushButton#Danger {{ background:{C.ERR}; border:none; color:white;
                              padding:14px; font-size:14px; }}
        QComboBox {{ background:{C.CARD2}; border:1px solid {C.BORDER};
                     border-radius:8px; padding:6px 10px; min-width:150px; }}
        QComboBox:hover {{ border-color:{C.ACCENT}; }}
        QComboBox QAbstractItemView {{ background:{C.CARD2};
                     selection-background-color:{C.ACCENT}; border:1px solid {C.BORDER}; }}
        QComboBox::drop-down {{ border:none; }}
        QRadioButton, QCheckBox {{ spacing:8px; }}
        QRadioButton::indicator, QCheckBox::indicator {{ width:16px; height:16px; }}
        QRadioButton::indicator {{ border-radius:9px; }}
        QCheckBox::indicator {{ border-radius:4px; }}
        QRadioButton::indicator:unchecked, QCheckBox::indicator:unchecked {{
                     border:2px solid {C.BORDER}; background:transparent; }}
        QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
                     border:2px solid {C.ACCENT}; background:{C.ACCENT}; }}
        QSlider::groove:horizontal {{ height:5px; background:{C.CARD2};
                     border-radius:3px; }}
        QSlider::sub-page:horizontal {{ background:{C.ACCENT}; border-radius:3px; }}
        QSlider::handle:horizontal {{ background:white; width:15px; height:15px;
                     margin:-6px 0; border-radius:8px; }}
        """

    def _card(self, title):
        card = QFrame(); card.setObjectName("Card")
        v = QVBoxLayout(card); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(10)
        sec = QLabel(title); sec.setObjectName("Section")
        v.addWidget(sec)
        return card, v

    # ------------------------------------------------------------- arayüz
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18); root.setSpacing(12)

        head = QVBoxLayout(); head.setSpacing(2)
        t = QLabel("LensLingo"); t.setObjectName("Title")
        s = QLabel("Ekrandaki yazıyı bul, işaretle, altına çevir"); s.setObjectName("Sub")
        head.addWidget(t); head.addWidget(s)
        root.addLayout(head)

        # 1) Bölge
        c1, v1 = self._card("1 · ÇEVİRİ BÖLGESİ")
        self.btn_region = QPushButton("🖱  Ekranda Bölge Seç")
        self.btn_region.clicked.connect(self.select_region)
        self.lbl_region = QLabel("Henüz bölge seçilmedi"); self.lbl_region.setObjectName("Sub")
        v1.addWidget(self.btn_region); v1.addWidget(self.lbl_region)
        root.addWidget(c1)

        # 2) Görünüm modu
        c2, v2 = self._card("2 · GÖRÜNÜM")
        self.grp = QButtonGroup(self)
        self.rb_panel = QRadioButton("🗒️  Not modu — sağda yapışkan not paneli (önerilen)")
        self.rb_box = QRadioButton("🔲  Kutu modu — yazıyı ekranda işaretle (deneysel)")
        self.rb_panel.setChecked(True)
        self.grp.addButton(self.rb_panel); self.grp.addButton(self.rb_box)
        v2.addWidget(self.rb_panel); v2.addWidget(self.rb_box)
        root.addWidget(c2)

        # 3) Diller
        c3, v3 = self._card("3 · DİL")
        row = QHBoxLayout(); row.addWidget(QLabel("Ekran dili"))
        self.cmb_ocr = QComboBox(); self.cmb_ocr.addItems(OCR_LANGS.keys())
        self.cmb_ocr.setCurrentText("İngilizce (en)")
        row.addStretch(); row.addWidget(self.cmb_ocr); v3.addLayout(row)
        row2 = QHBoxLayout(); row2.addWidget(QLabel("Çeviri dili"))
        self.cmb_target = QComboBox(); self.cmb_target.addItems(TARGET_LANGS.keys())
        self.cmb_target.setCurrentText("Türkçe")
        row2.addStretch(); row2.addWidget(self.cmb_target); v3.addLayout(row2)
        root.addWidget(c3)

        # 4) Ayarlar
        c4, v4 = self._card("4 · AYARLAR")
        rr = QHBoxLayout(); rr.addWidget(QLabel("Tarama aralığı"))
        self.lbl_interval = QLabel("1.0 sn")
        self.lbl_interval.setStyleSheet(f"color:{C.ACCENT}; font-weight:600;")
        rr.addStretch(); rr.addWidget(self.lbl_interval); v4.addLayout(rr)
        self.sld = QSlider(Qt.Orientation.Horizontal)
        self.sld.setRange(3, 30); self.sld.setValue(10)
        self.sld.valueChanged.connect(
            lambda v: self.lbl_interval.setText(f"{v/10:.1f} sn"))
        v4.addWidget(self.sld)
        self.chk_gpu = QCheckBox("GPU kullan (CUDA varsa hızlı)")
        self.chk_gpu.setChecked(True)
        v4.addWidget(self.chk_gpu)
        root.addWidget(c4)

        # Başlat
        self.btn_toggle = QPushButton("▶  Çeviriyi Başlat")
        self.btn_toggle.setObjectName("Primary")
        self.btn_toggle.clicked.connect(self.toggle)
        shadow = QGraphicsDropShadowEffect(blurRadius=24, xOffset=0, yOffset=4)
        shadow.setColor(QColor(79, 140, 255, 120))
        self.btn_toggle.setGraphicsEffect(shadow)
        root.addWidget(self.btn_toggle)

        self.lbl_status = QLabel("● Hazır")
        self.lbl_status.setStyleSheet(f"color:{C.OK};")
        root.addWidget(self.lbl_status)
        root.addStretch()

    # -------------------------------------------------------- bölge seçimi
    def select_region(self):
        self.hide()
        self._sel = RegionSelector()
        self._sel.picked.connect(self._on_region)
        self._sel.closed.connect(self.show)   # seçim bitince paneli geri getir
        self._sel.show()
        self._sel.activateWindow()
        self._sel.raise_()

    def _on_region(self, lx, ly, w, h):
        self.origin = (lx, ly)
        self.region_phys = {
            "left": int(lx * self.dpr), "top": int(ly * self.dpr),
            "width": int(w * self.dpr), "height": int(h * self.dpr),
        }
        self.lbl_region.setText(f"✓  {w}×{h} px  ·  ({lx}, {ly})")
        self.lbl_region.setStyleSheet(f"color:{C.OK};")

    # ------------------------------------------------------------ başlat/dur
    def toggle(self):
        self.stop() if self.worker else self.start()

    def start(self):
        if self.region_phys is None:
            self._status("Önce bir bölge seç!", True); return
        if GoogleTranslator is None:
            self._status("deep-translator kurulu değil.", True); return

        mode = "box" if self.rb_box.isChecked() else "panel"
        if mode == "box":
            if self.panel_overlay:            # diğer modun panelini gizle
                self.panel_overlay.hide()
            if self.box_overlay is None:
                self.box_overlay = BoxOverlay()
            self.box_overlay.clear(); self.box_overlay.show()
        else:
            if self.box_overlay:              # diğer modun overlay'ini gizle
                self.box_overlay.hide()
            if self.panel_overlay is None:
                self.panel_overlay = NotesWindow()
            self.panel_overlay.dock_right()
            self.panel_overlay.show()
            self.panel_overlay.raise_()

        # çalışırken mod değiştirilemesin (karışıklık olmasın)
        self.rb_box.setEnabled(False)
        self.rb_panel.setEnabled(False)

        self.worker = OcrWorker(
            self, self.region_phys, self.origin, self.dpr,
            OCR_LANGS[self.cmb_ocr.currentText()],
            TARGET_LANGS[self.cmb_target.currentText()],
            mode, self.sld.value() / 10, self.chk_gpu.isChecked())
        self.worker.boxes.connect(lambda it: self.box_overlay and self.box_overlay.set_items(it))
        self.worker.pairs.connect(lambda ps: self.panel_overlay and self.panel_overlay.set_pairs(ps))
        self.worker.status.connect(self._status)
        self.worker.stopped.connect(self._on_stopped)
        self.worker.start()

        self.btn_toggle.setText("■  Durdur")
        self.btn_toggle.setObjectName("Danger")
        self.btn_toggle.setStyleSheet(self._qss())
        self.btn_region.setEnabled(False)

    def stop(self):
        if self.worker:
            self.worker.stop()
            self._status("Durduruluyor…")

    def _on_stopped(self):
        self.worker = None
        if self.box_overlay:
            self.box_overlay.clear(); self.box_overlay.hide()
        # not paneli açık kalsın (son çeviriler okunabilsin)
        self.btn_toggle.setText("▶  Çeviriyi Başlat")
        self.btn_toggle.setObjectName("Primary")
        self.btn_toggle.setStyleSheet(self._qss())
        self.btn_region.setEnabled(True)
        self.rb_box.setEnabled(True)
        self.rb_panel.setEnabled(True)
        self._status("Durduruldu.")

    def _status(self, msg, err=False):
        self.lbl_status.setText(f"● {msg}")
        self.lbl_status.setStyleSheet(f"color:{C.ERR if err else C.OK};")

    def closeEvent(self, e):
        if self.worker:
            self.worker.stop(); self.worker.wait(1000)
        for w in (self.box_overlay, self.panel_overlay):
            if w:
                w.close()
        e.accept()
        QApplication.instance().quit()   # kontrol paneli kapanınca uygulamadan çık


def main():
    crash_handler.install()   # global hata yakalayıcı (crash log + diyalog)
    _log.info("LensLingo v%s başlatılıyor", __version__)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("LensLingo")
    # Bölge seçerken panel gizlenince/overlay kapanınca uygulama kendiliğinden
    # kapanmasın; çıkışı yalnızca kontrol panelinin kapanması tetikler.
    app.setQuitOnLastWindowClosed(False)
    panel = ControlPanel()
    panel.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
