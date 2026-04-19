# Translation Guide
A complete beginner-friendly guide for creating and maintaining `.lng` language files.

## 1. What This System Does
The game loads translations from files in the `langs` folder.

- Each language file uses the `.lng` extension.
- English is built into the game by default.
- Players can switch language in `Options -> Language`.
- If a line is missing in your language file, the game shows the original English text.

## 2. File Location and Naming
Put your translation file inside:

- `langs/`

Examples:

- `turkish.lng`
- `spanish.lng`
- `french.lng`

Use lowercase names when possible.

## 3. Required Line Format
Each translation entry must be exactly this format:

`English text [=] Your translation`

Rules:

- Keep one space before and after `[=]`.
- Left side is the original key.
- Right side is your translated output.

Example:

`Settings [=] Ayarlar`

## 4. Comments
Lines that start with `;` are comments and ignored by the game.

Example:

`; --------------------`
`; MENU`
`; --------------------`

## 5. Case-Insensitive Matching
Key matching is case-insensitive.

`hello`, `Hello`, and `HELLO` match the same entry.

Best practice: still write keys exactly as they appear in game strings.

## 6. Parameters (`%1`, `%2`, ... `%9`)
Some lines include dynamic values.

Example key:

`Score: %1`

Your translation must keep `%1`.

Correct:

`Score: %1 [=] Skor: %1`

You may reorder placeholders if grammar requires it.

Example:

`Buy Hoverboard   Cost: %1 Coins   Owned: %2   Max Buy: %3 [=] Hoverboard Satın Al   Bedel: %1 Coin   Sahip: %2   Azami Alım: %3`

Do not remove placeholders.

## 7. Translated Parameters (`%t1`, `%t2`, ...)
`%t1` means the inserted value should be translated first if possible.

Important rule:

- Left side can contain `%t1`.
- Right side should use `%1` (not `%t1`).

Example:

`north [=] kuzey`
`You are moving %t1. [=] %1 yönüne ilerliyorsun.`

Runtime:

- Input: `You are moving north.`
- Output: `kuzey yönüne ilerliyorsun.`

## 8. Step-by-Step Workflow
1. Create a new file in `langs/`.
2. Add basic UI entries first (`Back`, `Yes`, `No`, menu labels).
3. Add gameplay-critical lines (warnings, failures, rewards).
4. Add `%1/%2` parameter lines.
5. Add `%t1` helper lines (directions/states).
6. Save file as UTF-8.
7. Start game and select your language.
8. Review menus and gameplay; patch missing lines.

## 9. UTF-8 Requirements
Your file must be UTF-8 encoded.

Use proper native letters. Do not replace letters with `?`.

Bad:

`Magaza`

Good:

`Mağaza`

## 10. What Not to Translate
Usually keep these unchanged unless clearly user-facing:

- File names (`.mp3`, `.wav`, `.json`)
- Regex patterns
- Internal keys with underscores
- Protocol/identifier strings

Translate user-facing labels, spoken text, menu text, prompts, and descriptions.

## 11. Common Mistakes
Wrong separator:

`Settings[=]Ayarlar`

Correct:

`Settings [=] Ayarlar`

Missing placeholder:

`Score: %1 [=] Skor:`

Correct:

`Score: %1 [=] Skor: %1`

Wrong `%t` use:

`You are moving %t1. [=] %t1 yönüne ilerliyorsun.`

Correct:

`You are moving %t1. [=] %1 yönüne ilerliyorsun.`

## 12. Quality Checklist
Before release, check:

- Every entry uses ` [=] ` format.
- No broken characters.
- Placeholders are preserved.
- `%t` lines are correctly written.
- Important prompts are short and clear.
- Tone is consistent across menus and gameplay.

## 13. Minimal Starter Template
```lng
; CORE UI
Back [=] Geri
Yes [=] Evet
No [=] Hayır
Settings [=] Ayarlar
Options [=] Seçenekler
Exit [=] Çıkış

; GAMEPLAY
Game Over. [=] Oyun bitti.
Score: %1 [=] Skor: %1
Play Time: %1 [=] Oyun Süresi: %1

; %t SUPPORT
left [=] sol
right [=] sağ
turn left [=] sola geç
```

## 14. Troubleshooting
Language does not appear:

- Ensure file is in `langs/`
- Ensure extension is `.lng`
- Restart game if needed

Text stays English:

- Entry is missing
- Key does not match
- Text may be internal/non-user-facing

Broken characters:

- Re-save file as UTF-8
- Fix affected lines directly

## 15. Full Real Examples From This Game
Use this section as a direct reference. The lines below are taken from this game context and ready to adapt for your language.

### 15.1 Core Menu and Navigation
```lng
Main Menu [=] Ana Menü
Main Menu   Version: %1 [=] Ana Menü   Sürüm: %1
Start Game [=] Oyunu Başlat
Events [=] Etkinlikler
Missions [=] Görevler
Me [=] Ben
Shop [=] Mağaza
Leaderboard [=] Liderlik Tablosu
Options [=] Seçenekler
How to Play [=] Nasıl Oynanır
Learn Game Sounds [=] Oyun Seslerini Öğren
Check for Updates [=] Güncellemeleri Kontrol Et
What's New [=] Yenilikler
Exit [=] Çıkış
Back [=] Geri
Yes [=] Evet
No [=] Hayır
```

