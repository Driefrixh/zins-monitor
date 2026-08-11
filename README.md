# Zins-Monitor

Tägliches Update zur Zinsentwicklung — ohne Server, ohne laufende Kosten.

- **GitHub Action** holt werktäglich die Zinsstrukturkurve der EZB, schreibt sie ins Repo und schickt eine Push-Nachricht über ntfy.
- **Scriptable-Widget** liest dieselben Daten und zeigt sie auf dem iPhone-Homescreen.

```
zins-monitor/
├── .github/workflows/zins-update.yml   Cron-Job (werktags 17:10 MESZ)
├── scripts/fetch_rates.py              Abruf, Auswertung, ntfy-Push  
├── scriptable/ZinsWidget.js            iOS-Widget
└── data/                               wird automatisch befüllt
    ├── latest.json                     aktuelle Werte + Sparkline
    ├── history.csv                     wachsende Zeitreihe
    └── state.json                      zuletzt gemeldeter Handelstag
```

## Datenquelle

EZB Data Portal, Dataflow `YC` (Zinsstrukturkurve), Serien
`B.U2.EUR.4F.G_N_A.SV_C_YM.SR_{2Y,5Y,10Y,30Y}` — nominale Staatsanleihen
des Euroraums mit Triple-A-Rating. Das ist praktisch die Bundkurve,
kostenlos, ohne API-Key, werktäglich aktualisiert.

Gemeldet werden: aktueller Stand, Veränderung zum Vortag sowie zu
1 Woche / 1 Monat / 3 Monaten / 1 Jahr, jeweils in Basispunkten.
Bei einer Tagesbewegung ab 10 Bp wird die Nachricht als Alarm
mit Priorität 4 (Ton und Vibration) zugestellt — sonst mit
Priorität 2, also leise in der Mitteilungszentrale.

## Einrichtung

### 1. Repository

Neues **öffentliches** Repo `zins-monitor` anlegen und diese Dateien
hineinlegen. Öffentlich, damit das Widget die `latest.json` ohne Token
lesen kann (die Daten sind ohnehin öffentlich) und damit die Action
unbegrenzt kostenlose Minuten hat.

Anschließend unter **Settings → Actions → General → Workflow permissions**
die Option *Read and write permissions* aktivieren, damit der Job die
Daten zurück ins Repo committen darf.

### 2. ntfy einrichten

ntfy braucht keinen Account. Du denkst dir einen geheimen Themennamen
aus — er ist gleichzeitig Adresse und Passwort, also **nicht** `zinsen`,
sondern etwas Unratbares wie `zins-d4k9x2mq-7fp`.

1. App **ntfy** aus dem App Store laden und öffnen.
2. Auf **+** tippen, den Themennamen exakt eintragen, **Subscribe**.
   Beim ersten Mal Benachrichtigungen erlauben.
3. Im Repo unter **Settings → Secrets and variables → Actions →
   New repository secret** anlegen:

| Name         | Wert                    |
|--------------|-------------------------|
| `NTFY_TOPIC` | dein Themenname         |

Optional, nur bei eigenem Server oder reserviertem Topic:
`NTFY_SERVER` (Standard `https://ntfy.sh`) und `NTFY_TOKEN`.

Zum Testen ohne GitHub genügt ein Terminal-Befehl:

```bash
curl -d "Test" https://ntfy.sh/dein-themenname
```

Kommt die Meldung auf dem iPhone an, ist alles richtig eingerichtet.

### 3. Erster Lauf

Unter **Actions → Zins-Update → Run workflow** manuell starten.
Danach sollte `data/latest.json` im Repo liegen und die erste Nachricht
auf dem iPhone angekommen sein.

### 4. Widget

1. **Scriptable** aus dem App Store installieren.
2. Neues Skript anlegen, Inhalt von `scriptable/ZinsWidget.js` einfügen.
3. Ganz oben `GITHUB_USER` auf den eigenen Namen setzen
   (und `GITHUB_REPO` / `GITHUB_BRANCH`, falls abweichend).
4. Auf dem Homescreen lange drücken → **+** → *Scriptable* → Widget-Größe
   wählen → Widget antippen → *Script* = dieses Skript,
   *When Interacting* = *Run Script*.

Small, Medium und Large werden unterstützt. Farben aus Kreditnehmersicht:
Rot = Zinsen gestiegen, Grün = gefallen.

## Anpassen

| Was | Wo |
|---|---|
| Uhrzeit des Laufs | `cron` in `zins-update.yml` (UTC!) |
| Alarmschwelle | `ALERT_BP` in `zins-update.yml` |
| Laufzeiten | `SERIES` in `fetch_rates.py` |
| Vergleichszeiträume | `HORIZONS` in `fetch_rates.py` |
| Länge der Sparkline | `SPARK_POINTS` in `fetch_rates.py` |

## Hinweise

- Geplante GitHub-Läufe starten nicht auf die Minute genau; Verzögerungen
  von einigen Minuten bis Stunden sind normal und bei Tagesdaten egal.
- Workflows in Repos ohne Aktivität werden nach 60 Tagen deaktiviert.
  Da hier täglich committet wird, tritt das nicht ein.
- An Feiertagen liefert die EZB keinen neuen Wert. Das Skript erkennt das
  über `state.json` und verschickt dann keine zweite Nachricht.
- `history.csv` wächst über die von der API gelieferten ~430 Tage hinaus,
  weil bestehende Zeilen bei jedem Lauf zusammengeführt werden.

## Lokal testen

```bash
python3 scripts/fetch_rates.py
```

Ohne gesetzte Umgebungsvariable `NTFY_TOPIC` wird die Nachricht nur
auf der Konsole ausgegeben — praktisch zum Testen der Formatierung.
