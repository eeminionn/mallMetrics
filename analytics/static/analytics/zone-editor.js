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
  let resizing = null;
  let start = null;
  let pointer = null;
  let labelHitAreas = [];
  let metrics = { scale: 1, offsetX: 0, offsetY: 0, displayW: 1, displayH: 1 };

  function nextZoneId(type) {
    const count = zones.filter(zone => zone.type === type).length + 1;
    return `${type}_${count}`;
  }

  function defaultName(type) {
    const style = zoneStyles[type] || zoneStyles.zona;
    return `${style.label} ${zones.filter(zone => zone.type === type).length + 1}`;
  }

  function normalizeZone(zone) {
    const x1 = Math.min(zone.x1, zone.x2);
    const x2 = Math.max(zone.x1, zone.x2);
    const y1 = Math.min(zone.y1, zone.y2);
    const y2 = Math.max(zone.y1, zone.y2);
    zone.x1 = x1;
    zone.x2 = x2;
    zone.y1 = y1;
    zone.y2 = y2;
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

  function zoneCanvasRect(zone) {
    const a = originalToCanvas(zone.x1, zone.y1);
    const b = originalToCanvas(zone.x2, zone.y2);
    return {
      x: Math.min(a.x, b.x),
      y: Math.min(a.y, b.y),
      w: Math.abs(b.x - a.x),
      h: Math.abs(b.y - a.y),
      corners: {
        nw: { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y) },
        ne: { x: Math.max(a.x, b.x), y: Math.min(a.y, b.y) },
        se: { x: Math.max(a.x, b.x), y: Math.max(a.y, b.y) },
        sw: { x: Math.min(a.x, b.x), y: Math.max(a.y, b.y) }
      }
    };
  }

  function drawHandle(point, color) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#f7fff9";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = color;
    ctx.stroke();
    ctx.restore();
  }

  function drawEditIcon(cx, cy) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, Math.PI * 2);
    ctx.fillStyle = "#f7fff9";
    ctx.fill();
    ctx.strokeStyle = "#0a0f0c";
    ctx.lineWidth = 1.7;
    ctx.beginPath();
    ctx.moveTo(cx - 3.5, cy + 3.5);
    ctx.lineTo(cx + 3, cy - 3);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx + 1.5, cy - 4.5);
    ctx.lineTo(cx + 4.5, cy - 1.5);
    ctx.stroke();
    ctx.restore();
  }

  function drawZone(zone, index, isDraft) {
    const style = zoneStyles[zone.type] || zoneStyles.zona;
    const rect = zoneCanvasRect(zone);
    ctx.save();
    ctx.strokeStyle = style.hex;
    ctx.fillStyle = `${style.hex}22`;
    ctx.lineWidth = isDraft ? 2 : 3;
    if (isDraft) ctx.setLineDash([8, 6]);
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);

    if (!isDraft) {
      const label = zone.name || zone.id;
      ctx.setLineDash([]);
      const labelW = Math.min(Math.max(label.length * 8 + 48, 150), 310);
      const labelY = Math.max(metrics.offsetY + 8, rect.y - 32);
      const labelX = Math.min(rect.x, metrics.offsetX + metrics.displayW - labelW - 4);
      const editX = labelX + labelW - 26;
      const editY = labelY + 4;

      ctx.fillStyle = "#0a0f0c";
      ctx.strokeStyle = style.hex;
      ctx.lineWidth = 1;
      ctx.fillRect(labelX, labelY, labelW, 26);
      ctx.strokeRect(labelX, labelY, labelW, 26);

      ctx.fillStyle = style.hex;
      ctx.font = "700 12px Arial";
      ctx.fillText(label, labelX + 10, labelY + 17);

      drawEditIcon(editX + 8, editY + 8);

      labelHitAreas.push({ index, x: editX, y: editY, w: 18, h: 18 });
      Object.values(rect.corners).forEach(point => drawHandle(point, style.hex));
    }
    ctx.restore();
  }

  function draw() {
    labelHitAreas = [];
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#050806";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (image.complete) {
      ctx.drawImage(image, metrics.offsetX, metrics.offsetY, metrics.displayW, metrics.displayH);
    }
    ctx.strokeStyle = "#32d583";
    ctx.lineWidth = 2;
    ctx.strokeRect(metrics.offsetX, metrics.offsetY, metrics.displayW, metrics.displayH);
    zones.forEach((zone, index) => drawZone(zone, index, false));
    if (drawing && start && pointer) {
      const a = canvasToOriginal(start.x, start.y);
      const b = canvasToOriginal(pointer.x, pointer.y);
      drawZone({ type: currentType, name: "Nueva zona", x1: a.x, y1: a.y, x2: b.x, y2: b.y }, -1, true);
    }
    zoneCount.textContent = `${zones.length} ${zones.length === 1 ? "zona" : "zonas"}`;
  }

  function pointerFromEvent(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function findEditHit(point) {
    return labelHitAreas.find(area => (
      point.x >= area.x && point.x <= area.x + area.w &&
      point.y >= area.y && point.y <= area.y + area.h
    ));
  }

  function findCornerHit(point) {
    for (let index = zones.length - 1; index >= 0; index -= 1) {
      const rect = zoneCanvasRect(zones[index]);
      for (const [corner, handle] of Object.entries(rect.corners)) {
        const distance = Math.hypot(point.x - handle.x, point.y - handle.y);
        if (distance <= 11) {
          return { index, corner };
        }
      }
    }
    return null;
  }

  function applyResize(point) {
    if (!resizing) return;
    const zone = zones[resizing.index];
    const p = canvasToOriginal(point.x, point.y);

    if (resizing.corner.includes("n")) zone.y1 = p.y;
    if (resizing.corner.includes("s")) zone.y2 = p.y;
    if (resizing.corner.includes("w")) zone.x1 = p.x;
    if (resizing.corner.includes("e")) zone.x2 = p.x;
  }

  function editZoneName(index) {
    const zone = zones[index];
    const nextName = window.prompt("Nombre de la zona", zone.name || zone.id);
    if (nextName && nextName.trim()) {
      zone.name = nextName.trim();
      draw();
    }
  }

  function releasePointer(event) {
    if (canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
  }

  canvas.addEventListener("pointerdown", event => {
    const point = pointerFromEvent(event);
    const editHit = findEditHit(point);
    if (editHit) {
      editZoneName(editHit.index);
      return;
    }

    const cornerHit = findCornerHit(point);
    if (cornerHit) {
      resizing = cornerHit;
      canvas.setPointerCapture(event.pointerId);
      canvas.style.cursor = `${cornerHit.corner}-resize`;
      return;
    }

    if (!insideImage(point.x, point.y)) return;
    drawing = true;
    start = clampCanvas(point.x, point.y);
    pointer = start;
    canvas.setPointerCapture(event.pointerId);
    draw();
  });

  canvas.addEventListener("pointermove", event => {
    const point = pointerFromEvent(event);

    if (resizing) {
      applyResize(clampCanvas(point.x, point.y));
      draw();
      return;
    }

    if (drawing) {
      pointer = clampCanvas(point.x, point.y);
      draw();
      return;
    }

    const editHit = findEditHit(point);
    const cornerHit = findCornerHit(point);
    if (editHit) {
      canvas.style.cursor = "pointer";
    } else if (cornerHit) {
      canvas.style.cursor = `${cornerHit.corner}-resize`;
    } else {
      canvas.style.cursor = insideImage(point.x, point.y) ? "crosshair" : "default";
    }
  });

  canvas.addEventListener("pointerup", event => {
    if (resizing) {
      normalizeZone(zones[resizing.index]);
      resizing = null;
      releasePointer(event);
      canvas.style.cursor = "crosshair";
      draw();
      return;
    }

    if (!drawing || !start) return;
    drawing = false;
    const endPoint = pointerFromEvent(event);
    pointer = clampCanvas(endPoint.x, endPoint.y);
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
    releasePointer(event);
    draw();
  });

  canvas.addEventListener("pointercancel", event => {
    drawing = false;
    resizing = null;
    start = null;
    pointer = null;
    releasePointer(event);
    canvas.style.cursor = "crosshair";
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
    zones.forEach(normalizeZone);
    zonesInput.value = JSON.stringify(zones);
  });

  image.addEventListener("load", resizeCanvas);
  window.addEventListener("resize", resizeCanvas);
  buildTypeButtons();
  resizeCanvas();
})();
