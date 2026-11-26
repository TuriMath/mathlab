// TuriMath office: an evening study, in pixel art. Original art, drawn in code.
// Bookshelves, a chalkboard, a fire with armchairs, a sleeping cat, tea and a gramophone; warm lamp light in a dim room.
// Working agents sit at their writing desks (their lamp turns on); idle ones wander to the fireside.
(() => {
  const W = 384, H = 216;          // low-res scene size, scaled up with crisp pixels
  const WALL = 44, CORR = 104;     // wall height; corridor row (person top y) between desk rows
  const SPEED = 26;                // px per second: an unhurried stroll
  const ORDER = ["hilbert", "noether", "gauss", "euler", "godel"];

  const LOOKS = {
    hilbert: { hair: "#d9d9d9", skin: "#ffdbac", style: "short" },
    noether: { hair: "#4a3222", skin: "#f1c27d", style: "bun" },
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
  const hash = (n) => (((n * 2654435761) >>> 0) % 1000) / 1000;   // stable pseudo-random in [0, 1)

  // ---------- Layout ----------
  const DESK_W = 44, DESK_H = 16;
  const desks = ORDER.map((id, i) => {
    const x = 16 + (i % 4) * 64, y = i < 4 ? 78 : 148;
    return { id, x, y, seat: { x: x + DESK_W / 2 - 5, y: y - 12 }, aisle: x - 10 };
  });
  // Fireside: two armchairs by the fire, a loveseat at the back of the rug, and places to stand.
  const LOUNGE = [
    { x: 281, y: 52, pose: "sit" }, { x: 353, y: 52, pose: "sit" },
    { x: 304, y: 158, pose: "sit" }, { x: 320, y: 158, pose: "sit" }, { x: 336, y: 158, pose: "sit" },
    { x: 288, y: 122, pose: "stand" }, { x: 350, y: 118, pose: "stand" }, { x: 266, y: 150, pose: "stand" },
    { x: 366, y: 144, pose: "stand" },
  ];
  const FIRE = { x: 302, y: 22, w: 40, h: 28 };   // fireplace (mantel on top)
  const RUG = { x: 268, y: 70, w: 112, h: 74 };
  const CAT = { x: 314, y: 98 };
  const TEA = { x: 304, y: 128 };
  const GRAMO = { x: 176, y: 150 };
  const GLOBE = { x: 112, y: 150 };

  // ---------- State ----------
  let canvas, ctx, low, lctx, g, scratch, sctx, meta, getWorking, onPick, raf = null, last = 0, t = 0;
  let people = {}, logo = null, hover = null, view = { s: 1, regions: [] };
  // Tall screens (phones) split the scene: desks on top, fireside below. SPLIT is the scene x where the lounge starts.
  const SPLIT = 258;

  function makePeople() {
    people = {};
    const working = getWorking() || {};
    const free = LOUNGE.map((_, i) => i).sort(() => Math.random() - 0.5);
    ORDER.forEach((id) => {
      if (!meta.agents[id]) return;
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
          p.next = 14 + Math.random() * 20;          // idle agents linger by the fire
          goTo(p, Math.random() < 0.2 ? { kind: "desk" } : freeLoungeSpot(p));
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
  const OUTLINE = [30, 17, 12];
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

  // A 3x5 chalk font for the blackboard. "^" raises the next character (exponents).
  const GLYPHS = {
    a: ["...", ".##", "#.#", "#.#", ".##"], b: ["#..", "##.", "#.#", "#.#", "##."], c: ["...", ".##", "#..", "#..", ".##"],
    e: ["...", ".#.", "###", "#..", ".##"], i: [".#.", "...", ".#.", ".#.", ".#."], π: ["...", "###", "#.#", "#.#", "#.#"],
    0: ["###", "#.#", "#.#", "#.#", "###"], 1: [".#.", "##.", ".#.", ".#.", "###"], 2: ["##.", "..#", ".#.", "#..", "###"],
    "+": ["...", ".#.", "###", ".#.", "..."], "=": ["...", "###", "...", "###", "..."],
  };
  function chalk(str, x, y, color) {
    let raise = 0;
    for (const ch of str) {
      if (ch === "^") { raise = 3; x += 1; continue; }
      const gl = GLYPHS[ch];
      if (gl) for (let r = 0; r < 5; r++) for (let c = 0; c < 3; c++) if (gl[r][c] === "#") R(x + c, y + r - raise, 1, 1, color);
      x += 4; raise = 0;
    }
  }

  function drawRoom() {
    // floor: warm walnut planks
    for (let y = WALL; y < H; y += 6) {
      for (let x = (y / 6) % 2 ? -12 : 0; x < W; x += 24) {
        R(x, y, 24, 6, ((x + y) / 6) % 2 ? "#7a4a2a" : "#714326");
        R(x, y + 5, 24, 1, "#5c3820");
        R(x + 23, y, 1, 6, "#5c3820");
      }
    }
    // walls: green striped wallpaper over wood panelling, fairy lights along the top
    R(0, 0, W, WALL, "#24382e");
    for (let x = 0; x < W; x += 6) R(x, 0, 2, WALL - 14, "#2b4236");
    R(0, WALL - 14, W, 14, "#4a2c19"); R(0, WALL - 14, W, 2, "#6b4026");
    for (let x = 6; x < W; x += 20) R(x, WALL - 10, 14, 8, "#43271a");
    R(0, WALL - 1, W, 1, "#24150d");
    for (let x = 4; x < W; x += 10) {
      const on = Math.sin(t * 1.5 + x * 0.7) > -0.3;
      R(x, 2 + ((x / 10) % 2), 1, 1, on ? ["#ffd27a", "#ff9a8a", "#a7e3ff", "#c4f0a0"][(x / 10) % 4] : "#6b5a3a");
    }

    // bookshelves
    shelf(4, 6, 54, 42, 1);
    shelf(218, 6, 36, 42, 2);

    // window with the night sky, curtains
    outlined(66, 6, 34, 30, () => {
      R(66, 6, 34, 30, "#3a2414"); R(68, 8, 30, 26, "#151a3a"); R(68, 22, 30, 12, "#1c2350");
      R(88, 11, 5, 5, "#f4ecc8"); R(90, 11, 3, 3, "#151a3a");                       // crescent moon
      for (let i = 0; i < 7; i++) {
        const sx = 69 + Math.floor(hash(i + 3) * 28), sy = 9 + Math.floor(hash(i + 11) * 22);
        if (Math.sin(t * 2 + i * 1.9) > -0.2) R(sx, sy, 1, 1, "#ffffff");
      }
      R(82, 8, 2, 26, "#3a2414"); R(68, 20, 30, 1, "#3a2414");
      R(64, 6, 5, 34, "#7a1f2b"); R(65, 6, 1, 34, "#952838"); R(97, 6, 5, 34, "#7a1f2b"); R(100, 6, 1, 34, "#952838");
    });

    // chalkboard: the classics
    outlined(108, 6, 84, 32, () => {
      R(108, 6, 84, 32, "#6b4026"); R(110, 8, 80, 27, "#23403a");
      chalk("a^2+b^2=c^2", 113, 13, "#e9efe4");
      chalk("e^iπ+1=0", 113, 23, "#f3d38a");
      // a right triangle and a little sketch
      for (let i = 0; i < 12; i++) R(162 + i, 30, 1, 1, "#e9efe4");
      for (let i = 0; i < 12; i++) R(173, 18 + i, 1, 1, "#e9efe4");
      for (let i = 0; i < 12; i++) R(162 + i, 30 - i, 1, 1, "#e9efe4");
      R(170, 27, 3, 1, "#e9efe4"); R(170, 27, 1, 3, "#e9efe4");
      R(178, 12, 9, 1, "#b8c4b8"); R(178, 16, 6, 1, "#b8c4b8");
      R(110, 35, 80, 2, "#5a3520"); R(130, 34, 4, 1, "#f4f4f4"); R(150, 34, 3, 1, "#f3d38a");   // ledge, chalk
    });

    // grandfather clock with a swinging pendulum
    outlined(198, 4, 14, 46, () => {
      R(198, 4, 14, 46, "#5a311b"); R(199, 5, 12, 2, "#7a4527");
      R(200, 8, 10, 10, "#e8dcc0"); R(204, 9, 1, 4, "#2a1a10"); R(205, 12, 3, 1, "#2a1a10");
      R(201, 21, 8, 22, "#2d1a0e");
      const px = 205 + Math.round(Math.sin(t * 3) * 2);
      R(205, 21, 1, 14, "#c9a04a"); R(px - 1, 34, 3, 3, "#e0b85a"); R(px, 22, 1, 12, "#c9a04a");
      R(198, 46, 14, 4, "#43240f");
    });

    // fireplace with the lotus framed above it
    outlined(FIRE.x - 4, 2, FIRE.w + 8, FIRE.h + 26, () => {
      // portrait
      R(FIRE.x + 10, 2, 20, 18, "#c9a04a"); R(FIRE.x + 11, 3, 18, 16, "#2a1a33");
      if (logo && logo.complete) { g.imageSmoothingEnabled = false; g.drawImage(logo, FIRE.x + 11, 3, 18, 16); }
      // mantel and brick surround
      R(FIRE.x - 4, FIRE.y - 2, FIRE.w + 8, 4, "#6b4026"); R(FIRE.x - 4, FIRE.y - 2, FIRE.w + 8, 1, "#8a5532");
      R(FIRE.x, FIRE.y + 2, FIRE.w, FIRE.h, "#8c4a32");
      for (let y = FIRE.y + 2; y < FIRE.y + FIRE.h; y += 4)
        for (let x = FIRE.x + ((y / 4) % 2 ? 0 : 3); x < FIRE.x + FIRE.w; x += 6) R(x, y, 5, 3, "#9e5639");
      // firebox
      const fx = FIRE.x + 8, fy = FIRE.y + 9, fw = FIRE.w - 16, fh = FIRE.h - 9;
      R(fx, fy, fw, fh, "#140b08");
      flames(fx + 1, fy + fh - 4, fw - 2, fh - 6);
      R(fx + 2, fy + fh - 4, fw - 4, 2, "#5a3018"); R(fx + 5, fy + fh - 5, 8, 2, "#6e3c1e");   // logs
      R(fx, fy + fh - 2, fw, 2, "#3a2a24");
      // candles on the mantel
      R(FIRE.x - 2, FIRE.y - 7, 2, 5, "#f1e7cf"); R(FIRE.x + FIRE.w, FIRE.y - 7, 2, 5, "#f1e7cf");
      const fl = Math.sin(t * 11) > 0 ? 0 : 1;
      R(FIRE.x - 2 + fl, FIRE.y - 9, 1, 2, "#ffcc55"); R(FIRE.x + FIRE.w + fl, FIRE.y - 9, 1, 2, "#ffcc55");
    });

    // window on the right
    outlined(352, 8, 26, 26, () => {
      R(352, 8, 26, 26, "#3a2414"); R(354, 10, 22, 22, "#151a3a"); R(354, 24, 22, 8, "#1c2350");
      for (let i = 0; i < 5; i++) {
        const sx = 355 + Math.floor(hash(i + 40) * 20), sy = 11 + Math.floor(hash(i + 50) * 18);
        if (Math.sin(t * 1.7 + i * 2.3) > -0.2) R(sx, sy, 1, 1, "#ffffff");
      }
      R(364, 10, 2, 22, "#3a2414"); R(354, 20, 22, 1, "#3a2414");
    });

    // persian rug by the fire
    outlined(RUG.x, RUG.y, RUG.w, RUG.h, () => {
      R(RUG.x, RUG.y, RUG.w, RUG.h, "#7a2a22"); R(RUG.x + 3, RUG.y + 3, RUG.w - 6, RUG.h - 6, "#9c3a2a");
      R(RUG.x + 7, RUG.y + 7, RUG.w - 14, RUG.h - 14, "#7a2a22"); R(RUG.x + 9, RUG.y + 9, RUG.w - 18, RUG.h - 18, "#a8472f");
      for (let x = RUG.x + 4; x < RUG.x + RUG.w - 4; x += 6) { R(x, RUG.y + 4, 3, 1, "#d9a441"); R(x, RUG.y + RUG.h - 5, 3, 1, "#d9a441"); }
      const cx = RUG.x + RUG.w / 2, cy = RUG.y + RUG.h / 2;
      R(cx - 10, cy - 1, 20, 2, "#d9a441"); R(cx - 1, cy - 8, 2, 16, "#d9a441"); R(cx - 4, cy - 4, 8, 8, "#2f4a6b"); R(cx - 2, cy - 2, 4, 4, "#d9a441");
    });

    // a second, smaller rug under the reading corner
    outlined(96, 140, 120, 56, () => {
      R(96, 140, 120, 56, "#2f4a3b"); R(99, 143, 114, 50, "#3c5c49");
      for (let x = 102; x < 212; x += 8) R(x, 145, 4, 1, "#c9a04a"), R(x, 190, 4, 1, "#c9a04a");
    });
  }

  function shelf(x, y, w, h, seed) {
    outlined(x, y, w, h, () => {
      R(x, y, w, h, "#4f2c17"); R(x + 2, y + 2, w - 4, h - 4, "#2e1a0e");
      const BOOKS = ["#8e2b2b", "#2f5d50", "#c9a04a", "#2d4a7a", "#6b3d6b", "#d6c7a1", "#a2552b", "#3e6b3e"];
      for (let sy = y + 2, row = 0; sy + 9 < y + h; sy += 10, row++) {
        let bx = x + 3, n = 0;
        while (bx < x + w - 4) {
          const k = seed * 100 + row * 20 + n++, bw = 2 + Math.floor(hash(k) * 2), bh = 6 + Math.floor(hash(k + 7) * 3);
          if (hash(k + 3) < 0.08) { bx += 3; continue; }               // a gap on the shelf
          R(bx, sy + 9 - bh, bw, bh, BOOKS[Math.floor(hash(k + 5) * BOOKS.length)]);
          if (bh > 7) R(bx, sy + 11 - bh, bw, 1, "#e8d9a8");               // a gilt band on the spine
          bx += bw;
        }
        R(x + 2, sy + 9, w - 4, 1, "#6b4026");                              // shelf board
      }
    });
  }

  function flames(x, base, w, h) {
    for (let i = 0; i < w; i++) {
      const f = 0.45 + 0.3 * Math.sin(t * 9 + i * 1.7) + 0.2 * Math.sin(t * 14 + i * 0.6 + 1);
      const fh = Math.max(2, Math.round(h * f * (1 - Math.abs(i - w / 2) / w)));
      R(x + i, base - fh, 1, fh, "#d2401f");
      R(x + i, base - Math.round(fh * 0.7), 1, Math.round(fh * 0.7), "#f08a24");
      R(x + i, base - Math.round(fh * 0.35), 1, Math.round(fh * 0.35), "#ffd45a");
    }
    for (let k = 0; k < 3; k++) {             // embers drifting up
      const ph = (t * 0.6 + k / 3) % 1;
      if (ph < 0.8) R(x + Math.floor(hash(k + Math.floor(t * 0.6)) * w), base - h - ph * 6, 1, 1, "#ffb347");
    }
  }

  function sprite(x, y, look, shirt, pose, frame, typing) {
    const colors = { h: look.hair, s: look.skin, e: "#1d1c1d", c: shirt, d: shade(shirt, 0.75), p: "#3b3040", k: "#1f1612" };
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
    // cosy jumper: a ribbed collar
    R(x + 3, y + 7 - by, 4, 1, shade(shirt, 1.25));
    const H_ = (cx, cy) => R(x + cx, y + cy - by, 1, 1, look.hair);
    if (look.style === "long") for (let r = 2; r <= 7; r++) { H_(1, r); H_(8, r); }
    if (look.style === "bun") { H_(4, -1); H_(5, -1); H_(4, -2); H_(5, -2); }
    if (look.style === "spiky") { H_(3, -1); H_(5, -1); H_(7, -1); }
    if (Math.floor(t * 10 + x) % 37 === 0) { R(x + 3, y + 3 - by, 1, 1, look.skin); R(x + 6, y + 3 - by, 1, 1, look.skin); }
  }

  function drawDesk(d, busy) {
    // writing desk in walnut
    R(d.x, d.y, DESK_W, 6, "#7a4527"); R(d.x, d.y, DESK_W, 1, "#965a33");
    R(d.x, d.y + 6, DESK_W, 10, "#5a311b"); R(d.x + 3, d.y + 8, 17, 6, "#4d2915"); R(d.x + 24, d.y + 8, 17, 6, "#4d2915");
    R(d.x + 11, d.y + 10, 2, 1, "#c9a04a"); R(d.x + 31, d.y + 10, 2, 1, "#c9a04a");
    R(d.x + 2, d.y + 16, 3, 3, "#3e2210"); R(d.x + DESK_W - 5, d.y + 16, 3, 3, "#3e2210");
    // banker's lamp: green shade, brass stem; lit while the agent works
    const lx = d.x + 2, ly = d.y - 10;
    R(lx + 4, ly + 5, 1, 5, "#c9a04a"); R(lx + 2, ly + 9, 5, 1, "#c9a04a");
    R(lx, ly + 2, 9, 3, busy ? "#2f9a5e" : "#1f5e3b"); R(lx + 1, ly + 1, 7, 1, busy ? "#3cb371" : "#2a6e48");
    if (busy) R(lx + 1, ly + 5, 7, 1, "#fff1b8");
    // tea by the lamp; the middle stays clear so the agent's face shows; books, inkwell and quill on the right
    R(d.x + 12, d.y, 3, 3, "#e8dcc0"); R(d.x + 15, d.y + 1, 1, 1, "#e8dcc0");
    if (busy && Math.floor(t * 2) % 2) R(d.x + 13, d.y - 3, 1, 2, "#d8d0c8");
    R(d.x + 16, d.y + 1, 12, 4, "#f1e7cf"); R(d.x + 22, d.y + 1, 1, 4, "#c8b89a");               // open notebook
    if (busy) { const w = 1 + (Math.floor(t * 4) % 4); R(d.x + 17, d.y + 2, w, 1, "#3a3a5a"); R(d.x + 24, d.y + 3, 3, 1, "#3a3a5a"); }
    R(d.x + 30, d.y - 1, 9, 2, "#8e2b2b"); R(d.x + 31, d.y - 3, 8, 2, "#2d4a7a"); R(d.x + 30, d.y - 5, 9, 2, "#c9a04a");
    R(d.x + 40, d.y + 1, 3, 3, "#1c1c2c"); R(d.x + 41, d.y - 4, 1, 5, "#f4f4f4"); R(d.x + 42, d.y - 5, 1, 3, "#e6e6e6");
  }

  function drawChair(x, y) {   // wooden chair with a red cushion, seen from the front
    R(x, y + 3, 10, 2, "#5a311b"); R(x, y + 5, 2, 8, "#5a311b"); R(x + 8, y + 5, 2, 8, "#5a311b");
    R(x + 2, y + 9, 6, 3, "#9b2d30"); R(x + 2, y + 9, 6, 1, "#b8403f");
  }

  function armchairBack(x, y) { R(x, y, 18, 14, "#6e2a33"); R(x + 2, y + 1, 14, 2, "#8a3a44"); for (let i = 3; i < 16; i += 4) R(x + i, y + 5, 1, 1, "#4d1c23"); }
  function armchairFront(x, y) {
    R(x - 1, y + 10, 4, 12, "#5a2129"); R(x + 15, y + 10, 4, 12, "#5a2129");
    R(x + 3, y + 14, 12, 6, "#8a3a44"); R(x + 3, y + 14, 12, 1, "#a34b55"); R(x, y + 20, 18, 2, "#4d1c23");
    R(x, y + 22, 2, 2, "#3e2210"); R(x + 16, y + 22, 2, 2, "#3e2210");
  }
  function loveseatBack() { R(298, 154, 52, 12, "#2f4a6b"); R(298, 154, 52, 2, "#3e6088"); for (let i = 302; i < 348; i += 6) R(i, 159, 1, 1, "#22374f"); }
  function loveseatFront() {
    R(294, 162, 6, 16, "#263d58"); R(348, 162, 6, 16, "#263d58");
    R(300, 166, 48, 8, "#3e6088"); R(300, 166, 48, 1, "#5276a0"); R(300, 174, 48, 3, "#22374f");
    R(296, 177, 2, 3, "#3e2210"); R(350, 177, 2, 3, "#3e2210");
  }

  function drawCat() {
    const { x, y } = CAT, breath = Math.floor(t * 0.8) % 2;
    const fur = "#d9843a", dark = "#a85e22", light = "#f0b070";
    R(x + 2, y + 2 - breath, 10, 1, fur); R(x + 1, y + 3, 12, 4, fur);
    R(x, y, 5, 5, fur); R(x, y - 1, 1, 1, fur); R(x + 4, y - 1, 1, 1, fur);       // head and ears
    R(x + 1, y + 2, 1, 1, "#3a2414"); R(x + 3, y + 2, 1, 1, "#3a2414");          // eyes closed
    R(x + 2, y + 3, 1, 1, "#e88a8a");
    R(x + 6, y + 2, 1, 3, dark); R(x + 9, y + 2, 1, 3, dark); R(x + 2, y + 6, 10, 1, light);
    const sw = Math.round(Math.sin(t * 1.6) * 1.5);
    R(x + 12, y + 5, 3, 1, fur); R(x + 14, y + 4 + Math.min(0, sw), 1, 1 + Math.abs(sw), dark);   // tail
  }

  function drawTea() {
    const { x, y } = TEA;
    R(x, y + 6, 24, 3, "#5a311b"); R(x, y + 6, 24, 1, "#7a4527"); R(x + 2, y + 9, 2, 5, "#3e2210"); R(x + 20, y + 9, 2, 5, "#3e2210");
    R(x + 4, y + 1, 8, 5, "#e8dcc0"); R(x + 6, y, 4, 1, "#e8dcc0"); R(x + 12, y + 2, 2, 1, "#e8dcc0"); R(x + 2, y + 2, 2, 2, "#e8dcc0");
    R(x + 5, y + 3, 6, 1, "#4a7ab8");
    R(x + 16, y + 3, 4, 3, "#e8dcc0"); R(x + 17, y + 3, 2, 1, "#8a5a2a");
  }
  function drawSteam(x, y) {
    for (let k = 0; k < 3; k++) {
      const ph = (t * 0.7 + k / 3) % 1;
      g.globalAlpha = 0.7 * (1 - ph);
      R(x + Math.round(Math.sin(ph * 6 + k) * 1.5), y - ph * 10, 1, 2, "#e8e4ee");
    }
    g.globalAlpha = 1;
  }

  function drawGramophone() {
    const { x, y } = GRAMO;
    R(x, y + 10, 16, 8, "#6b3d22"); R(x, y + 10, 16, 1, "#8a5532"); R(x + 2, y + 9, 12, 1, "#1c1414");
    R(x + 7, y + 4, 2, 6, "#c9a04a");
    R(x + 8, y - 2, 8, 6, "#d9b25a"); R(x + 10, y - 4, 7, 2, "#e8c470"); R(x + 13, y - 6, 5, 2, "#f0d080");
    R(x - 2, y + 18, 20, 3, "#4a2a18");
  }
  function drawNotes() {
    const { x, y } = GRAMO;
    for (let k = 0; k < 3; k++) {
      const ph = (t * 0.35 + k / 3) % 1;
      g.globalAlpha = Math.min(1, 1.6 * (1 - ph));
      const nx = x + 16 + Math.round(Math.sin(ph * 5 + k) * 3) + k * 3, ny = y - 6 - ph * 22;
      R(nx, ny, 1, 4, "#f3d38a"); R(nx - 2, ny + 3, 2, 2, "#f3d38a"); if (k % 2) R(nx + 1, ny, 2, 1, "#f3d38a");
    }
    g.globalAlpha = 1;
  }

  function drawGlobe() {
    const { x, y } = GLOBE;
    R(x + 5, y + 14, 2, 6, "#c9a04a"); R(x + 1, y + 20, 10, 2, "#5a311b");
    R(x + 2, y, 8, 12, "#2d5a8a"); R(x, y + 2, 12, 8, "#2d5a8a");
    const sh = Math.floor(t * 1.2) % 12;
    for (const [lx, ly, lw, lh] of [[1, 3, 3, 3], [5, 6, 4, 2], [8, 2, 2, 3]]) {
      const px = ((lx + sh) % 12);
      if (px + lw <= 12) R(x + px, y + ly, lw, lh, "#5c8a4a");
    }
    R(x + 3, y + 1, 2, 2, "#4a7ab8");
    R(x - 1, y + 5, 1, 4, "#c9a04a"); R(x + 12, y + 5, 1, 4, "#c9a04a"); R(x + 5, y - 1, 2, 1, "#c9a04a");
  }

  function drawFloorLamp(x, y) {
    R(x + 3, y + 8, 1, 24, "#c9a04a"); R(x, y + 32, 7, 2, "#5a311b");
    R(x, y, 7, 2, "#f1e1b8"); R(x - 1, y + 2, 9, 6, "#e8cf96");
  }

  function drawPlant(x, y) {     // a fern in a terracotta pot
    R(x + 2, y + 10, 8, 7, "#a0522d"); R(x + 2, y + 10, 8, 1, "#b8653a");
    R(x + 1, y + 3, 10, 7, "#2f6b3f"); R(x + 4, y, 4, 5, "#3e8a52"); R(x - 1, y + 5, 3, 2, "#3e8a52"); R(x + 10, y + 4, 3, 2, "#3e8a52");
    R(x + 2, y + 1, 1, 3, "#3e8a52"); R(x + 9, y + 1, 1, 3, "#3e8a52");
  }

  function drawScene(working) {
    drawRoom();
    const items = [];
    for (const d of desks) {
      if (!people[d.id]) continue;
      items.push({ key: d.seat.y + 14, draw: () => outlined(d.seat.x - 1, d.seat.y + 3, 12, 11, () => drawChair(d.seat.x, d.seat.y)) });
      items.push({ key: d.y + 16, draw: () => outlined(d.x - 2, d.y - 11, 48, 30, () => drawDesk(d, !!working[d.id] && isSeated(people[d.id]))) });
    }
    const ac = [[277, 46], [349, 46]];   // armchairs either side of the fire
    for (const [x, y] of ac) {
      items.push({ key: y + 4, draw: () => outlined(x, y, 18, 14, () => armchairBack(x, y)) });
      items.push({ key: y + 24, draw: () => outlined(x - 1, y + 10, 20, 14, () => armchairFront(x, y)) });
    }
    items.push({ key: 157, draw: () => outlined(298, 154, 52, 12, loveseatBack) },
      { key: 178, draw: () => outlined(294, 162, 60, 18, loveseatFront) },
      { key: CAT.y + 7, draw: () => outlined(CAT.x, CAT.y - 1, 16, 8, drawCat) },
      { key: TEA.y + 14, draw: () => { outlined(TEA.x, TEA.y, 24, 14, drawTea); drawSteam(TEA.x + 13, TEA.y); } },
      { key: GRAMO.y + 20, draw: () => { outlined(GRAMO.x - 2, GRAMO.y - 6, 20, 27, drawGramophone); drawNotes(); } },
      { key: GLOBE.y + 22, draw: () => outlined(GLOBE.x - 1, GLOBE.y - 1, 14, 23, drawGlobe) },
      { key: 78, draw: () => outlined(370, 44, 9, 34, () => drawFloorLamp(371, 44)) });
    const plant = (x, y) => () => outlined(x - 1, y, 14, 17, () => drawPlant(x, y));
    items.push({ key: 205, draw: plant(262, 192) }, { key: 205, draw: plant(368, 192) }, { key: 61, draw: plant(258, 44) },
      { key: 205, draw: plant(226, 192) });
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
    light(working);
  }

  // Evening light: dim the room, then add warm pools from the fire, the lamps and the candles.
  function light(working) {
    g.fillStyle = "rgba(22, 10, 28, 0.38)"; g.fillRect(0, 0, W, H);
    g.globalCompositeOperation = "lighter";
    const pool = (x, y, r, rgb, a) => {
      const gr = g.createRadialGradient(x, y, 0, x, y, r);
      gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(1, `rgba(${rgb},0)`);
      g.fillStyle = gr; g.fillRect(x - r, y - r, 2 * r, 2 * r);
    };
    const flick = 0.85 + 0.1 * Math.sin(t * 7) + 0.05 * Math.sin(t * 17);
    pool(FIRE.x + FIRE.w / 2, FIRE.y + 24, 78 * flick, "255,130,50", 0.30);
    pool(FIRE.x + FIRE.w / 2, FIRE.y + 24, 26, "255,190,90", 0.25 * flick);
    pool(374, 50, 34, "255,200,120", 0.22);
    pool(FIRE.x - 1, FIRE.y - 8, 8, "255,200,100", 0.3); pool(FIRE.x + FIRE.w + 1, FIRE.y - 8, 8, "255,200,100", 0.3);
    for (const d of desks) {
      if (!people[d.id]) continue;
      const on = !!working[d.id] && isSeated(people[d.id]);
      pool(d.x + 6, d.y - 3, on ? 30 : 10, "255,215,130", on ? 0.32 : 0.08);
    }
    pool(83, 20, 20, "120,140,255", 0.08); pool(365, 21, 16, "120,140,255", 0.07);   // moonlight at the windows
    g.globalCompositeOperation = "source-over";
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
      ctx.fillStyle = hover === p.id ? a.color : "rgba(36,22,14,.82)";
      roundRect(cx - w / 2, top - hgt, w, hgt, 4); ctx.fill();
      ctx.fillStyle = "#fbf1de"; ctx.fillText(a.name, cx, top - 2);
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
    ctx.fillStyle = "#fdf6e8"; ctx.strokeStyle = "#3a2414"; ctx.lineWidth = 1.5;
    roundRect(x, y, w, h, 6); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx - 4, bottom); ctx.lineTo(cx, bottom + 5); ctx.lineTo(cx + 4, bottom); ctx.fill();
    ctx.fillStyle = "#2a1a10"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
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
      view = { split: true, regions: [fit(0, SPLIT, 0, box.width, half, "Desks"), fit(SPLIT, W - SPLIT, half, box.width, half, "Fireside")] };
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
      ctx.fillStyle = "#3a2414"; ctx.fillRect(0, mid - 2, box.width, 4);
      ctx.font = "700 12px Lato, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      for (const g of view.regions) {
        const w = ctx.measureText(g.label).width + 12;
        ctx.fillStyle = "rgba(36,22,14,.82)"; roundRect(8, g.top + 8, w, 20, 4); ctx.fill();
        ctx.fillStyle = "#fbf1de"; ctx.fillText(g.label, 14, g.top + 12);
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
