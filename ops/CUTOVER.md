# Registry → Hub cutover (macOS)

Replaces the bare app-port-registry LaunchAgent with the Selran Hub on the
same port (11999) and the same SQLite DB — all existing allocations carry
over untouched. Rehearsed 2026-06-10 on a scratch port: 41-app parity
confirmed.

## Pre-flight (already done if you ran bootstrap.sh)
    ./bootstrap.sh

## The cutover — three commands
    cp ops/com.selran.hub.plist ~/Library/LaunchAgents/
    launchctl bootout "gui/$(id -u)/com.aidin.app-port-registry" && mkdir -p ~/Library/LaunchAgents/disabled && mv ~/Library/LaunchAgents/com.aidin.app-port-registry.plist ~/Library/LaunchAgents/disabled/
    launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.selran.hub.plist

## Verify
    ./scripts/verify_cutover.sh

## Rollback (if anything is wrong)
    launchctl bootout "gui/$(id -u)/com.selran.hub"
    mv ~/Library/LaunchAgents/disabled/com.aidin.app-port-registry.plist ~/Library/LaunchAgents/
    launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.aidin.app-port-registry.plist
