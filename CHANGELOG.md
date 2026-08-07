# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir ve
[Semantic Versioning](https://semver.org/lang/tr/) izler.

## [Unreleased]

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
