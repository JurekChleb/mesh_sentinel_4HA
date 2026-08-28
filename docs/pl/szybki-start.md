# Szybki start (PL)

Mesh Sentinel to lokalny „rejestrator lotu” sieci urządzeń: zbiera sygnały,
wykrywa incydent, buduje oś czasu i wskazuje prawdopodobną przyczynę wraz z
dowodami. **Niczego nie zmienia w sieci** — nie resetuje, nie paruje ponownie i
nie przełącza kanałów. Wersja 0.1.0 obsługuje wyłącznie Zigbee2MQTT.

Interfejs i dokumentacja techniczna są po angielsku; ten plik to skrót do
uruchomienia i przetestowania u siebie.

## Instalacja

1. **Ustawienia → Aplikacje → ⋮ → Repozytoria**.
2. Dodaj `https://github.com/JurekChleb/mesh_sentinel_4HA`.
3. Zainstaluj **Mesh Sentinel** i uruchom.
4. Otwórz z paska bocznego (działa przez Ingress — nie trzeba wystawiać portu).

Jeśli masz aplikację Mosquitto, adres brokera i hasło zostaną pobrane z
Supervisora automatycznie. Własny broker: wpisz `mqtt_host` w opcjach aplikacji —
wartość wpisana ręcznie zawsze ma pierwszeństwo.

Sprawdź, czy `z2m_base_topic` zgadza się z `mqtt.base_topic` w Zigbee2MQTT
(domyślnie `zigbee2mqtt`).

## Trzy ekrany

* **Overview** — ocena zdrowia wraz z uzasadnieniem, liczniki urządzeń, aktywne
  incydenty i lista urządzeń wymagających uwagi.
* **Incidents** — karty z osią czasu. Po otwarciu: co się wydarzyło, dlaczego
  łączymy te zdarzenia, czego nie wiemy, co zrobić, oraz porównanie
  **przed/po** (stan 15 minut przed awarią kontra stan po niej).
* **Device cockpit** — karta urządzenia: last seen, trend LQI, bateria, router
  nadrzędny, powiązane incydenty i zdarzenia, przycisk **mark as critical**.

## Najważniejsze progi

| Opcja | Domyślnie | Znaczenie |
| --- | --- | --- |
| `offline_grace_seconds` | 180 | Ile urządzenie musi być niedostępne, zanim powstanie incydent. To ta jedna wartość chroni przed fałszywym alarmem przy krótkim restarcie |
| `mains_stale_minutes` | 90 | Budżet ciszy dla urządzenia zasilanego z sieci |
| `battery_stale_hours` | 24 | Budżet ciszy dla urządzenia bateryjnego |
| `topology_active_scan` | false | Aktywne skanowanie mapy sieci. **Obciąża mesh**, dlatego domyślnie wyłączone |

Snapshot topologii co 15 minut jest **pasywny** — zapisuje stan, który
Zigbee2MQTT i tak publikuje, i nie generuje ruchu w sieci. Aktywne skanowanie
(przycisk **Network map** lub `topology_active_scan`) zapisuje realne powiązania
router–urządzenie; reguła routera podaje wtedy wyższą pewność, a bez nich sama
przyznaje, że powiązanie wynika tylko z czasu.

## Testy u siebie

Pełny plan (7 testów odwracalnych, z tabelą do wypełnienia) jest w
[docs/testing.md](../testing.md). Skrót:

1. restart Z2M → jeden incydent `service_restart`, poziom **warning**;
2. restart aplikacji → brak nowego incydentu, historia zachowana;
3. odłączenie routera Zigbee → jeden `router_failure` ze wskazaniem routera;
4. wyjęcie baterii z czujnika → jeden `device_offline` tylko dla niego;
5. brak koordynatora USB po restarcie VMware → jeden `coordinator_unavailable`
   wskazujący na host/USB, **nie** na awarię Zigbee i **nie** po jednym
   incydencie na urządzenie;
6. urządzenie poza zasięgiem i z powrotem → `device_degraded`, potem recovery;
7. krótki restart (poniżej 2 minut) → **brak incydentu**.

Dla każdego testu zapisz: faktyczny przebieg, wniosek aplikacji, liczbę
fałszywych alarmów i brakujące dane.

Test 4 przyspieszysz, ustawiając tymczasowo `battery_stale_hours` na `1` —
zanotuj to w wynikach.

## Gdzie są surowe dane

Baza SQLite: `/data/mesh_sentinel.db`. Ten sam strumień przez API:
`GET /api/events?limit=2000`. Każdy incydent da się odtworzyć ze zdarzeń,
ponieważ silnik korelacji jest deterministyczną funkcją strumienia zdarzeń i
znacznika czasu.

Dane nie opuszczają Home Assistanta: brak telemetrii, brak konta, brak chmury.
