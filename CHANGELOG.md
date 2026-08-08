# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir ve
[Semantic Versioning](https://semver.org/lang/tr/) izler.

## [Unreleased]

## [0.1.2] - 2026-08-08
### Added
- Yeni **Not modu** (varsayılan): ekranın sağında, yarı saydam, Yapışkan Notlar
  tarzı panel. Bulunan her yazı parçası ayrı kart olur (orijinal + altında çeviri).

### Changed
- Kutu modu ikincil/deneysel seçenek oldu.

### Fixed
- Kendi çevirimizi ekrandan tekrar okuyup çevirme (geri besleme döngüsü) önlendi.
- Boş/geçici taramalarda içerik kaybolmuyor; yalnızca değişiklik onaylanınca güncelleniyor.
- "Durdur" artık anında tepki veriyor (uzun bekleme parçalara bölündü).
- Çalışırken mod kilitleniyor; mod değişince diğer modun paneli ekranda kalmıyor.

## [0.1.1] - 2026-08-08
### Added
- Açılışta arka planda otomatik güncelleme kontrolü (GitHub Releases) bağlandı;
  yeni sürüm varsa indirip kuran diyalog gösterilir (`updater.py`).
- Kullanıcı ayarları için `cfg.py` (settings.json) eklendi.
- Global crash handler ve loglama ana uygulamaya bağlandı.

### Fixed
- Bölge seçildikten sonra uygulamanın kapanması düzeltildi (Qt
  `quitOnLastWindowClosed` tuzağı; çıkış artık yalnızca kontrol paneli
  kapanınca tetikleniyor). Bölge seçici yeniden tasarlandı.

## [0.1.0] - 2026-08-08
### Added
- İlk sürüm — LensLingo iskelesi (updater, logger, crash handler, installer hattı).
