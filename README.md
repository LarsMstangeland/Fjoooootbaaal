# ticket-listener

`uv`-drevet Python-boilerplate for aa lytte etter at fotballbilletter aapner for salg.

Den trygge standarden er: poll billettsiden, oppdag tilgjengelighet med regex, send varsel, og aapne siden i nettleseren din. Den omgar ikke kosystemer, CAPTCHA, innlogging eller betaling.

## Kom i gang

1. Installer `uv` hvis du ikke har det: <https://docs.astral.sh/uv/>.
2. Kopier `config.example.toml` til `config.toml`.
3. Endre `url`, `available_regex` og `sold_out_regex` for billettsiden du vil folge.
4. Kjor:

```powershell
uv run python -m ticket_listener.cli --config config.toml
```

Valider konfigurasjonen uten aa starte lytteren:

```powershell
uv run python -m ticket_listener.cli --config config.toml --check-config
```

Legg til en bruker som skal varsles paa telefon:

```powershell
uv run python -m ticket_listener.cli --config config.toml --add-subscriber "+4712345678" --subscriber-name "Lars"
```

List brukere:

```powershell
uv run python -m ticket_listener.cli --config config.toml --list-subscribers
```

Varslingslenken bygges som en prefilled form-lenke. Naar Fotballfesten-siden viser en
Fanparks booking-lenke, sendes den videre med query-parametre for `phone`, `name`,
`target`, `ticket_url`, `event`, `venue`, `quantity` og `guests`.

## Kjore i bakgrunnen paa Windows

Start skjult i bakgrunnen:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-background.ps1
```

Installer som Scheduled Task ved innlogging:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-task.ps1
```

Avinstaller tasken:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-windows-task.ps1
```

Logger skrives til `logs/ticket-listener.log` naar du bruker bakgrunnsskriptet.

## Konfigurasjon

`available_regex` bor vaere noe konkret som bare finnes naar kjop faktisk er mulig, for eksempel tekst paa en kjopsknapp. `sold_out_regex` brukes for aa undertrykke falske positiver naar siden fremdeles sier utsolgt.

Du kan legge inn flere `[[targets]]` for flere kamper eller klubber.

## Viktig

Sjekk vilkaarene til billettleverandoren for du bruker dette. Mange leverandorer forbyr automatisering. Denne boilerplaten er laget for personlig varsling og rask manuell handling, ikke for aa bryte koer eller automatisere betaling.
