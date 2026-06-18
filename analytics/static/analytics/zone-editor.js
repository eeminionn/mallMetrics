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

  let zones = Array.isArray(initialZones) ? initialZones.map(normalizeClientZone) : [];
  let currentType = "puerta";
  let drawing = false;
  let draggingPoint = null;
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

  function clampOriginalPoint(point) {
    return {
      x: Math.round(Math.max(0, Math.min(frameWidth - 1, Number(point.x) || 0))),
      y: Math.round(Math.max(0, Math.min(frameHeight - 1, Number(point.y) || 0)))
    };
  }

  function rectanglePoints(x1, y1, x2, y2) {
    const left = Math.min(x1, x2);
    const right = Math.max(x1, x2);
    const top = Math.min(y1, y2);
    const bottom = Math.max(y1, y2);
    return [
      { x: left, y: top },
      { x: right, y: top },
      { x: right, y: bottom },
      { x: left, y: bottom }
    ];
  }

  function zonePoints(zone) {
    if (Array.isArray(zone.points) && zone.points.length >= 4) {
      return zone.points.slice(0, 4).map(clampOriginalPoint);
    }
    return rectanglePoints(zone.x1 || 0, zone.y1 || 0, zone.x2 || 0, zone.y2 || 0);
  }

  function updateBounds(zone) {
    zone.points = zonePoints(zone);
    const xs = zone.points.map(point => point.x);
    const ys = zone.points.map(point => point.y);
    zone.x1 = Math.min(...xs);
    zone.y1 = Math.min(...ys);
    zone.x2 = Math.max(...xs);
    zone.y2 = Math.max(...ys);
    return zone;
  }

  function normalizeClientZone(zone) {
    return updateBounds({ ...zone, points: zonePoints(zone) });
  }

  function polygonArea(points) {
    let area = 0;
    points.forEach((point, index) => {
      const next = points[(index + 1) % points.length];
      area += point.x * next.y - next.x * point.y;
    });
    return Math.abs(area) / 2;
  }

  function isValidZone(zone) {
    updateBounds(zone);
    return (zone.x2 - zone.x1) >= 10 && (zone.y2 - zone.y1) >= 10 && polygonArea(zone.points) >= 80;
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

  function originalToCanvas(point) {
    return {
      x: metrics.offsetX + point.x * metrics.scale,
      y: metrics.offsetY + point.y * metrics.scale
    };
  }

  function canvasToOriginal(x, y) {
    return clampOriginalPoint({
      x: (x - metrics.offsetX) / metrics.scale,
      y: (y - metrics.offsetY) / metrics.scale
    });
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

  function canvasPoints(zone) {
    return zonePoints(zone).map(originalToCanvas);
  }

  function zoneCanvasBounds(points) {
    const xs = points.map(point => point.x);
    const ys = points.map(point => point.y);
    return {
      x: Math.min(...xs),
      y: Math.min(...ys),
      w: Math.max(...xs) - Math.min(...xs),
      h: Math.max(...ys) - Math.min(...ys)
    };
  }

  function drawPath(points) {
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) {
        ctx.moveTo(point.x, point.y);
      } else {
        ctx.lineTo(point.x, point.y);
      }
    });
    ctx.closePath();
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
    const points = canvasPoints(zone);
    const bounds = zoneCanvasBounds(points);
    ctx.save();
    ctx.strokeStyle = style.hex;
    ctx.fillStyle = `${style.hex}22`;
    ctx.lineWidth = isDraft ? 2 : 3;
    if (isDraft) ctx.setLineDash([8, 6]);
    drawPath(points);
    ctx.fill();
    ctx.stroke();

    if (!isDraft) {
      const label = zone.name || zone.id;
      ctx.setLineDash([]);
      const labelW = Math.min(Math.max(label.length * 8 + 48, 150), 310);
      const labelY = Math.max(metrics.offsetY + 8, bounds.y - 32);
      const labelX = Math.min(bounds.x, metrics.offsetX + metrics.displayW - labelW - 4);
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
      points.forEach(point => drawHandle(point, style.hex));
    }
    ctx.restore();
  }

  function draw() {
    labelHitAreas = [];
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#05070d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (image.complete) {
      ctx.drawImage(image, metrics.offsetX, metrics.offsetY, metrics.displayW, metrics.displayH);
    }
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 2;
    ctx.strokeRect(metrics.offsetX, metrics.offsetY, metrics.displayW, metrics.displayH);
    zones.forEach((zone, index) => drawZone(zone, index, false));
    if (drawing && start && pointer) {
      const a = canvasToOriginal(start.x, start.y);
      const b = canvasToOriginal(pointer.x, pointer.y);
      drawZone({
        type: currentType,
        name: "Nueva zona",
        points: rectanglePoints(a.x, a.y, b.x, b.y)
      }, -1, true);
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

  function findPointHit(point) {
    for (let index = zones.length - 1; index >= 0; index -= 1) {
      const points = canvasPoints(zones[index]);
      for (let pointIndex = 0; pointIndex < points.length; pointIndex += 1) {
        const handle = points[pointIndex];
        const distance = Math.hypot(point.x - handle.x, point.y - handle.y);
        if (distance <= 11) {
          return { index, pointIndex };
        }
      }
    }
    return null;
  }

  function applyPointDrag(point) {
    if (!draggingPoint) return;
    const zone = zones[draggingPoint.index];
    zone.points[draggingPoint.pointIndex] = canvasToOriginal(point.x, point.y);
    updateBounds(zone);
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

    const pointHit = findPointHit(point);
    if (pointHit) {
      draggingPoint = pointHit;
      canvas.setPointerCapture(event.pointerId);
      canvas.style.cursor = "grabbing";
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

    if (draggingPoint) {
      applyPointDrag(clampCanvas(point.x, point.y));
      draw();
      return;
    }

    if (drawing) {
      pointer = clampCanvas(point.x, point.y);
      draw();
      return;
    }

    const editHit = findEditHit(point);
    const pointHit = findPointHit(point);
    if (editHit) {
      canvas.style.cursor = "pointer";
    } else if (pointHit) {
      canvas.style.cursor = "grab";
    } else {
      canvas.style.cursor = insideImage(point.x, point.y) ? "crosshair" : "default";
    }
  });

  canvas.addEventListener("pointerup", event => {
    if (draggingPoint) {
      updateBounds(zones[draggingPoint.index]);
      draggingPoint = null;
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
    const zone = updateBounds({
      id: nextZoneId(currentType),
      name: zoneName.value.trim() || defaultName(currentType),
      type: currentType,
      points: rectanglePoints(a.x, a.y, b.x, b.y)
    });
    if (isValidZone(zone)) {
      zones.push(zone);
      zoneName.value = "";
    }
    start = null;
    pointer = null;
    releasePointer(event);
    draw();
  });

  canvas.addEventListener("pointercancel", event => {
    drawing = false;
    draggingPoint = null;
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
    zones = zones.filter(isValidZone).map(updateBounds);
    zonesInput.value = JSON.stringify(zones);
  });

  image.addEventListener("load", resizeCanvas);
  window.addEventListener("resize", resizeCanvas);
  buildTypeButtons();
  resizeCanvas();
})();
