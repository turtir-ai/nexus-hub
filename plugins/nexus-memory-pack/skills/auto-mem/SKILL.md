---
name: auto-mem
description: Otomatik hafıza güncelleme - Her önemli işlemi hafızaya kaydeder
---

## Otomatik Hafıza Sistemi

Her oturumda otomatik olarak:
1. Session başlangıcını loglar
2. Önemli işlemleri kaydeder
3. Session sonunu loglar
4. Global memory'yi günceller

## Kullanım

```
/auto-mem "işlem açıklaması"
```

## Otomatik Kayıt Zamanları

Aşağıdaki durumlarda otomatik hafıza güncellemesi yap:
- ✅ Yeni test tamamlandığında
- ✅ Yeni hata pattern'ı bulunduğunda
- ✅ Yeni çözüm bulunduğunda
- ✅ Önemli bir karar alındığında
- ✅ Proje milestone'ı tamamlandığında

## Güncelleme Formatı

```markdown
### [İşlem Adı] (2026-02-06)
- **Zaman:** HH:MM
- **İşlem:** Ne yapıldı
- **Sonuç:** Ne çıktı
- **Dosyalar:** Etkilenen dosyalar
```

## Otomatik Log Konumu

```
~/.claude/logs/
├── sessions.log           # Tüm session'lar
└── session_YYYYMMDD_HHMMSS.md  # Session detayları
```

## Global Memory Güncelleme

Önemli olaylar için global memory'yi otomatik güncelle:
```bash
# Önerilen: nexus_mem ile yaz (memory_bank otomatik kompakt kalır)
python3 ~/.claude/nexus_mem.py remember --scope global --category learning --tags "nexus" --refs "path/to/file.py" "Kısa özet + verify cmd"

# Detay/kanıt için proje hafızasına yaz (repo içinde kalır)
mkdir -p ./.claude/memory
echo "### [LEARNING] ($(date +%F))" >> ./.claude/memory/MEMORY.md
echo "- **Detay:** ..." >> ./.claude/memory/MEMORY.md
```

## Hook Tabanli Otomatik Notlar

Claude Code PostToolUse hook'lari ile "tool fail" olaylari otomatik olarak `notes.jsonl` icine yazilabilir:

```bash
python3 ~/.claude/nexus_mem.py remember-hook --no-rebuild
```

Bu, sadece hata/exit_code != 0 gibi durumlarda kisa bir `tool_error` notu ekler (memory_bank sismez).
