# ios-qa-kit — автономное QA iOS-приложения через LLM-агента

Агент (любая LLM с поддержкой MCP) тестирует **ваше** iOS-приложение на **вашем** реальном iPhone: управляет экраном через Appium, перехватывает и подменяет сетевой трафик через mitmproxy, сверяет ответы API с экраном, пишет баги и отчёт.

В репозитории нет ничего, привязанного к конкретным устройствам, аккаунтам или приложению: всё задаётся в `config.env`.

```
LLM-агент --MCP stdio--> appium-mcp --HTTP :4723--> Appium (XCUITest) --> WDA :8100 --USB--> iPhone
iPhone --Wi-Fi proxy--> mitmdump :8080 (sniffer/qa_addon.py) --> API вашего приложения
журнал: ~/ios-qa/out/traffic/*.jsonl, правила подмены: ~/ios-qa/out/traffic/RULES.json
```

## Что нужно
| Что | Платно? |
|---|---|
| Mac с Xcode (для подписи WebDriverAgent) | Mac и Xcode: Xcode бесплатен |
| Apple ID. Бесплатный (Personal Team) работает, но профиль живёт **7 дней** и WDA надо пересобирать; платный Developer Program ($99/год) даёт год | бесплатно / платно |
| iPhone с включённым режимом разработчика, кабель USB | — |
| Тестируемая dev-сборка **без SSL pinning** (иначе трафик не расшифровать) | — |
| [go-ios](https://github.com/danielpaulus/go-ios) (запуск WDA и проброс порта) | бесплатно, MIT |
| [Appium](https://appium.io) 3/4 + драйвер `xcuitest` | бесплатно, Apache-2.0 |
| [appium-mcp](https://github.com/appium/appium-mcp) | бесплатно |
| [mitmproxy](https://mitmproxy.org) | бесплатно, MIT |
| LLM-клиент с MCP (Claude Code, Codex, свой) | зависит от провайдера |

## Настройка доступов (по шагам)

### 1. Mac
1. Создайте папку: `mkdir -p ~/ios-qa/out/traffic ~/ios-qa/tools`.
2. Скопируйте в неё: `scripts/mac_start_stack.sh`, `scripts/mac_health.sh`, `sniffer/qa_addon.py`, и `config.env` (см. шаг 3).
3. Установите (в `~/ios-qa/tools`, если нет sudo/brew; иначе обычным способом): Node.js, `npm i -g appium appium-mcp`, `appium driver install xcuitest`, go-ios (`npm i -g go-ios`), mitmproxy (приложение или `brew install mitmproxy`).
4. Включите «Удалённый вход» (Системные настройки → Основные → Общий доступ), если агент будет ходить на Mac по SSH. Войдите по ключу, пароль агенту не давайте:
   `ssh-copy-id <MAC_USER>@<MAC_HOST>`.
5. Чтобы Mac не засыпал в прогоне: `caffeinate -dimsu &`.

### 2. iPhone
1. Настройки → Конфиденциальность и безопасность → **Режим разработчика** → включить, перезагрузить.
2. Подключите по USB, нажмите «Доверять». Автоблокировка → **Никогда**, телефон на зарядке и разблокирован (заблокированный = WDA отвечает `RequestDenied`).
3. UDID: `ios list` или `xcrun xctrace list devices`.
4. **WebDriverAgent**: в Xcode откройте проект WebDriverAgent (из пакета `appium-webdriveragent`), для цели `WebDriverAgentRunner` выберите свою Team и **свой уникальный** Bundle ID (например `com.<вы>.wda.xctrunner`). Соберите на телефон (Product → Test). На телефоне: Настройки → Основные → VPN и управление устройством → доверять своему профилю.
5. Wi-Fi прокси: Настройки → Wi-Fi → ваша сеть → Настройка прокси → Вручную → `<IP_MAC>:8080`. Телефон и Mac в одной сети.
6. Сертификат mitmproxy: с телефона откройте `http://mitm.it`, поставьте профиль, затем Настройки → Основные → Об этом устройстве → **Доверие сертификатов** → включить для mitmproxy.

### 3. config.env
```
cp config.env.example ~/ios-qa/config.env     # и заполните
```
Укажите `UDID`, `APP_BUNDLE` (bundle id вашего приложения), `WDA_BUNDLE` (из п. 2.4), `QA_TARGETS` (какие хосты API расшифровывать). Файл **не коммитится** (`.gitignore`).

### 4. Запуск и проверка
```
zsh ~/ios-qa/mac_start_stack.sh     # поднимает WDA, проброс 8100, mitmdump, Appium; в конце health
zsh ~/ios-qa/mac_health.sh          # OK/FAIL по каждому компоненту
```
По SSH: `ssh <MAC_USER>@<MAC_HOST> 'zsh ~/ios-qa/mac_health.sh'`.

### 5. Подключение агента (MCP)
Пример для Claude Code (`.mcp.json`) — MCP-сервер запускается на Mac по SSH:
```json
{
  "mcpServers": {
    "appium": {
      "command": "ssh",
      "args": ["-T", "<MAC_USER>@<MAC_HOST>",
               "PATH=$HOME/ios-qa/tools/node/bin:$HOME/ios-qa/tools/npm/bin:$PATH APPIUM_HOME=$HOME/ios-qa/tools/appium appium-mcp"]
    }
  }
}
```
Если агент работает на самом Mac, запускайте `appium-mcp` напрямую. Сессия Appium создаётся инструментом `appium_session_management` (параметры и JSON capabilities — в `docs/STACK.md`).

### 6. Задание агенту
Дайте ему прочитать `docs/AGENT_RUNBOOK.md` (правила, границы, цикл проверки), затем `docs/STACK.md`, `docs/SNIFFER.md`, `docs/OUTPUTS.md`. Чеклист свой, формат в `checklists/TEMPLATE.md`.

## Безопасность
- `config.env`, `out/`, журналы трафика, скриншоты и сертификаты **в git не попадают**: в них бывают токены, e-mail и телефоны. Перед публикацией своих отчётов вычистите их.
- Тестируйте только приложения и API, на которые у вас есть право. Подмену трафика включайте только на своём тестовом окружении.
- Агенту: не трогать другие приложения на телефоне, не платить, не писать реальным людям (см. runbook).
- Бесплатный профиль подписи истекает через 7 дней: WDA тогда пересобирает человек.

## Структура
`docs/` — runbook агента, стенд, сниффер, выходные данные · `scripts/` — запуск и проверка стенда · `sniffer/` — аддон mitmproxy и шаблон правил подмены · `checklists/` — шаблон чеклиста · `config.env.example` — все настройки.

## Лицензия
MIT.