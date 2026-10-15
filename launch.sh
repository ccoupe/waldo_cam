#!/usr/bin/env bash
source PYENV/bin/activate
nm-online -q -t 30
cd /usr/local/lib/waldo_cam/
node=`hostname`
python3 waldo.py -s -c ${node}.toml
