// background.js — Aggregates media state from content scripts,
// communicates with the Python native messaging host.

"use strict";

const NATIVE_HOST = "com.media_tabs.firefox";

// Per-tab media state: tabId -> { playing, position, duration, ... }
const tabStates = new Map();

let port = null;
let reconnectTimer = null;

// ---------------------------------------------------------------------------
// Native messaging connection
// ---------------------------------------------------------------------------
function connectNative() {
  if (port) return;

  try {
    port = browser.runtime.connectNative(NATIVE_HOST);
  } catch (e) {
    console.error("MPRIS: Failed to connect to native host:", e);
    scheduleReconnect();
    return;
  }

  port.onMessage.addListener((msg) => {
    if (msg && msg.type === "command" && msg.tabId) {
      browser.tabs.sendMessage(msg.tabId, {
        type: "command",
        action: msg.action,
        offset: msg.offset,
        position: msg.position,
        volume: msg.volume,
      }).catch(() => {
        removeTab(msg.tabId);
      });
    }
  });

  port.onDisconnect.addListener((p) => {
    const err = p.error || browser.runtime.lastError;
    if (err) console.error("MPRIS: Native host disconnected:", err);
    port = null;
    scheduleReconnect();
  });

  // Send current state of all tracked tabs
  for (const [tabId, state] of tabStates) {
    sendToNative(Object.assign({}, state, { type: "tabState", tabId }));
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectNative();
  }, 3000);
}

function sendToNative(msg) {
  if (!port) {
    connectNative();
    return;
  }
  try {
    port.postMessage(msg);
  } catch (e) {
    console.error("MPRIS: Error sending to native host:", e);
    port = null;
    scheduleReconnect();
  }
}

// ---------------------------------------------------------------------------
// Tab state management
// ---------------------------------------------------------------------------
function updateTab(tabId, state) {
  browser.tabs.get(tabId).then((tab) => {
    const enriched = {
      ...state,
      tabTitle: tab.title || state.title || "",
      tabUrl: tab.url || state.url || "",
    };
    tabStates.set(tabId, enriched);
    sendToNative(Object.assign({}, enriched, { type: "tabState", tabId }));
  }).catch(() => {
    removeTab(tabId);
  });
}

function removeTab(tabId) {
  if (tabStates.has(tabId)) {
    tabStates.delete(tabId);
    sendToNative({ type: "tabRemoved", tabId });
  }
}

// ---------------------------------------------------------------------------
// Message listener from content scripts
// ---------------------------------------------------------------------------
browser.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.type !== "mediaState" || !sender.tab) return;

  const tabId = sender.tab.id;

  if (!msg.hasMedia) {
    removeTab(tabId);
    return;
  }

  updateTab(tabId, msg);
});

// ---------------------------------------------------------------------------
// Tab lifecycle events
// ---------------------------------------------------------------------------
browser.tabs.onRemoved.addListener((tabId) => {
  removeTab(tabId);
});

browser.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) {
    removeTab(tabId);
  }
});

// ---------------------------------------------------------------------------
// Inject content script into already-open tabs on startup/reload
// ---------------------------------------------------------------------------
function injectIntoExistingTabs() {
  browser.tabs.query({ url: "<all_urls>" }).then((tabs) => {
    for (const tab of tabs) {
      if (tab.url.startsWith("about:") || tab.url.startsWith("moz-extension:")) continue;
      browser.tabs.executeScript(tab.id, { file: "content.js", allFrames: true }).catch(() => {});
    }
  });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
connectNative();
injectIntoExistingTabs();
