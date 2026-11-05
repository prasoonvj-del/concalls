#!/data/data/com.termux/files/usr/bin/bash
# Builds the news brief automatically every morning (default 6:30 am).
# Change the time:  bash schedule_tablet.sh 7:15
TIME="${1:-6:30}"
H="${TIME%%:*}"; M="${TIME##*:}"
pkg install -y cronie termux-services termux-api >/dev/null
sv-enable crond 2>/dev/null || true
( crontab -l 2>/dev/null | grep -v "news.py" ; \
  echo "$M $H * * * cd $HOME/ConcallSummaries && python news.py --quiet >> data/news_log.txt 2>&1" ) | crontab -
echo "Scheduled: the morning brief will be built every day at $TIME."
echo "Important:"
echo " 1. Close Termux completely and open it again once (to start the scheduler)."
echo " 2. Android Settings > Apps > Termux > Battery > No restrictions."
echo " 3. Keep Termux running in the background (its notification stays)."
echo " 4. Optional: install the 'Termux:API' app to get a notification when the brief is ready."
echo "Open it any time with:  concalls  -> option 6"
