(function () {
  const canvas = document.getElementById("zoneCanvas");
  const image = document.getElementById("frameImage");
  const form = document.getElementById("zonesForm");
  const zonesInput = document.getElementById("zonesInput");
  const zoneCount = document.getElementById("zoneCount");
  const zoneTypes = document.getElementById("zoneTypes");
  const zoneName = document.getElementById("zoneName");
  const undoZone = document.getElementById("undoZone");
  const clearZones = document.getElementById("clearZones");
  const ctx = canvas.getContext("2d");

  let zones = Array.isArray(initialZones) ? [...initialZones] : [];
  let currentType = "puerta";
  let drawing = false;
  let start = null;
  let pointer = null;
  let metrics = { scale: 1, offsetX: 0, offsetY: 0, displayW: 1, displayH: 1 };

  function nextZoneId(type) {
    const count = zones.filter(zone => zone.type === type).length + 1;
    return `${type}_${count}`;
  }

  function defaultName(type) {
    const style = zoneStyles[type] || zoneStyles.zona;
    return `${style.label} ${zones.filter(zone => zone.type === type).length + 1}`;
  }

  function buildTypeButtons() {
    zoneTypes.innerHTML = "";
    Object.entries(zoneStyles).forEach(([type, style]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `zone-type ${type === currentType ? "selected" : ""}`;
      button.style.setProperty("--zone-color", style.hex);
      button.innerHTML = `<span></span><strong>${style.label}</strong>`;
      button.addEventListener("click", () => {
        currentType = type;
        buildTypeButtons();
      });
      zoneTypes.appendChild(button);
    });
  }

  function resizeCanvas() {
    const shell = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.max(320, Math.floor(shell.width));
    canvas.height = Math.max(320, Math.floor(shell.height));
    const scale = Math.min(canvas.width / frameWidth, canvas.height / frameHeight);
    metrics = {
      scale,
      displayW: frameWidth * scale,
      displayH: frameHeight * scale,
      offsetX: (canvas.width - frameWidth * scale) / 2,
      offsetY: (canvas.height - frameHeight * scale) / 2
    };
    draw();
  }

  function originalToCanvas(x, y) {
    return {
      x: metrics.offsetX + x * metrics.scale,
      y: metrics.offsetY + y * metrics.scale
    };
  }

  function canvasToOriginal(x, y) {
    return {
      x: Math.round(Math.max(0, Math.min(frameWidth - 1, (x - metrics.offsetX) / metrics.scale))),
      y: Math.round(Math.max(0, Math.min(frameHeight - 1, (y - metrics.offsetY) / metrics.scale)))
    };
  }

  function insideImage(x, y) {
    return x >= metrics.offsetX && y >= metrics.offsetY && x <= metrics.offsetX + metrics.displayW && y <= metrics.offsetY + metrics.displayH;
  }

  function clampCanvas(x, y) {
    return {
      x: Math.max(metrics.offsetX, Math.min(metrics.offsetX + metrics.displayW, x)),
      y: Math.max(metrics.offsetY, Math.min(metrics.offsetY + metrics.displayH, y))
    };
  }

  function drawZone(zone, isDraft) {
    const style = zoneStyles[zone.type] || zoneStyles.zona;
    const a = originalToCanvas(zone.x1, zone.y1);
    const b = originalToCanvas(zone.x2, zone.y2);
    const x = Math.min(a.x, b.x);
    const y = Math.min(a.y, b.y);
    const w = Math.abs(b.x - a.x);
    const h = Math.abs(b.y - a.y);
    ctx.save();
    ctx.strokeStyle = style.hex;
    ctx.fillStyle = `${style.hex}22`;
    ctx.lineWidth = isDraft ? 2 : 3;
    if (isDraft) ctx.setLineDash([8, 6]);
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x, y, w, h);
    if (!isDraft) {
      const label = zone.name || zone.id;
      ctx.setLineDash([]);
      ctx.fillStyle = "#0B0F19";
      ctx.strokeStyle = style.hex;
      const labelW = Math.min(Math.max(label.length * 8 + 22, 130), 280);
      const labelY = Math.max(metrics.offsetY + 8, y - 30);
      ctx.fillRect(x, labelY, labelW, 24);
      ctx.strokeRect(x, labelY, labelW, 24);
      ctx.fillStyle = style.hex;
      ctx.font = "700 12px Arial";
      ctx.fillText(label, x + 10, labelY + 16);
    }
    ctx.restore();
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#070A11";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (image.complete) {
      ctx.drawImage(image, metrics.offsetX, metrics.offsetY, metrics.displayW, metrics.displayH);
    }
    ctx.strokeStyle = "#2F80ED";
    ctx.lineWidth = 2;
    ctx.strokeRect(metrics.offsetX, metrics.offsetY, metrics.displayW, metrics.displayH);
    zones.forEach(zone => drawZone(zone, false));
    if (drawing && start && pointer) {
      const a = canvasToOriginal(start.x, start.y);
      const b = canvasToOriginal(pointer.x, pointer.y);
      drawZone({ type: currentType, name: "Nueva zona", x1: a.x, y1: a.y, x2: b.x, y2: b.y }, true);
    }
    zoneCount.textContent = `${zones.length} ${zones.length === 1 ? "zona" : "zonas"}`;
  }

  canvas.addEventListener("pointerdown", event => {
    const rect = canvas.getBoundingClientRect();
    const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    if (!insideImage(point.x, point.y)) return;
    drawing = true;
    start = clampCanvas(point.x, point.y);
    pointer = start;
    draw();
  });

  canvas.addEventListener("pointermove", event => {
    if (!drawing) return;
    const rect = canvas.getBoundingClientRect();
    pointer = clampCanvas(event.clientX - rect.left, event.clientY - rect.top);
    draw();
  });

  canvas.addEventListener("pointerup", event => {
    if (!drawing || !start) return;
    drawing = false;
    const rect = canvas.getBoundingClientRect();
    pointer = clampCanvas(event.clientX - rect.left, event.clientY - rect.top);
    const a = canvasToOriginal(start.x, start.y);
    const b = canvasToOriginal(pointer.x, pointer.y);
    const x1 = Math.min(a.x, b.x);
    const x2 = Math.max(a.x, b.x);
    const y1 = Math.min(a.y, b.y);
    const y2 = Math.max(a.y, b.y);
    if (Math.abs(x2 - x1) >= 10 && Math.abs(y2 - y1) >= 10) {
      zones.push({
        id: nextZoneId(currentType),
        name: zoneName.value.trim() || defaultName(currentType),
        type: currentType,
        x1,
        y1,
        x2,
        y2
      });
      zoneName.value = "";
    }
    start = null;
    pointer = null;
    draw();
  });

  undoZone.addEventListener("click", () => {
    zones.pop();
    draw();
  });

  clearZones.addEventListener("click", () => {
    zones = [];
    draw();
  });

  form.addEventListener("submit", () => {
    zonesInput.value = JSON.stringify(zones);
  });

  image.addEventListener("load", resizeCanvas);
  window.addEventListener("resize", resizeCanvas);
  buildTypeButtons();
  resizeCanvas();
})();
