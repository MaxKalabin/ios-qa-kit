# Сниффер: перехват, журнал и подмена

mitmdump с аддоном `qa_addon.py` (копия на Mac `~/ios-qa/qa_addon.py`, исходник `sniffer/qa_addon.py`). Расшифровывает только хосты из `QA_TARGETS` (`config.env`); остальное идёт туннелем. WebSocket-хосты — `QA_WS_HOSTS`.
Запуск делает `mac_start_stack.sh` (вручную: `QA_TARGETS=... mitmdump --listen-port 8080 -s ~/ios-qa/qa_addon.py --set qa_dir=$HOME/ios-qa/out/traffic`).

## Журнал: `~/ios-qa/out/traffic/<YYYYMMDD-HHMMSS>.jsonl`
Одна строка JSON на запрос (WebSocket: на сообщение). Поля: `ts`, `method`, `url`, `status`, `dur_s`, `resp_bytes`, `flags` (`4xx`, `5xx`, `slow`, `injected`...), `rule` (имя сработавшего правила), `req_body`, `resp_body` (до 20 000 символов), `orig_req` (`url`, `body` до подмены; только если правило сработало). В старых строках `resp_body` может не быть: читать через `.get`.
Пример на python (jq на Mac может не быть):
```
python3 - <<'PY'
import json,glob
for f in sorted(glob.glob('~/ios-qa/out/traffic/*.jsonl')):
    for l in open(f):
        d=json.loads(l)
        if 'filters' in d['url']: print(d['ts'],d['status'],(d.get('resp_body') or '')[:200])
PY
```

## Подмена: `~/ios-qa/out/traffic/RULES.json`
Файл перечитывается на лету, перезапуск не нужен. Создать или изменить: записать JSON-массив. Удалить файл: подмена выключена, сниффер только пишет. Шаблоны: `sniffer/RULES.example.json`.
Поля правила: `name`, `when` (`request` | `response` | `ws_in` | `ws_out`), `url` (regex), `method`, `body_match` (regex по телу запроса), `times` (сколько раз сработать), `enabled`, `match` (regex по тексту WS-сообщения), `action`.
Действия: `block` (+`status`), `status`, `delay_s`, `set_header` (словарь), `remove_header` (список имён), `set_query` (словарь; `null` удаляет параметр; только `when=request`), `replace_body`, `json_set` (путь `a.b.0.c` → значение).
В JSON regex пишется с двойным слэшем: `"api\\.example\\.com"`. Файл проверять через `python3 -c "import json;json.load(open('RULES.json'))"`: при ошибке аддон пишет `bad RULES.json` в `/tmp/mitm.log`, и правила не действуют. Лучше писать файл python-скриптом через `json.dump`, а не вручную.

## Правила работы с подменой
- Каждая подмена — отдельный тест-кейс: включить правило, выполнить сценарий в приложении, прочитать журнал (`injected`, `orig_req`), **удалить правило**, убедиться, что трафик снова не меняется.
- Перед завершением прогона `RULES.json` удалён или пуст. Оставленное правило искажает следующие тесты.
- Ожидаемое поведение приложения на подмену (500, пустой список, отказ сети): нет крэша и белого экрана, понятное сообщение, повтор возможен. Любой крэш — баг.
- Подмена исходящего запроса ломает подпись: ответ 400 `Wrong authorization` ожидаем, если меняется подписанный запрос.
