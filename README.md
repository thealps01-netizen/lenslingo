# LensLingo

**Canlı Ekran Çevirmeni.** Ekranda seçtiğin bir bölgeyi gerçek zamanlı izler, içindeki **her metin bloğunu**
**EasyOCR** ile bulur, etrafını bir kutu ile işaretler ve çeviriyi tam o metnin
altına yazar. Modern **PyQt6** arayüzü ve gerçek şeffaf, tıklama-geçirgen overlay.

> Akış: **Ekran bölgesi → EasyOCR (kutular + metin) → Google Translate → Ekrana çizim**

## Özellikler
- 🔲 **Kutu modu** — ekrandaki her yazıyı bulur, etrafını işaretler ve çeviriyi
  hemen altına yazar (oyun/uygulama arkada görünmeye devam eder).
- 🪟 **Panel modu** — tüm çeviriyi sürüklenebilir tek bir pencerede gösterir.
- 🎨 Modern, koyu temalı, anlaşılır seçimli PyQt6 arayüzü.
- 🧠 EasyOCR ile yerel OCR (GPU/CUDA destekli).
- 🌐 Google Translate ile otomatik dil algılama (API anahtarı gerekmez).
- ⚡ Aynı metni tekrar çevirmeyi önleyen önbellek + ayarlanabilir tarama aralığı.

## Kurulum & Çalıştırma

En kolay yol — `run.bat` dosyasına çift tıkla. İlk çalıştırmada sanal ortam kurar ve
bağımlılıkları (PyQt6 + torch + easyocr dahil, ~birkaç yüz MB) indirir.

Ya da elle:

```bash
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python translator_app.py
```

## Kullanım
1. **Ekranda Bölge Seç** → çevrilecek yazının olduğu alanı fareyle sürükle.
2. **Görünüm** modunu seç: Kutu modu (her yazının altına çeviri) ya da Panel modu.
3. **Ekran dili** (metnin dili) ve **Çeviri dili**ni seç.
4. **Çeviriyi Başlat**. Kutu modunda her metin işaretlenip altına çevrilir.

## Notlar
- **Ekran dili** = ekrandaki metnin hangi karakter setiyle okunacağı (ör. İngilizce,
  Japonca). Çeviri kaynağı ayrıca otomatik algılanır.
- İlk `EasyOCR` başlatması model indirir/yükler; birkaç saniye sürebilir.
- GPU yoksa otomatik olarak CPU'ya düşer (daha yavaş ama çalışır).
- Kutu overlay Windows'ta tıklama-geçirgendir; alttaki oyun/uygulama etkilenmez.
- Google Translate ücretsiz uç noktası aşırı istekte geçici sınırlayabilir;
  tarama aralığını 1 sn veya üzerinde tutmak sağlıklıdır.

## Bağımlılıklar
`PyQt6`, `easyocr`, `mss`, `deep-translator`, `numpy` — tümü `requirements.txt` içinde.