### 15.2 Options and Settings
```lng
SFX Volume: %1 [=] SFX Ses Düzeyi: %1
Music Volume: %1 [=] Müzik Ses Düzeyi: %1
Check for Updates on Startup: %1 [=] Açılışta Güncelleme Kontrolü: %1
Output Device: %1 [=] Çıkış Aygıtı: %1
Menu Sound HRTF: %1 [=] Menü Sesi HRTF: %1
Menu Wrap: %1 [=] Menü Sarma: %1
Speech: %1 [=] Konuşma: %1
SAPI Settings [=] SAPI Ayarları
SAPI Speech: %1 [=] SAPI Konuşması: %1
SAPI Volume: %1 [=] SAPI Ses Düzeyi: %1
SAPI Voice: %1 [=] SAPI Ses: %1
SAPI Rate: %1 [=] SAPI Hızı: %1
SAPI Pitch: %1 [=] SAPI Perdesi: %1
Difficulty: %1 [=] Zorluk: %1
Language: %1 [=] Dil: %1
Main Menu Descriptions: %1 [=] Ana Menü Açıklamaları: %1
Set User Name [=] Kullanıcı Adı Belirle
Gameplay Announcements [=] Oyun İçi Duyurular
Controls [=] Kontroller
Purchase Confirmation: %1 [=] Satın Alma Onayı: %1
Exit Confirmation: %1 [=] Çıkış Onayı: %1
```

### 15.3 Difficulty, Status, and Labels
```lng
Easy [=] Kolay
Normal [=] Normal
Hard [=] Zor
All Difficulties [=] Tüm Zorluklar
Easy Only [=] Yalnızca Kolay
Normal Only [=] Yalnızca Normal
Hard Only [=] Yalnızca Zor
Unknown Difficulty [=] Bilinmeyen Zorluk
Unknown [=] Bilinmiyor
Weekly Season [=] Haftalık Sezon
Verified [=] Doğrulanmış
Suspicious [=] Şüpheli
```

### 15.4 Game Over and Run Summary
```lng
Game Over [=] Oyun Bitti
Game Over. [=] Oyun bitti.
Run again [=] Tekrar Koş
Main menu [=] Ana menü
Score: %1 [=] Skor: %1
Play Time: %1 [=] Oyun Süresi: %1
Death reason: %1 [=] Ölüm nedeni: %1
Run ended after crash [=] Koşu çarpışma sonrası sona erdi
%1 copied to clipboard. [=] %1 panoya kopyalandı.
```

### 15.5 Shop and Upgrades
```lng
Buy Hoverboard   Cost: %1 Coins   Owned: %2   Max Buy: %3 [=] Hoverboard Satın Al   Bedel: %1 Coin   Sahip: %2   Azami Alım: %3
Open Mystery Box   Cost: %1 Coins   Max Buy: %2 [=] Gizemli Kutu Aç   Bedel: %1 Coin   Azami Alım: %2
Buy Headstart   Cost: %1 Coins   Owned: %2   Max Buy: %3 [=] Headstart Satın Al   Bedel: %1 Coin   Sahip: %2   Azami Alım: %3
Buy Score Booster   Cost: %1 Coins   Owned: %2   Max Buy: %3 [=] Skor Artırıcı Satın Al   Bedel: %1 Coin   Sahip: %2   Azami Alım: %3
Free Daily Gift   Available [=] Günlük Ücretsiz Hediye   Uygun
Free Daily Gift   Claimed [=] Günlük Ücretsiz Hediye   Alındı
Item Upgrades   Maxed: %1/%2 [=] Eşya Geliştirmeleri   Azami: %1/%2
Character Upgrades   Active: %1 [=] Karakter Geliştirmeleri   Aktif: %1
Status: %1   Level %2/%3 [=] Durum: %1   Seviye %2/%3
Perk: %1 [=] Yetenek: %1
Set as Active Character [=] Aktif Karakter Yap
Set as Active Board [=] Aktif Tahta Yap
```

### 15.6 Missions, Events, and Progress
```lng
Missions %1/3 [=] Görevler %1/3
Mission set complete. Super Mystery Box. [=] Görev seti tamamlandı. Süper Gizemli Kutu.
Quest Meter: %1/%2 [=] Görev Sayacı: %1/%2
Claim Reward [=] Ödülü Al
Claimed [=] Alındı
Daily Event [=] Günlük Etkinlik
Daily High Score [=] Günlük En Yüksek Skor
Coin Meter [=] Coin Sayacı
Daily Login Calendar [=] Günlük Giriş Takvimi
Word Hunt [=] Kelime Avı
Season Hunt [=] Sezon Avı
Season Ends In: %1 [=] Sezonun Bitmesine: %1
Season Reward: %1. %2 [=] Sezon Ödülü: %1. %2
Season: Loading current week [=] Sezon: Bu hafta yükleniyor
```

