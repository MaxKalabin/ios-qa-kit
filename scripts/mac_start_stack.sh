#!/bin/zsh
# Start/repair the whole stack on the Mac. Safe to rerun: starts only what is missing.
# Usage: zsh ~/ios-qa/mac_start_stack.sh   (locally or over ssh)
. "${QA_CONFIG:-$HOME/ios-qa/config.env}" || { echo "config.env not found (copy config.env.example)"; exit 1; }
export PATH=$QA_HOME/tools/node/bin:$QA_HOME/tools/npm/bin:$PATH
export APPIUM_HOME=$QA_HOME/tools/appium
export QA_TARGETS QA_WS_HOSTS
M=${MITMDUMP:-$QA_HOME/tools/mitm/mitmproxy.app/Contents/MacOS/mitmdump}   # or just `mitmdump` if installed in PATH
OUT=$QA_HOME/out/traffic; mkdir -p $OUT
up(){ pgrep -f "$1" >/dev/null; }

up "ios runwda" || { nohup ios runwda --bundleid=$WDA_BUNDLE --testrunnerbundleid=$WDA_BUNDLE --xctestconfig=WebDriverAgentRunner.xctest --udid $UDID >/tmp/wda.log 2>&1 & sleep 8; }
up "ios forward 8100" || { nohup ios forward 8100 8100 --udid $UDID >/tmp/fwd.log 2>&1 & sleep 2; }
up "mitmdump" || { nohup $M --listen-port $PROXY_PORT -s $QA_HOME/qa_addon.py --set qa_dir=$OUT >/tmp/mitm.log 2>&1 & sleep 3; }
up "appium --port 4723" || { nohup appium --port 4723 --address 127.0.0.1 >/tmp/appium.log 2>&1 & sleep 6; }
/bin/zsh $QA_HOME/mac_health.sh