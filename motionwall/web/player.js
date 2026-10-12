"use strict";

(() => {
  const stage = document.getElementById("stage");
  const placeholder = document.getElementById("placeholder");
  const errorBox = document.getElementById("error");
  let engine = null;
  let generation = 0;
  let controller = null;
  let userPaused = false;
  let nativeHidden = false;
  let ended = false;
  let loaded = false;
  let kind = null;
  const settings = { fit: "contain", speed: 1, loop: true };
  let surface = null;
  const desktop = new URLSearchParams(location.search).get("desktop") === "1";

  function notify(type, extra = {}) {
    const message = { type, ...extra };
    window.webkit?.messageHandlers?.motionwall?.postMessage(JSON.stringify(message));
    window.dispatchEvent(new CustomEvent("motionwall", { detail: message }));
  }

  function showError(error) {
    const message = error?.message || String(error);
    errorBox.textContent = message;
    errorBox.hidden = false;
    userPaused = true;
    loaded = false;
    engine?.pause();
    notify("error", { message });
  }

  function isPlaying() {
    return loaded && !userPaused && !ended && !nativeHidden && (desktop || !document.hidden);
  }

  function syncPlayback() {
    if (isPlaying()) engine?.play();
    else engine?.pause();
    notify("state", { playing: isPlaying(), paused: userPaused, ended, suspended: nativeHidden || document.hidden });
  }

  function onEnded() {
    ended = true;
    syncPlayback();
  }

  function layout() {
    if (!surface) return;
    const { node, width, height } = surface;
    const sx = stage.clientWidth / width;
    const sy = stage.clientHeight / height;
    const scale = settings.fit === "cover" ? Math.max(sx, sy) : Math.min(sx, sy);
    node.style.width = `${width}px`;
    node.style.height = `${height}px`;
    node.style.transform = settings.fit === "stretch" ? `scale(${sx},${sy})` : `scale(${scale})`;
  }

  function makeSurface(width, height, tag = "div") {
    const node = document.createElement(tag);
    node.classList.add("artwork");
    stage.replaceChildren(node);
    surface = { node, width, height };
    layout();
    return node;
  }

  async function read(url, signal, type = "json") {
    const response = await fetch(url, { signal });
    if (!response.ok) throw new Error("O arquivo importado não está disponível. Importe-o novamente.");
    return type === "json" ? response.json() : type === "text" ? response.text() : response.arrayBuffer();
  }

  function gifEngine(buffer) {
    const bytes = new Uint8Array(buffer);
    const gif = new GifReader(bytes);
    const width = gif.width, height = gif.height;
    if (!width || !height || width * height > 16000000 || !gif.numFrames()) {
      throw new Error("GIF sem quadros ou com dimensões acima do limite.");
    }
    for (let i = 0; i < gif.numFrames(); i++) {
      const f = gif.frameInfo(i);
      if (!f.width || !f.height || f.x + f.width > width || f.y + f.height > height) {
        throw new Error("GIF contém um quadro fora da área da imagem.");
      }
    }
    const canvas = makeSurface(width, height, "canvas");
    canvas.width = width; canvas.height = height;
    const context = canvas.getContext("2d");
    const pixels = new Uint8ClampedArray(width * height * 4);
    const image = new ImageData(pixels, width, height);
    let restore = null, previous = null, frame = 0, elapsed = 0, last = null, raf = null;
    let finished = false, rendered = 0;
    const backgroundIndex = bytes[11];
    const background = bytes[10] & 128 ? [bytes[13 + backgroundIndex * 3], bytes[14 + backgroundIndex * 3], bytes[15 + backgroundIndex * 3], 255] : [0, 0, 0, 0];
    function clearRectangle(f) {
      const color = f.transparent_index === null ? background : [0, 0, 0, 0];
      for (let y = f.y; y < f.y + f.height; y++) {
        for (let x = f.x; x < f.x + f.width; x++) pixels.set(color, (y * width + x) * 4);
      }
    }
    function render(index) {
      if (previous?.disposal === 2) clearRectangle(previous);
      else if (previous?.disposal === 3 && restore) pixels.set(restore);
      const info = gif.frameInfo(index);
      restore = info.disposal === 3 ? pixels.slice() : null;
      gif.decodeAndBlitFrameRGBA(index, pixels);
      context.putImageData(image, 0, 0);
      previous = info;
      rendered++;
    }
    function reset() {
      pixels.fill(0);
      previous = restore = null;
      frame = elapsed = 0;
      finished = false;
      last = null;
      render(frame);
    }
    function tick(now) {
      raf = null;
      if (last !== null) elapsed += Math.min(now - last, 250) * settings.speed;
      last = now;
      let advanced = 0;
      while (elapsed >= Math.max(gif.frameInfo(frame).delay * 10 || 100, 20) && advanced < 40) {
        elapsed -= Math.max(gif.frameInfo(frame).delay * 10 || 100, 20);
        if (frame + 1 === gif.numFrames()) {
          if (!settings.loop) { finished = true; onEnded(); return; }
          pixels.fill(0); previous = restore = null; frame = 0;
        } else frame++;
        render(frame);
        advanced++;
      }
      raf = requestAnimationFrame(tick);
    }
    reset();
    return {
      play() { if (!finished && raf === null) { last = null; raf = requestAnimationFrame(tick); } },
      pause() { if (raf !== null) cancelAnimationFrame(raf); raf = null; last = null; },
      restart: reset,
      configure() {},
      destroy() { this.pause(); },
      debug: () => ({ frame, rendered }),
      capabilities: { loop: true, speed: true }
    };
  }

  function svgEngine(text) {
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    if (doc.querySelector("parsererror") || doc.documentElement.localName !== "svg") throw new Error("SVG inválido.");
    const svg = document.importNode(doc.documentElement, true);
    // Defense in depth: imports reject these too. Imported styles are scoped
    // to a shadow root, and the transport blocks scripts/network resources.
    svg.querySelectorAll("script,foreignObject,iframe,object,embed").forEach(n => n.remove());
    for (const node of [svg, ...svg.querySelectorAll("*")]) {
      for (const attr of [...node.attributes]) if (attr.localName.startsWith("on")) node.removeAttributeNode(attr);
    }
    const box = svg.viewBox.baseVal;
    const width = box.width || parseFloat(svg.getAttribute("width")) || 800;
    const height = box.height || parseFloat(svg.getAttribute("height")) || 450;
    const host = makeSurface(width, height);
    const shadow = host.attachShadow({ mode: "open" });
    svg.setAttribute("width", width); svg.setAttribute("height", height);
    shadow.append(svg);
    svg.pauseAnimations();
    svg.getBoundingClientRect(); // Resolve CSS animations before controlling them.
    const animations = svg.getAnimations({ subtree: true });
    animations.forEach(a => { a.pause(); a.playbackRate = settings.speed; });
    let time = 0, last = null, raf = null, rendered = 0;
    function tick(now) {
      raf = null;
      if (last !== null) time += Math.min(now - last, 250) / 1000 * settings.speed;
      last = now;
      svg.setCurrentTime(time);
      rendered++;
      raf = requestAnimationFrame(tick);
    }
    return {
      play() { animations.forEach(a => a.play()); if (raf === null) { last = null; raf = requestAnimationFrame(tick); } },
      pause() { animations.forEach(a => a.pause()); if (raf !== null) cancelAnimationFrame(raf); raf = null; last = null; },
      restart() { time = 0; last = null; svg.setCurrentTime(0); animations.forEach(a => { a.currentTime = 0; }); },
      configure() { animations.forEach(a => a.updatePlaybackRate(settings.speed)); },
      destroy() { this.pause(); animations.forEach(a => a.cancel()); },
      debug: () => ({ time, rendered, cssAnimations: animations.length }),
      capabilities: { loop: false, speed: true }
    };
  }

  function lottieEngine(data, url, signal) {
    for (const asset of data.assets || []) {
      if (asset.p && !asset.p.startsWith("data:")) {
        asset.p = new URL((asset.u || "") + asset.p, url).href;
        asset.u = "";
      }
    }
    for (const font of data.fonts?.list || []) if (font.fPath) font.fPath = new URL(font.fPath, url).href;
    const container = makeSurface(data.w, data.h);
    const animation = lottie.loadAnimation({ container, renderer: "svg", loop: settings.loop, autoplay: false, animationData: data });
    animation.setSpeed(settings.speed);
    let rendered = 0;
    animation.addEventListener("enterFrame", () => rendered++);
    animation.addEventListener("complete", onEnded);
    const ready = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Lottie demorou demais para carregar.")), 15000);
      const complete = () => { clearTimeout(timeout); resolve(); };
      const fail = () => { clearTimeout(timeout); reject(new Error("Não foi possível reproduzir esta animação Lottie.")); };
      if (animation.isLoaded) complete();
      else animation.addEventListener("DOMLoaded", complete);
      animation.addEventListener("data_failed", fail);
      animation.addEventListener("error", fail);
      signal.addEventListener("abort", () => { clearTimeout(timeout); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
    });
    return {
      ready,
      play: () => animation.play(), pause: () => animation.pause(),
      restart: () => animation.goToAndStop(0, true),
      configure() { animation.setSpeed(settings.speed); animation.loop = settings.loop; },
      destroy: () => animation.destroy(),
      debug: () => ({ frame: animation.currentFrame, rendered }),
      capabilities: { loop: true, speed: true }
    };
  }

  function videoEngine(url, signal) {
    const video = document.createElement("video");
    video.muted = true; video.playsInline = true; video.preload = "auto";
    video.loop = settings.loop; video.playbackRate = settings.speed;
    video.disableRemotePlayback = true;
    stage.replaceChildren(video);
    video.addEventListener("ended", onEnded);
    const ready = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("O vídeo demorou demais para carregar.")), 15000);
      const done = callback => { clearTimeout(timeout); callback(); };
      video.addEventListener("loadeddata", () => done(resolve), { once: true });
      video.addEventListener("error", () => done(() => reject(new Error("Vídeo incompatível ou codec ausente. Verifique os plugins do GStreamer."))), { once: true });
      signal.addEventListener("abort", () => done(() => reject(new DOMException("Aborted", "AbortError"))), { once: true });
      video.src = url;
    });
    return {
      ready,
      play() { video.play().catch(e => { if (!signal.aborted) showError(e); }); },
      pause: () => video.pause(), restart() { video.currentTime = 0; },
      configure() { video.loop = settings.loop; video.playbackRate = settings.speed; },
      destroy() { video.pause(); video.removeAttribute("src"); video.load(); },
      debug: () => ({ time: video.currentTime, readyState: video.readyState }),
      capabilities: { loop: true, speed: true }
    };
  }

  function configure(values = {}) {
    if (["contain", "cover", "stretch"].includes(values.fit)) settings.fit = values.fit;
    if (Number.isFinite(values.speed) && values.speed >= 0.25 && values.speed <= 3) settings.speed = values.speed;
    if (typeof values.loop === "boolean") settings.loop = values.loop;
    stage.dataset.fit = settings.fit;
    engine?.configure();
    layout();
  }

  function clear() {
    generation++;
    controller?.abort();
    controller = null;
    engine?.destroy();
    engine = surface = null;
    stage.replaceChildren();
    placeholder.hidden = false;
    errorBox.hidden = true;
    loaded = ended = false;
    kind = null;
  }

  async function open(options) {
    clear();
    const current = generation;
    const url = new URL(options.src, location.href);
    const assetPrefix = location.pathname.split("/player/")[0] + "/assets/";
    if (url.origin !== location.origin || !url.pathname.startsWith(assetPrefix)) {
      showError(new Error("A prévia aceita apenas arquivos importados neste catálogo."));
      return false;
    }
    kind = options.kind;
    userPaused = false;
    configure(options);
    controller = new AbortController();
    const signal = controller.signal;
    try {
      let result;
      if (kind === "gif") result = await read(url, signal, "buffer");
      else if (kind === "svg") result = await read(url, signal, "text");
      else if (["lottie", "dotlottie"].includes(kind)) result = await read(url, signal);
      else if (kind !== "video") throw new Error("Formato não suportado.");
      if (current !== generation) return false;
      if (kind === "gif") engine = gifEngine(result);
      else if (kind === "svg") engine = svgEngine(result);
      else if (["lottie", "dotlottie"].includes(kind)) engine = lottieEngine(result, url, signal);
      else engine = videoEngine(url, signal);
      if (engine.ready) await engine.ready;
      if (current !== generation) return false;
      loaded = true;
      placeholder.hidden = true;
      notify("loaded", { kind, capabilities: engine.capabilities });
      syncPlayback();
      return true;
    } catch (error) {
      if (current === generation && error.name !== "AbortError") showError(error);
      return false;
    }
  }

  window.MotionWall = {
    open, clear, configure,
    pause() { userPaused = true; syncPlayback(); },
    play() { if (ended) { ended = false; engine?.restart(); } userPaused = false; syncPlayback(); },
    restart() { ended = false; engine?.restart(); syncPlayback(); },
    setSuspended(value) { nativeHidden = !!value; syncPlayback(); },
    debug: () => ({ kind, loaded, playing: isPlaying(), ended, ...settings, ...engine?.debug() })
  };
  new ResizeObserver(layout).observe(stage);
  document.addEventListener("visibilitychange", syncPlayback);
  notify("ready");
  const params = new URLSearchParams(location.search);
  if (params.has("src") && params.has("kind")) open({ src: params.get("src"), kind: params.get("kind") });
})();
