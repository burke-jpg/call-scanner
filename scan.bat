@echo off
REM Call Scanner — run from anywhere
REM Usage: scan "George Tuesday morning"
REM        scan --list "last 5 calls"
REM        scan --csv %USERPROFILE%\Desktop\calls.csv "Sara yesterday"

pushd "%~dp0"
python main.py %*
popd
