#!/bin/zsh
# One-shot health check. Prints OK/FAIL per component; exit 1 if anything fails.
. "${QA_CONFIG:-$HOME/ios-qa/config.env}" || { echo "FAIL config.env not found"; exit 1; }
bad=0
chk(){ if eval "$2" >/dev/null 2>&1; then echo "OK   $1"; else echo "FAIL $1"; bad=1; fi }
chk "WDA process"        'pgrep -f "ios runwda"'
chk "forward 8100"       'pgrep -f "ios forward 8100"'
chk "WDA answers"        'curl -sf -m5 http://127.0.0.1:8100/status'
chk "phone unlocked"     '[ "$(curl -s -m5 http://127.0.0.1:8100/wda/locked | tr -d " \n" | grep -o "\"value\":false")" ]'
chk "mitmdump :$PROXY_PORT" 'pgrep -f mitmdump && lsof -iTCP:$PROXY_PORT -sTCP:LISTEN'
chk "appium :4723"       'curl -sf -m5 http://127.0.0.1:4723/status'
chk "traffic log fresh (<30 min)" '[ -n "$(find $QA_HOME/out/traffic -name "*.jsonl" -mmin -30 | head -1)" ]'
exit $bad