### 15.7 Update and Error Messages
```lng
Open Release Page [=] Sürüm Sayfasını Aç
Starting update download. [=] Güncelleme indirilmeye başlanıyor.
Downloading update package. %1 percent. [=] Güncelleme paketi indiriliyor. Yüzde %1.
Extracting update package. [=] Güncelleme paketi çıkarılıyor.
Extracting update package. %1 percent. [=] Güncelleme paketi çıkarılıyor. Yüzde %1.
Installing Update... [=] Güncelleme kuruluyor...
Update installed. Restart the game to finish applying it. [=] Güncelleme kuruldu. Uygulamanın tamamlanması için oyunu yeniden başlatın.
Restart Game [=] Oyunu Yeniden Başlat
You already have the latest version. [=] Zaten en son sürümü kullanıyorsunuz.
Version %1 is available. [=] %1 sürümü kullanılabilir.
No published releases were found. [=] Yayınlanmış sürüm bulunamadı.
Unable to contact GitHub Releases. [=] GitHub Releases hizmetine ulaşılamadı.
Update check failed with HTTP %1. [=] Güncelleme kontrolü HTTP %1 hatasıyla başarısız oldu.
Unable to download the update package. [=] Güncelleme paketi indirilemedi.
Unable to extract the update package. [=] Güncelleme paketi çıkarılamadı.
```

### 15.8 Runtime Action Prompts
```lng
jump now [=] şimdi zıpla
roll now [=] şimdi yuvarlan
turn left now [=] şimdi sola geç
turn right now [=] şimdi sağa geç
turn left [=] sola geç
turn right [=] sağa geç
```

### 15.9 `%1/%2` Parameter Examples
```lng
Main Menu   Version: %1 [=] Ana Menü   Sürüm: %1
SFX Volume: %1 [=] SFX Ses Düzeyi: %1
Music Volume: %1 [=] Müzik Ses Düzeyi: %1
Output Device: %1 [=] Çıkış Aygıtı: %1
Difficulty: %1 [=] Zorluk: %1
Language: %1 [=] Dil: %1
Score: %1 [=] Skor: %1
Play Time: %1 [=] Oyun Süresi: %1
Death reason: %1 [=] Ölüm nedeni: %1
Downloading update package. %1 percent. [=] Güncelleme paketi indiriliyor. Yüzde %1.
Extracting update package. %1 percent. [=] Güncelleme paketi çıkarılıyor. Yüzde %1.
Version %1 is available. [=] %1 sürümü kullanılabilir.
Buy Hoverboard   Cost: %1 Coins   Owned: %2   Max Buy: %3 [=] Hoverboard Satın Al   Bedel: %1 Coin   Sahip: %2   Azami Alım: %3
Buy Score Booster   Cost: %1 Coins   Owned: %2   Max Buy: %3 [=] Skor Artırıcı Satın Al   Bedel: %1 Coin   Sahip: %2   Azami Alım: %3
Open Mystery Box   Cost: %1 Coins   Max Buy: %2 [=] Gizemli Kutu Aç   Bedel: %1 Coin   Azami Alım: %2
Quest Meter: %1/%2 [=] Görev Sayacı: %1/%2
Missions %1/3 [=] Görevler %1/3
Season Ends In: %1 [=] Sezonun Bitmesine: %1
Season Reward: %1. %2 [=] Sezon Ödülü: %1. %2
%1 copied to clipboard. [=] %1 panoya kopyalandı.
```

### 15.10 `%t1/%t2` Translated-Parameter Examples
```lng
The current shipped game text is mainly `%1/%2` based.
If you add `%t` entries later, still follow the same rule:
- `%t1` can appear only on the left key
- `%1` must be used on the right translation
```

### 15.11 Input and Control Text
```lng
Use %1/%2, %3 to select, %4 to go back. [=] %1/%2 ile gez, %3 ile seç, %4 ile geri dön.
Adjust values with %1/%2. [=] Değerleri %1/%2 ile ayarla.
Press Enter to play the selected game sound. [=] Seçili oyun sesini çalmak için Enter tuşuna bas.
Select a sound to hear its gameplay cue. [=] Oyun içi ipucunu duymak için bir ses seç.
Press a button or stick direction on the %1 for %2. Press Escape to cancel. [=] %2 için %1 üzerinde bir tuşa veya analog yönüne bas. İptal etmek için Escape tuşuna bas.
Use %1 and %2 to change lanes. Press %3 to jump, %4 to roll, %5 to activate a hoverboard, %6 to pause, and %7 to toggle speech. On keyboard, press R to hear coins and T to hear play time. [=] Şerit değiştirmek için %1 ve %2 tuşlarını kullan. Zıplamak için %3, yuvarlanmak için %4, hoverboard etkinleştirmek için %5, duraklatmak için %6 ve konuşmayı aç/kapatmak için %7 tuşuna bas. Klavyede coin sayısını duymak için R, oyun süresini duymak için T tuşuna bas.
```
