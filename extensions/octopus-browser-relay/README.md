# Octopus Browser Relay

Local unpacked extension for connecting a normal Chromium browser to Octopus browser automation.
The primary UI is a Chrome Side Panel so the Agent conversation stays visible
without covering the page being operated.

## Install

1. Open `chrome://extensions`.
2. Enable `Developer mode`.
3. Click `Load unpacked`.
4. Select this folder: `extensions/octopus-browser-relay`.

The extension sends a local heartbeat to `http://127.0.0.1:8000/api/browser/relay/heartbeat`.
Click the `Octopus Agent` toolbar icon on any page to open the Octopus Sidecar.
The side panel talks to the local realtime gateway at `/api/realtime`, prefixes
turns with `@Chrome`, and keeps the active tab available through the relay.

When Octopus sends a browser action, the extension executes it in the currently active Chromium tab and posts the result back to the local server. If you change these files while the extension is loaded, click `Reload` on the extension card in `chrome://extensions`.

## Side panel mode

The Chrome Side Panel is the recommended external-browser experience:

- The real webpage remains fully visible in the main tab.
- The Agent chat, approvals, current task, and action log stay in the side panel.
- Page overlays are avoided by default; use the `页面轻面板` button only as a fallback.
- `@Chrome` turns prefer the extension relay, so signed-in pages and browser extensions stay available.

## Bookmarklet mode

Octopus can also expose a draggable `Octopus Agent` bookmarklet in the browser page. Drag it to the Chrome/Edge bookmarks bar, then click it on any target page to connect that page to Octopus without installing the unpacked extension.

Bookmarklet mode supports page text extraction, click/type/scroll actions, and `window.__octopusPageAgent` semantic actions when the page provides them. Screenshots and cross-tab control still require the unpacked extension.
