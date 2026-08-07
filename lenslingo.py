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
                             QGraphicsDropShadowEffect)

# ---- Ağır import tembel yüklenir (uygulama hızlı açılsın diye) ----
try:
    from deep_translator import GoogleTranslator
except Exception:  # pragma: no cover
    GoogleTranslator = None


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
    text    = pyqtSignal(str)    # panel modu için birleşik çeviri
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

                dets = []
                for det in results:
                    bbox, txt = det[0], det[1]
                    conf = det[2] if len(det) > 2 else 1.0
                    txt = (txt or "").strip()
                    if txt and conf >= 0.35:
                        dets.append((bbox, txt))

                if self.mode == "box":
                    self._emit_boxes(dets, translator)
                else:
                    self._emit_panel(dets, translator)

                time.sleep(max(0.0, self.interval - (time.time() - t0)))
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
            items.append((x1, y1, x2, y2, self._translate(translator, txt)))
        self.boxes.emit(items)
        self.status.emit(f"{len(items)} metin çevrildi", False)

    def _emit_panel(self, dets, translator):
        text = " ".join(t for _, t in dets).strip()
        if not text or text == self._last_sig:
            return
        self._last_sig = text
        self.text.emit(self._translate(translator, text))
        self.status.emit("Çeviriliyor…", False)


# ============================ Bölge seçici ================================
class RegionSelector(QWidget):
    picked = pyqtSignal(int, int, int, int)  # logical: left, top, w, h

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._start = None
        self._end = None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        p.setPen(QPen(QColor(C.TEXT), 1))
        p.setFont(QFont("Segoe UI", 15, QFont.Weight.DemiBold))
        p.drawText(QRect(0, 30, self.width(), 40),
                   Qt.AlignmentFlag.AlignHCenter,
                   "Çevrilecek alanı fareyle sürükleyerek seç   ·   ESC = iptal")
        if self._start and self._end:
            r = QRect(self._start, self._end).normalized()
            # seçili alanı temizle (delik efekti)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(r, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(C.BOX), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)

    def mousePressEvent(self, e):
        self._start = e.position().toPoint()
        self._end = self._start

    def mouseMoveEvent(self, e):
        self._end = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):
        self._end = e.position().toPoint()
        r = QRect(self._start, self._end).normalized()
        self.close()
        if r.width() > 10 and r.height() > 10:
            self.picked.emit(r.left(), r.top(), r.width(), r.height())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()


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


# ============================ Panel overlay ==============================
class PanelOverlay(QWidget):
    """Sürüklenebilir, kenarlıksız tek çeviri paneli."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setStyleSheet(f"""
            QWidget {{ background:#0d1b2a; border:1px solid {C.ACCENT};
                       border-radius:10px; }}
            QLabel  {{ color:#ffffff; font:600 15px 'Segoe UI'; border:none; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.label = QLabel("(çeviri burada görünecek)")
        self.label.setWordWrap(True)
        lay.addWidget(self.label)
        self.resize(480, 90)
        self._drag = None

    def set_text(self, t):
        self.label.setText(t)

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)


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

        self.setWindowTitle("LensLingo")
        self.setMinimumWidth(400)
        self.setStyleSheet(self._qss())
        self._build()

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
        self.rb_box = QRadioButton("🔲  Kutu modu — her yazıyı işaretle, altına çevir")
        self.rb_panel = QRadioButton("🪟  Panel modu — hepsini tek pencerede göster")
        self.rb_box.setChecked(True)
        self.grp.addButton(self.rb_box); self.grp.addButton(self.rb_panel)
        v2.addWidget(self.rb_box); v2.addWidget(self.rb_panel)
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
        self._sel.destroyed.connect(self.show)
        self._sel.show()

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
            if self.box_overlay is None:
                self.box_overlay = BoxOverlay()
            self.box_overlay.clear(); self.box_overlay.show()
        else:
            if self.panel_overlay is None:
                self.panel_overlay = PanelOverlay()
            lx, ly = self.origin
            self.panel_overlay.move(lx, ly + self.region_phys["height"] // int(self.dpr) + 12)
            self.panel_overlay.show()

        self.worker = OcrWorker(
            self, self.region_phys, self.origin, self.dpr,
            OCR_LANGS[self.cmb_ocr.currentText()],
            TARGET_LANGS[self.cmb_target.currentText()],
            mode, self.sld.value() / 10, self.chk_gpu.isChecked())
        self.worker.boxes.connect(lambda it: self.box_overlay and self.box_overlay.set_items(it))
        self.worker.text.connect(lambda t: self.panel_overlay and self.panel_overlay.set_text(t))
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

    def _on_stopped(self):
        self.worker = None
        if self.box_overlay:
            self.box_overlay.clear()
        self.btn_toggle.setText("▶  Çeviriyi Başlat")
        self.btn_toggle.setObjectName("Primary")
        self.btn_toggle.setStyleSheet(self._qss())
        self.btn_region.setEnabled(True)
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


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("LensLingo")
    panel = ControlPanel()
    panel.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
