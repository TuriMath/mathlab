// Factory office: a small pixel-art map of the team. Original art, drawn in code.
// Working agents sit at their desks and type; idle agents wander to the lounge.
(() => {
  const W = 384, H = 216;          // low-res scene size, scaled up with crisp pixels
  const WALL = 44, CORR = 104;     // wall height; corridor row (person top y) between desk rows
  const SPEED = 30;                // px per second
  const ORDER = ["hilbert", "noether", "gauss", "euler", "godel"];

  const LOOKS = {
    hilbert: { hair: "#d9d9d9", skin: "#ffdbac", style: "short" },
    noether: { hair: "#4a3222", skin: "#f1c27d", style: "long" },
    gauss:   { hair: "#8f9aa0", skin: "#ffdbac", style: "short" },
    euler:   { hair: "#2b1d14", skin: "#e0ac69", style: "short" },
    godel:   { hair: "#141414", skin: "#f1c27d", style: "spiky" },
  };

  // 10x16 front-facing person. h hair, s skin, e eye, c shirt, d shirt shade, p pants, k shoes.
  const BODY = [
    "...hhhh...",
    "..hhhhhh..",
    "..hssssh..",
    "..sesses..",
    "..ssssss..",
    "...ssss...",
    "....ss....",
    "..cccccc..",
    ".cccccccc.",
    ".sccddccs.",
    ".sccccccs.",
    "..dddddd..",
    "..pppppp..",
    "..pp..pp..",
    "..pp..pp..",
    "..kk..kk..",
  ];
  const WALK = [
    ["..pp..pp..", "..pp...pp.", "..kk...kk."],
    ["..pp..pp..", ".pp...pp..", ".kk...kk.."],
  ];

  function shade(hex, f) {
    const n = parseInt(hex.slice(1), 16);
    const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(v * f))));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }

  // ---------- Layout ----------
  const DESK_W = 44, DESK_H = 16;
  const desks = ORDER.map((id, i) => {
    const x = 16 + (i % 4) * 64, y = i < 4 ? 78 : 148;
    return { id, x, y, seat: { x: x + DESK_W / 2 - 5, y: y - 12 }, aisle: x - 10 };
  });
  const LOUNGE = [
    { x: 300, y: 52, pose: "sit" }, { x: 318, y: 52, pose: "sit" }, { x: 336, y: 52, pose: "sit" },
    { x: 346, y: 142, pose: "stand" }, { x: 304, y: 126, pose: "stand" }, { x: 322, y: 130, pose: "stand" },
    { x: 296, y: 176, pose: "stand" }, { x: 262, y: 120, pose: "stand" }, { x: 360, y: 104, pose: "stand" },
  ];

  // ---------- State ----------
  let canvas, ctx, low, lctx, g, scratch, sctx, meta, getWorking, onPick, raf = null, last = 0, t = 0;
  let people = {}, logo = null, hover = null, view = { s: 1, regions: [] };
  // Tall screens (phones) split the scene: desks on top, lounge below. SPLIT is the scene x where the lounge starts.
  const SPLIT = 258;

  function makePeople() {
    people = {};
    const working = getWorking() || {};
    const free = LOUNGE.map((_, i) => i).sort(() => Math.random() - 0.5);
    ORDER.forEach((id) => {
      if (!meta.agents[id]) return;
      // Working agents start at their desks; the rest are spread between the lounge and their desks.
      const atDesk = working[id] || !free.length || Math.random() < 0.3;
      const spot = atDesk ? { kind: "desk" } : { kind: "lounge", i: free.pop() };
      const p = spotPos(id, spot);
      people[id] = { id, x: p.x, y: p.y, spot, path: [], pose: p.pose, next: 3 + Math.random() * 8, bubble: null };
    });
  }

  function spotPos(id, spot) {
    if (spot.kind === "desk") { const d = desks.find((k) => k.id === id); return { ...d.seat, pose: "sit" }; }
    return LOUNGE[spot.i];
  }

  function chain(id, spot) {          // points from the corridor into a spot (reverse to leave it)
    if (spot.kind === "desk") {
      const d = desks.find((k) => k.id === id);
      return { corrX: d.aisle, pts: [{ x: d.aisle, y: CORR }, { x: d.aisle, y: d.seat.y }, { x: d.seat.x, y: d.seat.y }] };
    }
    const s = LOUNGE[spot.i];
    return { corrX: s.x, pts: [{ x: s.x, y: CORR }, { x: s.x, y: s.y }] };
  }

  function goTo(p, spot) {
    if (sameSpot(p.spot, spot)) return;
    const from = chain(p.id, p.spot), to = chain(p.id, spot);
    const out = from.pts.slice(0, -1).reverse();
    p.path = [...out, { x: from.corrX, y: CORR }, { x: to.corrX, y: CORR }, ...to.pts];
    p.spot = spot;
    p.pose = "walk";
  }

  const sameSpot = (a, b) => a.kind === b.kind && a.i === b.i;

  function freeLoungeSpot(except) {
    const taken = new Set(Object.values(people).filter((q) => q !== except && q.spot.kind === "lounge").map((q) => q.spot.i));
    const options = LOUNGE.map((_, i) => i).filter((i) => !taken.has(i));
    return options.length ? { kind: "lounge", i: options[Math.floor(Math.random() * options.length)] } : { kind: "desk" };
  }

  // ---------- Update ----------
  function update(dt) {
    const working = getWorking() || {};
    for (const p of Object.values(people)) {
      if (working[p.id] && p.spot.kind !== "desk") goTo(p, { kind: "desk" });
      if (!working[p.id] && !p.path.length) {
        p.next -= dt;
        if (p.next <= 0) {
          p.next = 10 + Math.random() * 16;
          goTo(p, Math.random() < 0.25 ? { kind: "desk" } : freeLoungeSpot(p));
        }
      }
      if (p.path.length) {
        let step = SPEED * dt;
        while (step > 0 && p.path.length) {
          const tgt = p.path[0], dx = tgt.x - p.x, dy = tgt.y - p.y, dist = Math.hypot(dx, dy);
          if (dist <= step) { p.x = tgt.x; p.y = tgt.y; p.path.shift(); step -= dist; }
          else { p.x += (dx / dist) * step; p.y += (dy / dist) * step; step = 0; }
        }
        if (!p.path.length) p.pose = spotPos(p.id, p.spot).pose;
      }
      if (p.bubble && (p.bubble.until -= dt) <= 0) p.bubble = null;
    }
  }

  // ---------- Drawing (low-res) ----------
  const R = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(Math.round(x), Math.round(y), w, h); };

  // Every object gets a 1px dark outline so it stands out from the floor. The object is drawn alone on a
  // scratch layer, the outline is traced around its solid pixels, and the result is copied into the scene.
  const OUTLINE = [20, 14, 34];
  function outlined(x, y, w, h, fn) {
    const x0 = Math.max(0, Math.floor(x) - 2), y0 = Math.max(0, Math.floor(y) - 2);
    const x1 = Math.min(W, Math.ceil(x + w) + 2), y1 = Math.min(H, Math.ceil(y + h) + 2);
    const bw = x1 - x0, bh = y1 - y0;
    if (bw <= 0 || bh <= 0) return;
    sctx.clearRect(x0, y0, bw, bh);
    g = sctx; fn(); g = lctx;
    const img = sctx.getImageData(x0, y0, bw, bh), d = img.data, src = new Uint8ClampedArray(d);
    const solid = (i, j) => i >= 0 && j >= 0 && i < bw && j < bh && src[(j * bw + i) * 4 + 3] >= 200;
    for (let j = 0; j < bh; j++) for (let i = 0; i < bw; i++) {
      const k = (j * bw + i) * 4;
      if (src[k + 3] >= 200) continue;
      if (solid(i - 1, j) || solid(i + 1, j) || solid(i, j - 1) || solid(i, j + 1)) {
        d[k] = OUTLINE[0]; d[k + 1] = OUTLINE[1]; d[k + 2] = OUTLINE[2]; d[k + 3] = 255;
      }
    }
    sctx.putImageData(img, x0, y0);
    lctx.drawImage(scratch, x0, y0, bw, bh, x0, y0, bw, bh);
  }

  function drawRoom() {
    // floor planks
    for (let y = WALL; y < H; y += 6) {
      for (let x = (y / 6) % 2 ? -12 : 0; x < W; x += 24) {
        R(x, y, 24, 6, ((x + y) / 6) % 2 ? "#b88b5c" : "#ad8052");
        R(x, y + 5, 24, 1, "#9a7047");
        R(x + 23, y, 1, 6, "#9a7047");
      }
    }
    // walls
    R(0, 0, W, WALL, "#2d2245");
    R(0, WALL - 6, W, 6, "#3e3060");
    R(0, WALL - 1, W, 1, "#1d162e");
    for (const wx of [20, 96, 236]) {          // windows
      outlined(wx, 8, 40, 24, () => {
        R(wx, 8, 40, 24, "#1b1530");
        R(wx + 2, 10, 36, 20, "#8fd3fe");
        R(wx + 2, 22, 36, 8, "#bde6ff");
        // cloud drifts across the glass (wx+2 .. wx+38) and is clipped to it, entering left and leaving right
        const cx = Math.round(wx + 2 - 8 + ((t * 2 + wx) % 44)), x0 = Math.max(cx, wx + 2), x1 = Math.min(cx + 8, wx + 38);
        if (x1 > x0) R(x0, 13, x1 - x0, 3, "#ffffff");
        R(wx + 19, 10, 2, 20, "#1b1530");
      });
    }
    // logo poster
    outlined(160, 6, 40, 30, () => {
      R(160, 6, 40, 30, "#1b1530"); R(162, 8, 36, 26, "#120d22");
      if (logo && logo.complete) { g.imageSmoothingEnabled = false; g.drawImage(logo, 167, 8, 26, 26); }
    });
    // whiteboard with this quarter's plan
    outlined(300, 8, 60, 26, () => {
      R(300, 8, 60, 26, "#cfd6de"); R(302, 10, 56, 22, "#f4f7fa");
      R(306, 14, 22, 2, "#7c3aed"); R(306, 19, 40, 1, "#64748b"); R(306, 23, 32, 1, "#64748b"); R(306, 27, 36, 1, "#dc2626");
    });
    // clock
    outlined(214, 12, 12, 12, () => {
      R(214, 12, 12, 12, "#1b1530"); R(215, 13, 10, 10, "#f4f7fa"); R(219, 15, 1, 4, "#1d1c1d"); R(220, 18, 3, 1, "#1d1c1d");
    });
    // lounge rug
    outlined(286, 116, 90, 72, () => {
      R(286, 116, 90, 72, "#4b3b78"); R(290, 120, 82, 64, "#5d4a91");
      for (let i = 0; i < 6; i++) R(294 + i * 13, 150, 6, 2, "#7c66b8");
    });
  }

  function sprite(x, y, look, shirt, pose, frame, typing) {
    const colors = { h: look.hair, s: look.skin, e: "#1d1c1d", c: shirt, d: shade(shirt, 0.75), p: "#2f3550", k: "#1a1a22" };
    const rows = BODY.slice();
    if (pose === "walk") { const f = WALK[frame % 2]; rows[13] = f[0]; rows[14] = f[1]; rows[15] = f[2]; }
    if (typing) { rows[9] = ".cccddccc."; rows[10] = ".cccccccc."; }
    const by = pose === "walk" ? (frame % 2) : 0;
    for (let r = 0; r < rows.length; r++) {
      for (let c = 0; c < 10; c++) {
        const k = rows[r][c];
        if (k !== ".") R(x + c, y + r - by, 1, 1, colors[k]);
      }
    }
    // hair styles
    const H_ = (cx, cy) => R(x + cx, y + cy - by, 1, 1, look.hair);
    if (look.style === "long") for (let r = 2; r <= 7; r++) { H_(1, r); H_(8, r); }
    if (look.style === "bun") { H_(4, -1); H_(5, -1); H_(4, -2); H_(5, -2); }
    if (look.style === "spiky") { H_(3, -1); H_(5, -1); H_(7, -1); }
    // blink
    if (Math.floor(t * 10 + x) % 37 === 0) { R(x + 3, y + 3 - by, 1, 1, look.skin); R(x + 6, y + 3 - by, 1, 1, look.skin); }
  }

  function drawDesk(d, busy) {
    R(d.x, d.y, DESK_W, 6, "#9a6534"); R(d.x, d.y, DESK_W, 1, "#b47a43");
    R(d.x, d.y + 6, DESK_W, 10, "#6e4520"); R(d.x + 2, d.y + 8, DESK_W - 4, 1, "#5a381a");
    R(d.x + 2, d.y + 16, 3, 3, "#4a2e14"); R(d.x + DESK_W - 5, d.y + 16, 3, 3, "#4a2e14");
    // monitor (back faces us) on the left, glow when busy
    const mx = d.x + 3, my = d.y - 9;
    if (busy) { g.globalAlpha = 0.35 + 0.15 * Math.sin(t * 6); R(mx - 2, my - 2, 16, 13, "#7dd3fc"); g.globalAlpha = 1; }
    R(mx, my, 12, 9, "#23232e"); R(mx + 1, my + 1, 10, 7, "#2e2e3c"); R(mx + 5, my + 9, 2, 2, "#23232e");
    if (busy) R(mx + 10, my + 7, 1, 1, "#4ade80");
    // keyboard, mug, papers
    R(d.x + 17, d.y + 1, 12, 3, "#d0d4dc"); R(d.x + 18, d.y + 2, 10, 1, "#9ca3af");
    R(d.x + 36, d.y - 1, 4, 4, "#f4f7fa"); R(d.x + 40, d.y, 1, 2, "#f4f7fa");
    R(d.x + 31, d.y + 1, 4, 3, "#fef3c7");
  }

  function drawChair(x, y) {   // office chair seen from the front: rounded back, armrests
    R(x + 1, y + 4, 8, 1, "#1f2433"); R(x, y + 5, 10, 8, "#1f2433");
    R(x + 1, y + 5, 8, 7, "#2f6f8f"); R(x + 2, y + 5, 6, 1, "#3d8db5");
    R(x - 1, y + 10, 2, 3, "#1f2433"); R(x + 9, y + 10, 2, 3, "#1f2433");
  }

  function drawCouchBack() { R(294, 58, 76, 12, "#6c3483"); R(294, 58, 76, 2, "#8e44ad"); }
  function drawCouchFront() {
    R(292, 64, 4, 16, "#5b2c6f"); R(368, 64, 4, 16, "#5b2c6f");
    R(296, 66, 72, 10, "#8e44ad"); R(296, 66, 72, 1, "#a569bd"); R(296, 76, 72, 3, "#5b2c6f");
  }
  function drawCoffee() {
    R(356, 128, 16, 26, "#3f3f46"); R(358, 131, 12, 8, "#18181b"); R(368, 133, 1, 1, "#ef4444");
    R(361, 143, 6, 5, "#f4f7fa"); if (Math.floor(t * 2) % 2) R(363, 140, 1, 2, "#e5e7eb");
    R(354, 154, 20, 4, "#27272a");
  }
  function drawPlant(x, y) {
    R(x + 2, y + 10, 8, 7, "#a0522d"); R(x + 2, y + 10, 8, 1, "#b8653a");
    R(x + 1, y + 2, 10, 8, "#2e8b57"); R(x + 3, y, 6, 4, "#3cb371"); R(x, y + 5, 3, 3, "#3cb371"); R(x + 9, y + 4, 3, 3, "#3cb371");
  }

  function drawScene(working) {
    drawRoom();
    const items = [];
    for (const d of desks) {
      if (!people[d.id]) continue;
      items.push({ key: d.seat.y + 14, draw: () => outlined(d.seat.x - 1, d.seat.y + 4, 12, 9, () => drawChair(d.seat.x, d.seat.y)) });
      items.push({ key: d.y + 16, draw: () => outlined(d.x - 2, d.y - 11, 48, 30, () => drawDesk(d, !!working[d.id] && isSeated(people[d.id]))) });
    }
    items.push({ key: 60, draw: () => outlined(294, 58, 76, 12, drawCouchBack) },
      { key: 80, draw: () => outlined(292, 64, 80, 16, drawCouchFront) },
      { key: 158, draw: () => outlined(354, 128, 20, 30, drawCoffee) });
    const plant = (x, y) => () => outlined(x, y, 12, 17, () => drawPlant(x, y));
    items.push({ key: 205, draw: plant(276, 188) }, { key: 63, draw: plant(372, 46) }, { key: 63, draw: plant(268, 46) });
    for (const p of Object.values(people)) {
      const a = meta.agents[p.id], look = LOOKS[p.id] || LOOKS.euler;
      const frame = Math.floor(t * 6);
      const typing = !!working[p.id] && isSeated(p) && frame % 2 === 0;
      items.push({ key: p.y + 16, draw: () => {
        outlined(p.x - 1, p.y - 3, 12, 20, () => sprite(p.x, p.y, look, a.color, p.pose, frame, typing));
        if (hover === p.id) { g.globalAlpha = 0.25; R(p.x - 1, p.y - 3, 12, 20, "#ffffff"); g.globalAlpha = 1; }
      } });
    }
    items.sort((a, b) => a.key - b.key).forEach((i) => i.draw());
  }

  const isSeated = (p) => p.spot.kind === "desk" && !p.path.length;

  // ---------- Drawing (full-res overlay: names and bubbles) ----------
  function overlay(working) {
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    for (const p of Object.values(people)) {
      const a = meta.agents[p.id];
      const g = regionOf(p.x + 5), s = g.s;
      const cx = g.dx + (p.x + 5 - g.sx) * s, top = g.dy + (p.y - 3) * s;
      ctx.font = `700 ${Math.max(10, Math.round(s * 3.6))}px Lato, sans-serif`;
      const w = ctx.measureText(a.name).width + 10, hgt = Math.max(14, s * 5);
      ctx.fillStyle = hover === p.id ? a.color : "rgba(20,16,32,.78)";
      roundRect(cx - w / 2, top - hgt, w, hgt, 4); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.fillText(a.name, cx, top - 2);
      let text = null;
      if (p.bubble) text = p.bubble.text;
      else if (working[p.id]) text = ".".repeat(1 + (Math.floor(t * 3) % 3));
      if (text) bubble(cx, top - hgt - 4, text);
    }
  }

  function bubble(cx, bottom, text) {
    const s = view.s;
    ctx.font = `400 ${Math.max(11, Math.round(s * 3.6))}px Lato, sans-serif`;
    const w = Math.min(ctx.measureText(text).width + 14, 260), h = Math.max(18, s * 6.5);
    const x = Math.max(4, Math.min(canvas.width / dpr() - w - 4, cx - w / 2)), y = bottom - h;
    ctx.fillStyle = "#ffffff"; ctx.strokeStyle = "#1d1c1d"; ctx.lineWidth = 1.5;
    roundRect(x, y, w, h, 6); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx - 4, bottom); ctx.lineTo(cx, bottom + 5); ctx.lineTo(cx + 4, bottom); ctx.fill();
    ctx.fillStyle = "#1d1c1d"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.save(); ctx.beginPath(); ctx.rect(x + 6, y, w - 12, h); ctx.clip();
    ctx.fillText(text, x + 7, y + h / 2 + 1); ctx.restore();
    ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  const dpr = () => window.devicePixelRatio || 1;

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    const d = dpr();
    canvas.width = Math.floor(box.width * d); canvas.height = Math.floor(box.height * d);
    canvas.style.width = `${box.width}px`; canvas.style.height = `${box.height}px`;
    ctx.setTransform(d, 0, 0, d, 0, 0);
    const fit = (sx, sw, top, bw, bh, label) => {
      const s = Math.min(bw / sw, bh / H) * 0.98;
      return { sx, sw, s, label, dx: Math.floor((bw - sw * s) / 2), dy: Math.floor(top + (bh - H * s) / 2), top, bh };
    };
    if (box.height > box.width) {     // portrait: two stacked halves
      const half = box.height / 2;
      view = { split: true, regions: [fit(0, SPLIT, 0, box.width, half, "Desks"), fit(SPLIT, W - SPLIT, half, box.width, half, "Lounge")] };
    } else {
      view = { split: false, regions: [fit(0, W, 0, box.width, box.height)] };
    }
    view.s = Math.min(...view.regions.map((g) => g.s));
  }

  // Which drawn region shows scene x (people in the corridor switch halves as they cross SPLIT).
  const regionOf = (x) => view.regions.find((g) => x >= g.sx && x < g.sx + g.sw) || view.regions[view.regions.length - 1];

  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000 || 0); last = now; t += dt;
    const working = getWorking() || {};
    update(dt);
    lctx.clearRect(0, 0, W, H);
    drawScene(working);
    const box = canvas.parentElement.getBoundingClientRect();
    ctx.clearRect(0, 0, box.width, box.height);
    ctx.imageSmoothingEnabled = false;
    for (const g of view.regions) ctx.drawImage(low, g.sx, 0, g.sw, H, g.dx, g.dy, g.sw * g.s, H * g.s);
    if (view.split) {
      const mid = view.regions[1].top;
      ctx.fillStyle = "#2d2245"; ctx.fillRect(0, mid - 2, box.width, 4);
      ctx.font = "700 12px Lato, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      for (const g of view.regions) {
        const w = ctx.measureText(g.label).width + 12;
        ctx.fillStyle = "rgba(20,16,32,.78)"; roundRect(8, g.top + 8, w, 20, 4); ctx.fill();
        ctx.fillStyle = "#fff"; ctx.fillText(g.label, 14, g.top + 12);
      }
    }
    overlay(working);
    raf = requestAnimationFrame(frame);
  }

  function pick(ev) {
    const r = canvas.getBoundingClientRect(), cy = ev.clientY - r.top;
    const g = view.regions.find((k) => cy >= k.top && cy < k.top + k.bh) || view.regions[0];
    const x = g.sx + (ev.clientX - r.left - g.dx) / g.s, y = (cy - g.dy) / g.s;
    if (x < g.sx - 4 || x > g.sx + g.sw + 4) return null;
    let best = null;
    for (const p of Object.values(people)) if (x >= p.x - 2 && x <= p.x + 12 && y >= p.y - 8 && y <= p.y + 17) best = p.id;
    return best;
  }

  window.Office = {
    start(el, m, workingFn, pickFn) {
      canvas = el; ctx = canvas.getContext("2d"); meta = m; getWorking = workingFn; onPick = pickFn;
      if (!low) {
        low = document.createElement("canvas"); low.width = W; low.height = H; lctx = low.getContext("2d"); g = lctx;
        scratch = document.createElement("canvas"); scratch.width = W; scratch.height = H;
        sctx = scratch.getContext("2d", { willReadFrequently: true });
        logo = new Image(); logo.src = "/static/brand/logo-256.png";
        makePeople();
        canvas.addEventListener("mousemove", (e) => { hover = pick(e); canvas.style.cursor = hover ? "pointer" : "default"; });
        canvas.addEventListener("mouseleave", () => { hover = null; });
        canvas.addEventListener("click", (e) => { const id = pick(e); if (id) onPick(id); });
        window.addEventListener("resize", () => { if (raf) resize(); });
      }
      resize();
      const ff = Number(new URLSearchParams(location.search).get("ff")) || 0;   // test hook: fast-forward N seconds
      for (let i = 0; i < ff * 20; i++) { t += 0.05; update(0.05); }
      if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
    },
    stop() { if (raf) cancelAnimationFrame(raf); raf = null; },
    say(agent, text) {
      const p = people[agent];
      if (!p) return;
      const clean = text.replace(/[`*_#>]/g, "").replace(/\s+/g, " ").trim();
      p.bubble = { text: clean.length > 48 ? `${clean.slice(0, 46)}…` : clean, until: 6 };
    },
  };
})();
