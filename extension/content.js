// content.js — Injected into every page. Detects media elements,
// reports state to the background script, and executes commands.

(function () {
  "use strict";

  let trackedMedia = null;
  let observer = null;
  let metadataInterval = null;

  // ---------------------------------------------------------------------------
  // YouTube-specific metadata extraction
  // ---------------------------------------------------------------------------
  function isYouTube() {
    return location.hostname.includes("youtube.com");
  }

  function getYouTubeMetadata() {
    const title =
      document.querySelector(
        "yt-formatted-string.ytd-watch-metadata, #info-contents yt-formatted-string.ytd-video-primary-info-renderer, h1.ytd-watch-metadata yt-formatted-string"
      )?.textContent?.trim() ||
      document.querySelector("title")?.textContent?.replace(" - YouTube", "").trim() ||
      "";

    const artist =
      document.querySelector(
        "ytd-channel-name yt-formatted-string a, #owner-name a, ytd-video-owner-renderer yt-formatted-string a"
      )?.textContent?.trim() || "";

    const videoId = new URLSearchParams(location.search).get("v");
    const artUrl = videoId ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : "";

    return { title, artist, artUrl };
  }

  // ---------------------------------------------------------------------------
  // Generic metadata extraction
  // ---------------------------------------------------------------------------
  function getGenericMetadata() {
    const og = (prop) =>
      document.querySelector(`meta[property="og:${prop}"]`)?.content || "";

    const title = og("title") || document.title || location.hostname;
    const artist = og("site_name") || location.hostname;
    const artUrl = og("image") || "";

    return { title, artist, artUrl };
  }

  function getMetadata() {
    return isYouTube() ? getYouTubeMetadata() : getGenericMetadata();
  }

  // ---------------------------------------------------------------------------
  // Pick the best media element on the page
  // ---------------------------------------------------------------------------
  function pickMedia() {
    const allMedia = [
      ...document.querySelectorAll("video"),
      ...document.querySelectorAll("audio"),
    ];

    if (allMedia.length === 0) return null;

    // Prefer playing elements
    const playing = allMedia.filter((m) => !m.paused);
    if (playing.length > 0) {
      return playing.sort((a, b) => {
        const areaA = (a.videoWidth || 0) * (a.videoHeight || 0);
        const areaB = (b.videoWidth || 0) * (b.videoHeight || 0);
        return areaB - areaA;
      })[0];
    }

    // Pick the largest element with a source
    const withSrc = allMedia.filter((m) => m.currentSrc || m.src);
    if (withSrc.length > 0) {
      return withSrc.sort((a, b) => {
        const areaA = (a.videoWidth || 0) * (a.videoHeight || 0);
        const areaB = (b.videoWidth || 0) * (b.videoHeight || 0);
        return areaB - areaA;
      })[0];
    }

    return allMedia[0];
  }

  // ---------------------------------------------------------------------------
  // State reporting
  // ---------------------------------------------------------------------------
  function buildState() {
    if (!trackedMedia) return null;

    const meta = getMetadata();
    return {
      type: "mediaState",
      playing: !trackedMedia.paused,
      position: trackedMedia.currentTime || 0,
      duration: trackedMedia.duration || 0,
      volume: trackedMedia.volume,
      muted: trackedMedia.muted,
      title: meta.title,
      artist: meta.artist,
      artUrl: meta.artUrl,
      url: location.href,
      hasMedia: true,
    };
  }

  function sendState() {
    const state = buildState();
    if (state) {
      browser.runtime.sendMessage(state).catch(() => {
        cleanup();
      });
    }
  }

  function sendNoMedia() {
    browser.runtime.sendMessage({ type: "mediaState", hasMedia: false }).catch(() => {});
  }

  // ---------------------------------------------------------------------------
  // Media element event listeners
  // ---------------------------------------------------------------------------
  const mediaEvents = [
    "play",
    "pause",
    "ended",
    "seeked",
    "volumechange",
    "loadedmetadata",
    "emptied",
  ];

  function attachListeners(el) {
    for (const evt of mediaEvents) {
      el.addEventListener(evt, sendState);
    }
    el.addEventListener("timeupdate", onTimeUpdate);
  }

  function detachListeners(el) {
    for (const evt of mediaEvents) {
      el.removeEventListener(evt, sendState);
    }
    el.removeEventListener("timeupdate", onTimeUpdate);
  }

  let lastTimeUpdate = 0;
  function onTimeUpdate() {
    const now = Date.now();
    if (now - lastTimeUpdate > 2000) {
      lastTimeUpdate = now;
      sendState();
    }
  }

  // ---------------------------------------------------------------------------
  // Scanning / MutationObserver
  // ---------------------------------------------------------------------------
  function scan() {
    const best = pickMedia();

    if (best === trackedMedia) return;

    if (trackedMedia) {
      detachListeners(trackedMedia);
    }

    trackedMedia = best;

    if (trackedMedia) {
      attachListeners(trackedMedia);
      sendState();
    } else {
      sendNoMedia();
    }
  }

  function startObserver() {
    if (observer) observer.disconnect();
    observer = new MutationObserver(() => scan());
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  }

  // ---------------------------------------------------------------------------
  // Command handling from background script
  // ---------------------------------------------------------------------------
  browser.runtime.onMessage.addListener((msg) => {
    if (!msg || msg.type !== "command" || !trackedMedia) return;

    switch (msg.action) {
      case "Play":
        trackedMedia.play();
        break;
      case "Pause":
        trackedMedia.pause();
        break;
      case "PlayPause":
        if (trackedMedia.paused) trackedMedia.play();
        else trackedMedia.pause();
        break;
      case "Stop":
        trackedMedia.pause();
        trackedMedia.currentTime = 0;
        break;
      case "Next":
        trackedMedia.currentTime = trackedMedia.duration || 0;
        break;
      case "Previous":
        trackedMedia.currentTime = 0;
        break;
      case "Seek":
        if (typeof msg.offset === "number") {
          trackedMedia.currentTime = Math.max(
            0,
            Math.min(trackedMedia.duration || 0, msg.offset / 1e6)
          );
        }
        break;
      case "SetPosition":
        if (typeof msg.position === "number") {
          trackedMedia.currentTime = Math.max(
            0,
            Math.min(trackedMedia.duration || 0, msg.position / 1e6)
          );
        }
        break;
      case "Volume":
        if (typeof msg.volume === "number") {
          trackedMedia.volume = Math.max(0, Math.min(1, msg.volume));
        }
        break;
    }

    setTimeout(sendState, 100);
  });

  // ---------------------------------------------------------------------------
  // Periodic metadata refresh (for SPAs like YouTube that change title)
  // ---------------------------------------------------------------------------
  metadataInterval = setInterval(() => {
    if (trackedMedia && !trackedMedia.paused) {
      sendState();
    }
  }, 5000);

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------
  function cleanup() {
    if (trackedMedia) detachListeners(trackedMedia);
    if (observer) observer.disconnect();
    if (metadataInterval) clearInterval(metadataInterval);
    trackedMedia = null;
    observer = null;
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------
  scan();
  startObserver();

  if (document.readyState !== "complete") {
    window.addEventListener("load", () => scan());
  }
})();
