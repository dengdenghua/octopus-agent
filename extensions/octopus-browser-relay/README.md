# Octopus Browser Relay

Local unpacked extension for connecting a normal Chromium browser to Octopus browser automation.

## Install

1. Open `chrome://extensions`.
2. Enable `Developer mode`.
3. Click `Load unpacked`.
4. Select this folder: `.octopus-browser-relay`.

The extension sends a local heartbeat to `http://127.0.0.1:8000/api/browser/relay/heartbeat`.
Click the `Octopus Agent` toolbar icon on any page to open the Page Agent panel directly.

When Octopus sends a browser action, the extension executes it in the currently active Chromium tab and posts the result back to the local server. If you change these files while the extension is loaded, click `Reload` on the extension card in `chrome://extensions`.

## Bookmarklet mode

Octopus can also expose a draggable `Octopus Agent` bookmarklet in the browser page. Drag it to the Chrome/Edge bookmarks bar, then click it on any target page to connect that page to Octopus without installing the unpacked extension.

Bookmarklet mode supports page text extraction, click/type/scroll actions, and `window.__octopusPageAgent` semantic actions when the page provides them. Screenshots and cross-tab control still require the unpacked extension.
