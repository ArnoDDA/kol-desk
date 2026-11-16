#!/bin/zsh
cd -- "${0:A:h}" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  print 'Python 3.9+ is required. / 请先安装 Python 3.9 或更高版本。'
  read '?Press Enter to close / 按回车关闭'
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
python3 launch.py
result=$?
if (( result != 0 )); then
  read '?Could not start. Read the message above. Press Enter to close. / 启动失败，请查看上方提示，按回车关闭。'
fi
exit $result
