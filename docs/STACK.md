# Стенд: компоненты, запуск, диагностика

## Что где (Mac, `ssh <MAC_USER>@<MAC_HOST>`)
PATH: `export PATH=$HOME/ios-qa/tools/node/bin:$HOME/ios-qa/tools/npm/bin:$PATH` и `export APPIUM_HOME=$HOME/ios-qa/tools/appium`.

| Компонент | Что делает | Порт / файл | Лог |
|---|---|---|---|
| `ios runwda` (go-ios) | запускает WebDriverAgent на телефоне | — | `/tmp/wda.log` |
| `ios forward 8100 8100` | пробрасывает WDA на Mac | 127.0.0.1:8100 | `/tmp/fwd.log` |
| `mitmdump` + `~/ios-qa/qa_addon.py` | прокси-сниффер | :8080 | `/tmp/mitm.log` |
| `appium` | сервер Appium (xcuitest) | 127.0.0.1:4723 | `/tmp/appium.log` |
| `appium-mcp` | MCP-сервер (stdio) для агента | запускается клиентом | — |

Телефон: свой iPhone (UDID в `config.env`). Wi-Fi прокси на телефоне: `<IP_MAC>:<PROXY_PORT>`, CA mitmproxy установлен и включён как доверенный (см. README).
Копии скриптов на Mac: `~/ios-qa/mac_start_stack.sh`, `~/ios-qa/mac_health.sh`, `~/ios-qa/config.env` (исходники в `scripts/`).

## Проверка и запуск
```
ssh <MAC_USER>@<MAC_HOST> 'zsh ~/ios-qa/mac_health.sh'        # OK/FAIL по каждому компоненту
ssh <MAC_USER>@<MAC_HOST> 'zsh ~/ios-qa/mac_start_stack.sh'   # поднимает то, что упало, и снова проверяет
```
Телефон должен быть разблокирован и на зарядке, Автоблокировка «Никогда». Заблокированный телефон = WDA отвечает `RequestDenied`.

## Подключение агента через appium-mcp
MCP-сервер: команда `appium-mcp` на Mac (stdio). Клиент запускает её на Mac или по SSH: `ssh -T <MAC_USER>@<MAC_HOST> "PATH=... APPIUM_HOME=... appium-mcp"`.
Создание сессии: `appium_session_management`, `action=create`, `platform=ios`, `remoteServerUrl=http://127.0.0.1:4723`, `capabilities` — **строка JSON** (объект инструмент не принимает):
```
{"platformName":"iOS","appium:automationName":"XCUITest","appium:udid":"<UDID>",
 "appium:webDriverAgentUrl":"http://127.0.0.1:8100","appium:bundleId":"<APP_BUNDLE>","appium:noReset":true}
```
Подпись «iPhone Simulator» в ответе — косметика, сессия идёт на реальный телефон. `select_device` не нужен.
`appium_screenshot` сохраняет файл на Mac (путь в ответе); копируй его в `out/screenshots/...`.

## Типовые сбои
| Симптом | Причина | Что делать |
|---|---|---|
| WDA `RequestDenied`, запуск таймаутится | телефон заблокирован | разблокировать, `mac_start_stack.sh` |
| `curl 127.0.0.1:8100/status` пусто | упал `ios runwda` или `forward` | `mac_start_stack.sh` |
| `ios launch` висит | известная проблема | запускать через Appium (`appium_app_lifecycle`) |
| В журнале пусто, приложение не грузится | прокси на телефоне выключен или mitmdump упал | проверить `:8080` и Wi-Fi прокси на телефоне |
| TLS-ошибки в `/tmp/mitm.log` | CA не доверен | Настройки → Основные → Об этом устройстве → Доверие сертификатов |
| WDA не стартует через 7 дней | истёк профиль бесплатного Apple ID (Personal Team) | пересборка с Mac из Terminal, только человек |
| Всё пропало ночью | Mac уснул или отвалился USB | `caffeinate` на Mac, проверить кабель, `mac_start_stack.sh` |

Не решилось за 2 попытки: записать в отчёт, прекратить работу с телефоном, не изобретать обходы.

## Ограничения Mac
Нет sqlite3 (только JSONL), нет sudo и brew, всё ставится в `~/ios-qa/tools`.
