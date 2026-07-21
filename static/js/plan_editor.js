/**
 * Plan Editor — Interactive PDF annotation tool.
 * Allows drawing, selecting, moving, resizing, and deleting rectangle annotations
 * on PDF page images. Annotations are persisted via REST API.
 */

// Editor state
const state = {
    mode: 'select',          // 'draw' | 'select'
    annotations: [],         // Array of annotation objects
    selectedId: null,        // Currently selected annotation ID
    currentPage: 1,
    totalPages: 1,
    attachmentId: null,
    canvas: null,
    ctx: null,
    imageElement: null,
    isDragging: false,
    dragStart: null,         // {x, y} in canvas pixels
    dragAction: null,        // 'draw' | 'move' | 'resize'
    zoom: 100,              // Zoom percentage (25-300)
    isPanning: false,       // True when middle-click or space+drag panning
    panStart: null,         // {x, y, scrollLeft, scrollTop} for panning
    resizeHandle: null,      // 'nw' | 'ne' | 'sw' | 'se'
    dragAnnotation: null,    // annotation being moved/resized
    originalAnnotation: null, // snapshot for rollback
    groups: [],              // Array of group objects from API
    activeGroupId: null,     // Group ID for new annotations (selected in panel)
    hiddenGroupIds: new Set(), // Groups toggled invisible (client-side)
    exclusionZones: [],      // Array of {id, x, y, width, height} for current page
    selectedExclusionZoneId: null, // Currently selected exclusion zone ID
};

// --- Coordinate helpers ---

function toRatio(px, dimension) {
    return px / dimension;
}

function fromRatio(ratio, dimension) {
    return ratio * dimension;
}

// --- Constrain helper ---

function constrain(ann) {
    // Keep annotation fully within [0, 1] bounds
    if (ann.x < 0) ann.x = 0;
    if (ann.y < 0) ann.y = 0;
    if (ann.x + ann.width > 1.0) ann.x = 1.0 - ann.width;
    if (ann.y + ann.height > 1.0) ann.y = 1.0 - ann.height;
    // Ensure non-negative after adjustment
    if (ann.x < 0) { ann.width += ann.x; ann.x = 0; }
    if (ann.y < 0) { ann.height += ann.y; ann.y = 0; }
    if (ann.width > 1.0) ann.width = 1.0;
    if (ann.height > 1.0) ann.height = 1.0;
    return ann;
}

// --- Initialization ---

function init(attachmentId) {
    state.attachmentId = attachmentId;
    state.canvas = document.getElementById('annotation-canvas');
    state.ctx = state.canvas.getContext('2d');
    state.imageElement = document.getElementById('page-image');

    // Attach mouse events to canvas
    state.canvas.addEventListener('mousedown', handleMouseDown);
    state.canvas.addEventListener('mousemove', handleMouseMove);
    state.canvas.addEventListener('mouseup', handleMouseUp);

    // Scroll wheel zoom
    state.canvas.addEventListener('wheel', handleWheel, { passive: false });

    // Middle mouse button panning
    const container = document.getElementById('editor-container');
    container.addEventListener('mousedown', handlePanStart);
    container.addEventListener('mousemove', handlePanMove);
    container.addEventListener('mouseup', handlePanEnd);
    container.addEventListener('mouseleave', handlePanEnd);

    // Space key for temporary pan mode
    document.addEventListener('keydown', function (e) {
        if (e.code === 'Space' && !e.repeat && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            e.preventDefault();
            state._spaceHeld = true;
            container.style.cursor = 'grab';
        }
    });
    document.addEventListener('keyup', function (e) {
        if (e.code === 'Space') {
            state._spaceHeld = false;
            container.style.cursor = '';
        }
    });

    // Key events
    document.addEventListener('keydown', handleKeyDown);

    // Resize canvas when image loads
    state.imageElement.addEventListener('load', function () {
        resizeCanvas();
        render();
    });

    // Handle window resize
    window.addEventListener('resize', function () {
        resizeCanvas();
        render();
    });

    // Wire up "Ny grupp" button
    const createGroupBtn = document.getElementById('btn-create-group');
    if (createGroupBtn) {
        createGroupBtn.addEventListener('click', showCreateGroupInput);
    }

    // Load visibility state from sessionStorage before rendering groups
    loadVisibilityState();

    // Load first page
    loadPage(1);

    // Fetch groups for this attachment
    fetchGroups(attachmentId);
}

function resizeCanvas() {
    const img = state.imageElement;
    // Match canvas pixel size to displayed image size
    state.canvas.width = img.clientWidth;
    state.canvas.height = img.clientHeight;
    state.canvas.style.width = img.clientWidth + 'px';
    state.canvas.style.height = img.clientHeight + 'px';
}

// --- Page loading ---

async function loadPage(pageNumber) {
    state.currentPage = pageNumber;
    state.selectedId = null;

    // Show loading indicator
    const loader = document.getElementById('loading-indicator');
    if (loader) loader.style.display = 'flex';

    const url = `/data/api/page-image/${state.attachmentId}/${pageNumber}`;

    try {
        const response = await fetch(url);
        if (!response.ok) {
            if (loader) loader.style.display = 'none';
            showError('Kunde inte ladda sidan.');
            return;
        }

        // Read total pages from header
        const pageCount = response.headers.get('X-Page-Count');
        if (pageCount) {
            state.totalPages = parseInt(pageCount, 10);
        }

        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);

        // Hide loader when image finishes rendering
        state.imageElement.onload = function () {
            if (loader) loader.style.display = 'none';
            // Apply current zoom level to the new page
            setZoom(state.zoom);
        };
        state.imageElement.src = objectUrl;

        // Update page nav UI
        updatePageNav();

        // Fetch annotations for this page
        await fetchAnnotations(state.attachmentId, pageNumber);

        // Fetch exclusion zones for this page
        await fetchExclusionZones(state.attachmentId, pageNumber);
    } catch (err) {
        const loader = document.getElementById('loading-indicator');
        if (loader) loader.style.display = 'none';
        showError('Kunde inte ladda sidan.');
    }
}

function updatePageNav() {
    document.getElementById('page-indicator').textContent =
        `Sida ${state.currentPage} / ${state.totalPages}`;
    document.getElementById('btn-prev').disabled = (state.currentPage <= 1);
    document.getElementById('btn-next').disabled = (state.currentPage >= state.totalPages);
}

// --- Rendering ---

function render() {
    const ctx = state.ctx;
    const w = state.canvas.width;
    const h = state.canvas.height;

    ctx.clearRect(0, 0, w, h);

    for (const ann of state.annotations) {
        // Skip annotations belonging to hidden groups
        if (ann.group_id !== null && ann.group_id !== undefined && state.hiddenGroupIds.has(ann.group_id)) {
            continue;
        }

        const px = fromRatio(ann.x, w);
        const py = fromRatio(ann.y, h);
        const pw = fromRatio(ann.width, w);
        const ph = fromRatio(ann.height, h);

        const isSelected = (ann.id === state.selectedId);

        // Determine color from group or use default
        const color = ann.group_color || '#3498db';

        // Parse hex color to RGB for alpha fill
        const r = parseInt(color.slice(1, 3), 16);
        const g = parseInt(color.slice(3, 5), 16);
        const b = parseInt(color.slice(5, 7), 16);

        // Fill with semi-transparent group color
        const fillAlpha = isSelected ? 0.25 : 0.15;
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${fillAlpha})`;
        ctx.fillRect(px, py, pw, ph);

        // Border with full opacity group color
        ctx.strokeStyle = color;
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.strokeRect(px, py, pw, ph);

        // Resize handles for selected
        if (isSelected) {
            const handleSize = 8;
            const hs = handleSize / 2;
            ctx.fillStyle = color;
            // NW
            ctx.fillRect(px - hs, py - hs, handleSize, handleSize);
            // NE
            ctx.fillRect(px + pw - hs, py - hs, handleSize, handleSize);
            // SW
            ctx.fillRect(px - hs, py + ph - hs, handleSize, handleSize);
            // SE
            ctx.fillRect(px + pw - hs, py + ph - hs, handleSize, handleSize);
        }
    }

    // Render exclusion zones
    for (const zone of (state.exclusionZones || [])) {
        const zx = fromRatio(zone.x, w);
        const zy = fromRatio(zone.y, h);
        const zw = fromRatio(zone.width, w);
        const zh = fromRatio(zone.height, h);
        
        const isSelectedZone = (zone.id === state.selectedExclusionZoneId);
        
        ctx.fillStyle = isSelectedZone ? 'rgba(128, 128, 128, 0.35)' : 'rgba(128, 128, 128, 0.2)';
        ctx.fillRect(zx, zy, zw, zh);
        ctx.strokeStyle = isSelectedZone ? '#e74c3c' : '#666';
        ctx.lineWidth = isSelectedZone ? 2 : 1;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(zx, zy, zw, zh);
        ctx.setLineDash([]);
        
        // Draw X pattern
        ctx.beginPath();
        ctx.moveTo(zx, zy);
        ctx.lineTo(zx + zw, zy + zh);
        ctx.moveTo(zx + zw, zy);
        ctx.lineTo(zx, zy + zh);
        ctx.strokeStyle = isSelectedZone ? 'rgba(231, 76, 60, 0.5)' : 'rgba(128, 128, 128, 0.4)';
        ctx.stroke();
    }

    // Draw preview rectangle during draw action
    if (state.isDragging && state.dragAction === 'draw' && state.dragStart && state._drawCurrent) {
        const sx = state.dragStart.x;
        const sy = state.dragStart.y;
        const cx = state._drawCurrent.x;
        const cy = state._drawCurrent.y;
        const rx = Math.min(sx, cx);
        const ry = Math.min(sy, cy);
        const rw = Math.abs(cx - sx);
        const rh = Math.abs(cy - sy);
        ctx.fillStyle = 'rgba(46, 204, 113, 0.2)';
        ctx.fillRect(rx, ry, rw, rh);
        ctx.strokeStyle = '#27ae60';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 3]);
        ctx.strokeRect(rx, ry, rw, rh);
        ctx.setLineDash([]);
    }
}

// --- Mouse event handlers ---

function getCanvasPos(e) {
    const rect = state.canvas.getBoundingClientRect();
    return {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
    };
}

function handleMouseDown(e) {
    // Middle button always pans
    if (e.button === 1) return;

    // Pan mode: left click pans
    if (state.mode === 'pan' && e.button === 0) {
        e.preventDefault();
        const container = document.getElementById('editor-container');
        state.isPanning = true;
        state.panStart = {
            x: e.clientX,
            y: e.clientY,
            scrollLeft: container.scrollLeft,
            scrollTop: container.scrollTop,
        };
        container.style.cursor = 'grabbing';
        return;
    }

    // Skip if space held (already handled by pan start)
    if (state._spaceHeld) return;

    const pos = getCanvasPos(e);

    if (state.mode === 'draw') {
        state.isDragging = true;
        state.dragAction = 'draw';
        state.dragStart = pos;
        state._drawCurrent = pos;
        return;
    }

    if (state.mode === 'exclusion') {
        // Check if clicking on an existing exclusion zone first (to select for deletion)
        const zoneHit = hitTestExclusionZone(pos.x, pos.y);
        if (zoneHit) {
            state.selectedExclusionZoneId = zoneHit.id;
            state.selectedId = null;
            render();
            return;
        }
        // Otherwise start drawing a new exclusion zone
        state.selectedExclusionZoneId = null;
        state.isDragging = true;
        state.dragAction = 'draw';
        state.dragStart = pos;
        state._drawCurrent = pos;
        return;
    }

    // Select mode
    if (state.mode === 'select') {
        // Check if clicking on a resize handle of the selected annotation
        if (state.selectedId !== null) {
            const selected = state.annotations.find(a => a.id === state.selectedId);
            if (selected) {
                const handle = hitTestHandle(pos.x, pos.y, selected);
                if (handle) {
                    state.isDragging = true;
                    state.dragAction = 'resize';
                    state.resizeHandle = handle;
                    state.dragStart = pos;
                    state.dragAnnotation = selected;
                    state.originalAnnotation = { ...selected };
                    return;
                }
            }
        }

        // Check hit test for selection/move
        const hit = hitTest(pos.x, pos.y);
        if (hit) {
            state.selectedId = hit.id;
            state.selectedExclusionZoneId = null;
            render();
            renderGroupsPanel();

            // Start move
            state.isDragging = true;
            state.dragAction = 'move';
            state.dragStart = pos;
            state.dragAnnotation = hit;
            state.originalAnnotation = { ...hit };
        } else {
            // Check if clicking on an exclusion zone
            const zoneHit = hitTestExclusionZone(pos.x, pos.y);
            if (zoneHit) {
                state.selectedExclusionZoneId = zoneHit.id;
                state.selectedId = null;
                render();
                renderGroupsPanel();
            } else {
                // Deselect all
                state.selectedId = null;
                state.selectedExclusionZoneId = null;
                render();
                renderGroupsPanel();
            }
        }
    }
}

function handleMouseMove(e) {
    // If in pan mode and panning via left click, delegate to pan handler
    if (state.isPanning && state.mode === 'pan') {
        handlePanMove(e);
        return;
    }

    if (!state.isDragging) {
        // Update cursor based on context
        if (state.mode === 'draw' || state.mode === 'exclusion') {
            state.canvas.style.cursor = 'crosshair';
        } else if (state.mode === 'pan') {
            state.canvas.style.cursor = state.isPanning ? 'grabbing' : 'grab';
            return;
        } else if (state.mode === 'select') {
            const pos = getCanvasPos(e);
            if (state.selectedId !== null) {
                const selected = state.annotations.find(a => a.id === state.selectedId);
                if (selected && hitTestHandle(pos.x, pos.y, selected)) {
                    state.canvas.style.cursor = 'nwse-resize';
                    return;
                }
            }
            const hit = hitTest(pos.x, pos.y);
            state.canvas.style.cursor = hit ? 'move' : 'default';
        }
        return;
    }

    const pos = getCanvasPos(e);
    const w = state.canvas.width;
    const h = state.canvas.height;

    if (state.dragAction === 'draw') {
        state._drawCurrent = pos;
        render();
        return;
    }

    if (state.dragAction === 'move') {
        const dx = toRatio(pos.x - state.dragStart.x, w);
        const dy = toRatio(pos.y - state.dragStart.y, h);

        state.dragAnnotation.x = state.originalAnnotation.x + dx;
        state.dragAnnotation.y = state.originalAnnotation.y + dy;

        constrain(state.dragAnnotation);
        render();
        return;
    }

    if (state.dragAction === 'resize') {
        const ann = state.dragAnnotation;
        const orig = state.originalAnnotation;
        const dx = toRatio(pos.x - state.dragStart.x, w);
        const dy = toRatio(pos.y - state.dragStart.y, h);
        const minSize = 10 / Math.max(w, h); // minimum 10px in ratio

        if (state.resizeHandle === 'se') {
            ann.width = Math.max(minSize, orig.width + dx);
            ann.height = Math.max(minSize, orig.height + dy);
        } else if (state.resizeHandle === 'sw') {
            const newW = Math.max(minSize, orig.width - dx);
            ann.x = orig.x + orig.width - newW;
            ann.width = newW;
            ann.height = Math.max(minSize, orig.height + dy);
        } else if (state.resizeHandle === 'ne') {
            ann.width = Math.max(minSize, orig.width + dx);
            const newH = Math.max(minSize, orig.height - dy);
            ann.y = orig.y + orig.height - newH;
            ann.height = newH;
        } else if (state.resizeHandle === 'nw') {
            const newW = Math.max(minSize, orig.width - dx);
            const newH = Math.max(minSize, orig.height - dy);
            ann.x = orig.x + orig.width - newW;
            ann.y = orig.y + orig.height - newH;
            ann.width = newW;
            ann.height = newH;
        }

        constrain(ann);
        render();
        return;
    }
}

function handleMouseUp(e) {
    // End pan mode left-click pan
    if (state.isPanning && state.mode === 'pan') {
        handlePanEnd(e);
        return;
    }

    if (!state.isDragging) return;
    state.isDragging = false;

    const pos = getCanvasPos(e);
    const w = state.canvas.width;
    const h = state.canvas.height;

    if (state.dragAction === 'draw') {
        const sx = state.dragStart.x;
        const sy = state.dragStart.y;
        const ex = pos.x;
        const ey = pos.y;
        const rectW = Math.abs(ex - sx);
        const rectH = Math.abs(ey - sy);

        state._drawCurrent = null;

        // Only create if >= 5px in both dimensions
        if (rectW >= 5 && rectH >= 5) {
            const x = toRatio(Math.min(sx, ex), w);
            const y = toRatio(Math.min(sy, ey), h);
            const annW = toRatio(rectW, w);
            const annH = toRatio(rectH, h);

            const ann = constrain({ x, y, width: annW, height: annH });

            if (state.mode === 'exclusion') {
                createExclusionZone(ann);
            } else {
                createAnnotation(ann);
            }
        } else {
            render(); // Clear preview
        }
        return;
    }

    if (state.dragAction === 'move' || state.dragAction === 'resize') {
        const ann = state.dragAnnotation;
        if (ann) {
            updateAnnotation(ann.id, {
                x: ann.x,
                y: ann.y,
                width: ann.width,
                height: ann.height,
            });
        }
        state.dragAnnotation = null;
        state.originalAnnotation = null;
        return;
    }
}

// --- Hit testing ---

function hitTest(x, y) {
    const w = state.canvas.width;
    const h = state.canvas.height;

    // Search in reverse order (top-most first)
    for (let i = state.annotations.length - 1; i >= 0; i--) {
        const ann = state.annotations[i];

        // Skip annotations belonging to hidden groups
        if (ann.group_id !== null && ann.group_id !== undefined && state.hiddenGroupIds.has(ann.group_id)) {
            continue;
        }

        const px = fromRatio(ann.x, w);
        const py = fromRatio(ann.y, h);
        const pw = fromRatio(ann.width, w);
        const ph = fromRatio(ann.height, h);

        if (x >= px && x <= px + pw && y >= py && y <= py + ph) {
            return ann;
        }
    }
    return null;
}

function hitTestHandle(x, y, annotation) {
    const w = state.canvas.width;
    const h = state.canvas.height;
    const tolerance = 8;

    const px = fromRatio(annotation.x, w);
    const py = fromRatio(annotation.y, h);
    const pw = fromRatio(annotation.width, w);
    const ph = fromRatio(annotation.height, h);

    // Check corners
    const corners = {
        'nw': { cx: px, cy: py },
        'ne': { cx: px + pw, cy: py },
        'sw': { cx: px, cy: py + ph },
        'se': { cx: px + pw, cy: py + ph },
    };

    for (const [handle, { cx, cy }] of Object.entries(corners)) {
        if (Math.abs(x - cx) <= tolerance && Math.abs(y - cy) <= tolerance) {
            return handle;
        }
    }
    return null;
}

// --- Key handler ---

function handleKeyDown(e) {
    if (e.key === 'Delete' || e.key === 'Backspace') {
        // Don't delete if focus is on an input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        e.preventDefault();
        // Delete selected exclusion zone if one is selected
        if (state.selectedExclusionZoneId !== null) {
            deleteExclusionZone(state.selectedExclusionZoneId);
            return;
        }
        deleteSelected();
    }
}

// --- API communication ---

async function fetchAnnotations(attachmentId, page) {
    try {
        const response = await fetch(`/data/api/annotations/${attachmentId}/${page}`);
        if (response.ok) {
            state.annotations = await response.json();
            render();
            renderGroupsPanel();
        }
    } catch (err) {
        showError('Kunde inte hämta annoteringar.');
    }
}

async function createAnnotation(ann) {
    const body = {
        attachment_id: state.attachmentId,
        page_number: state.currentPage,
        x: ann.x,
        y: ann.y,
        width: ann.width,
        height: ann.height,
    };

    // Assign to active group if one is selected
    if (state.activeGroupId !== null) {
        body.group_id = state.activeGroupId;
    }

    try {
        const response = await fetch('/data/api/annotations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (response.ok) {
            const created = await response.json();
            state.annotations.push(created);
            state.selectedId = created.id;
            render();
            renderGroupsPanel();
        } else {
            showError('Ändringarna kunde inte sparas');
            render();
        }
    } catch (err) {
        showError('Ändringarna kunde inte sparas');
        render();
    }
}

async function updateAnnotation(id, data) {
    try {
        const response = await fetch(`/data/api/annotations/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            // Rollback
            if (state.originalAnnotation) {
                const ann = state.annotations.find(a => a.id === id);
                if (ann) {
                    Object.assign(ann, state.originalAnnotation);
                }
            }
            showError('Ändringarna kunde inte sparas');
            render();
        }
    } catch (err) {
        // Rollback
        if (state.originalAnnotation) {
            const ann = state.annotations.find(a => a.id === id);
            if (ann) {
                Object.assign(ann, state.originalAnnotation);
            }
        }
        showError('Ändringarna kunde inte sparas');
        render();
    }
}

async function deleteAnnotation(id) {
    try {
        const response = await fetch(`/data/api/annotations/${id}`, {
            method: 'DELETE',
        });
        if (response.ok) {
            state.annotations = state.annotations.filter(a => a.id !== id);
            state.selectedId = null;
            render();
        } else {
            showError('Ändringarna kunde inte sparas');
        }
    } catch (err) {
        showError('Ändringarna kunde inte sparas');
    }
}

// --- Group API communication ---

async function fetchGroups(attachmentId) {
    try {
        const response = await fetch(`/data/api/groups/${attachmentId}`);
        if (response.ok) {
            state.groups = await response.json();
            renderGroupsPanel();
        }
    } catch (err) {
        showError('Kunde inte hämta grupper.');
    }
}

async function createGroup(name) {
    const body = {
        attachment_id: state.attachmentId,
        name: name,
    };

    try {
        const response = await fetch('/data/api/groups', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (response.ok || response.status === 201) {
            const created = await response.json();
            state.groups.push(created);
            renderGroupsPanel();
        } else {
            const err = await response.json().catch(() => null);
            showError(err?.error || 'Kunde inte skapa grupp.');
        }
    } catch (err) {
        showError('Kunde inte skapa grupp.');
    }
}

async function updateGroup(groupId, data) {
    try {
        const response = await fetch(`/data/api/groups/${groupId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (response.ok) {
            const updated = await response.json();
            const idx = state.groups.findIndex(g => g.id === groupId);
            if (idx !== -1) {
                state.groups[idx] = updated;
            }
            // Update local annotation colors if group color changed
            if (data.color) {
                for (const ann of state.annotations) {
                    if (ann.group_id === groupId) {
                        ann.group_color = updated.color;
                    }
                }
            }
            renderGroupsPanel();
            render();
        } else {
            const err = await response.json().catch(() => null);
            showError(err?.error || 'Kunde inte spara ändringarna.');
        }
    } catch (err) {
        showError('Kunde inte spara ändringarna.');
    }
}

async function deleteGroup(groupId) {
    if (!confirm('Radera grupp? Annoteringarna behålls men blir otilldelade.')) {
        return;
    }

    try {
        const response = await fetch(`/data/api/groups/${groupId}`, {
            method: 'DELETE',
        });
        if (response.ok) {
            state.groups = state.groups.filter(g => g.id !== groupId);
            if (state.activeGroupId === groupId) {
                state.activeGroupId = null;
            }
            // Re-fetch annotations to get updated group_id=null
            await fetchAnnotations(state.attachmentId, state.currentPage);
            renderGroupsPanel();
        } else {
            const err = await response.json().catch(() => null);
            showError(err?.error || 'Kunde inte radera grupp.');
        }
    } catch (err) {
        showError('Kunde inte radera grupp.');
    }
}

async function assignAnnotationToGroup(annotationId, groupId) {
    try {
        const response = await fetch(`/data/api/annotations/${annotationId}/group`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_id: groupId }),
        });
        if (response.ok) {
            const updated = await response.json();
            const ann = state.annotations.find(a => a.id === annotationId);
            if (ann) {
                ann.group_id = updated.group_id;
                ann.group_color = updated.group_color;
            }
            render();
            renderGroupsPanel();
        } else {
            const err = await response.json().catch(() => null);
            showError(err?.error || 'Kunde inte tilldela grupp.');
        }
    } catch (err) {
        showError('Kunde inte tilldela grupp.');
    }
}

async function clearUnassignedAnnotations() {
    const count = state.annotations.filter(a => a.group_id === null || a.group_id === undefined).length;
    if (count === 0) return;

    if (!confirm(`Radera ${count} otilldelade annotering(ar)?`)) {
        return;
    }

    try {
        const response = await fetch(`/data/api/annotations/${state.attachmentId}/unassigned`, {
            method: 'DELETE',
        });
        if (response.ok) {
            state.annotations = state.annotations.filter(a => a.group_id !== null && a.group_id !== undefined);
            state.selectedId = null;
            render();
            renderGroupsPanel();
        } else {
            showError('Kunde inte radera annoteringar.');
        }
    } catch (err) {
        showError('Kunde inte radera annoteringar.');
    }
}

// --- Exclusion Zone API ---

async function fetchExclusionZones(attachmentId, pageNumber) {
    try {
        const response = await fetch(`/data/api/exclusion-zones/${attachmentId}/${pageNumber}`);
        if (response.ok) {
            state.exclusionZones = await response.json();
            render();
        }
    } catch (err) { /* silently ignore */ }
}

async function createExclusionZone(zone) {
    const body = {
        attachment_id: state.attachmentId,
        page_number: state.currentPage,
        ...zone,
    };
    try {
        const response = await fetch('/data/api/exclusion-zones', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (response.ok) {
            const created = await response.json();
            state.exclusionZones.push(created);
            render();
        }
    } catch (err) { showError('Kunde inte skapa exkluderingszon.'); }
}

async function deleteExclusionZone(zoneId) {
    try {
        const response = await fetch(`/data/api/exclusion-zones/${zoneId}`, {
            method: 'DELETE',
        });
        if (response.ok) {
            state.exclusionZones = state.exclusionZones.filter(z => z.id !== zoneId);
            state.selectedExclusionZoneId = null;
            render();
        }
    } catch (err) { showError('Kunde inte ta bort exkluderingszon.'); }
}

function hitTestExclusionZone(x, y) {
    const w = state.canvas.width;
    const h = state.canvas.height;
    for (let i = state.exclusionZones.length - 1; i >= 0; i--) {
        const zone = state.exclusionZones[i];
        const zx = fromRatio(zone.x, w);
        const zy = fromRatio(zone.y, h);
        const zw = fromRatio(zone.width, w);
        const zh = fromRatio(zone.height, h);
        if (x >= zx && x <= zx + zw && y >= zy && y <= zy + zh) {
            return zone;
        }
    }
    return null;
}

// --- Group Merge ---

async function mergeGroups(sourceId, targetId) {
    if (!confirm('Slå ihop grupper? Annoteringarna flyttas till målgruppen.')) return;
    try {
        const response = await fetch('/data/api/groups/merge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_group_id: sourceId, target_group_id: targetId }),
        });
        if (response.ok) {
            await fetchGroups(state.attachmentId);
            await fetchAnnotations(state.attachmentId, state.currentPage);
            renderGroupsPanel();
        } else {
            showError('Kunde inte slå ihop grupper.');
        }
    } catch (err) { showError('Kunde inte slå ihop grupper.'); }
}

function showMergeTargets(sourceGroupId, anchorElement) {
    // Remove any existing merge dropdown
    const existing = document.querySelector('.merge-dropdown');
    if (existing) existing.remove();

    const otherGroups = state.groups.filter(g => g.id !== sourceGroupId);
    if (otherGroups.length === 0) {
        showError('Ingen annan grupp att slå ihop med.');
        return;
    }

    const dropdown = document.createElement('div');
    dropdown.className = 'merge-dropdown dropdown-menu';
    dropdown.style.display = 'block';
    dropdown.style.position = 'absolute';
    dropdown.style.zIndex = '1000';

    for (const target of otherGroups) {
        const link = document.createElement('a');
        link.href = '#';
        link.textContent = target.name;
        link.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropdown.remove();
            mergeGroups(sourceGroupId, target.id);
        });
        dropdown.appendChild(link);
    }

    // Position relative to anchor
    const item = anchorElement.closest('.group-item');
    if (item) {
        item.style.position = 'relative';
        item.appendChild(dropdown);
        dropdown.style.top = '100%';
        dropdown.style.right = '0';
        dropdown.style.left = 'auto';
    }

    // Close on outside click
    setTimeout(() => {
        document.addEventListener('click', function closeMerge(e) {
            if (!dropdown.contains(e.target)) {
                dropdown.remove();
                document.removeEventListener('click', closeMerge);
            }
        });
    }, 0);
}

// --- Groups panel rendering ---

function renderGroupsPanel() {
    const container = document.getElementById('groups-list');
    if (!container) return;

    container.innerHTML = '';

    if (state.groups.length === 0) {
        container.innerHTML = '<p class="groups-empty-state">Skapa en grupp för att organisera annoteringarna.</p>';
        // Still show clear unassigned button even with no groups
        const unassignedCount = state.annotations.filter(a => a.group_id === null || a.group_id === undefined).length;
        if (unassignedCount > 0) {
            const clearBtn = document.createElement('button');
            clearBtn.className = 'btn btn-sm btn-clear-unassigned';
            clearBtn.textContent = `Rensa otilldelade (${unassignedCount})`;
            clearBtn.title = 'Ta bort alla annoteringar utan grupp';
            clearBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                clearUnassignedAnnotations();
            });
            container.appendChild(clearBtn);
        }
        return;
    }

    for (const group of state.groups) {
        const item = document.createElement('div');
        item.className = 'group-item';
        item.dataset.groupId = group.id;

        if (state.activeGroupId === group.id) {
            item.classList.add('active');
        }
        if (state.hiddenGroupIds.has(group.id)) {
            item.classList.add('hidden');
        }

        // Visibility toggle
        const visBtn = document.createElement('button');
        visBtn.className = 'group-visibility-toggle';
        visBtn.title = state.hiddenGroupIds.has(group.id) ? 'Visa' : 'Dölj';
        visBtn.innerHTML = state.hiddenGroupIds.has(group.id)
            ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'
            : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
        visBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            toggleGroupVisibility(group.id);
        });

        // Color indicator
        const colorIndicator = document.createElement('span');
        colorIndicator.className = 'group-color-indicator';
        colorIndicator.style.background = group.color;
        colorIndicator.addEventListener('click', function (e) {
            e.stopPropagation();
            showColorPicker(group.id, colorIndicator);
        });

        // Group name
        const nameSpan = document.createElement('span');
        nameSpan.className = 'group-name';
        nameSpan.textContent = group.name;
        nameSpan.addEventListener('dblclick', function (e) {
            e.stopPropagation();
            startGroupRename(group.id);
        });

        // Annotation count badge (computed from local state for real-time updates)
        const countBadge = document.createElement('span');
        countBadge.className = 'group-count';
        const localCount = state.annotations.filter(a => a.group_id === group.id).length;
        countBadge.textContent = localCount;

        // Quantity override input
        const quantityInput = document.createElement('input');
        quantityInput.type = 'number';
        quantityInput.className = 'group-quantity-input';
        const overrideValue = group.quantity_override !== null && group.quantity_override !== undefined
            ? group.quantity_override : localCount;
        quantityInput.value = overrideValue;
        if (group.quantity_override !== null && group.quantity_override !== undefined) {
            quantityInput.classList.add('overridden');
        }
        quantityInput.title = 'Antal (överstyr vid ändring)';
        quantityInput.min = '0';
        quantityInput.addEventListener('click', function (e) { e.stopPropagation(); });
        quantityInput.addEventListener('change', function (e) {
            e.stopPropagation();
            const val = quantityInput.value.trim();
            const override = val === '' || parseInt(val, 10) === localCount ? null : parseInt(val, 10);
            updateGroup(group.id, { quantity_override: override });
        });

        // Merge button
        const mergeBtn = document.createElement('button');
        mergeBtn.className = 'group-merge-btn';
        mergeBtn.title = 'Slå ihop med annan grupp';
        mergeBtn.textContent = '⊕';
        mergeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            showMergeTargets(group.id, mergeBtn);
        });

        // Delete button
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'group-delete-btn';
        deleteBtn.title = 'Ta bort';
        deleteBtn.textContent = '✕';
        deleteBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            deleteGroup(group.id);
        });

        item.appendChild(visBtn);
        item.appendChild(colorIndicator);
        item.appendChild(nameSpan);
        item.appendChild(countBadge);
        item.appendChild(quantityInput);
        item.appendChild(mergeBtn);
        item.appendChild(deleteBtn);

        // Assign button when annotation is selected
        if (state.selectedId !== null) {
            const assignBtn = document.createElement('button');
            assignBtn.className = 'group-assign-btn';
            assignBtn.title = 'Tilldela markerad annotering';
            assignBtn.textContent = '←';
            assignBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                assignAnnotationToGroup(state.selectedId, group.id);
            });
            item.appendChild(assignBtn);
        }

        // Clicking on the group item body sets active group
        item.addEventListener('click', function () {
            setActiveGroup(group.id);
        });

        container.appendChild(item);
    }

    // "Clear unassigned" button at the bottom
    const unassignedCount = state.annotations.filter(a => a.group_id === null || a.group_id === undefined).length;
    if (unassignedCount > 0) {
        const clearBtn = document.createElement('button');
        clearBtn.className = 'btn btn-sm btn-clear-unassigned';
        clearBtn.textContent = `Rensa otilldelade (${unassignedCount})`;
        clearBtn.title = 'Ta bort alla annoteringar utan grupp';
        clearBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            clearUnassignedAnnotations();
        });
        container.appendChild(clearBtn);
    }
}

// --- Active group selection ---

function setActiveGroup(groupId) {
    if (state.activeGroupId === groupId) {
        state.activeGroupId = null;
    } else {
        state.activeGroupId = groupId;
    }
    renderGroupsPanel();
}

// --- Inline group rename ---

function startGroupRename(groupId) {
    const group = state.groups.find(g => g.id === groupId);
    if (!group) return;

    const item = document.querySelector(`.group-item[data-group-id="${groupId}"]`);
    if (!item) return;

    const nameSpan = item.querySelector('.group-name');
    if (!nameSpan) return;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'group-rename-input';
    input.value = group.name;
    let saved = false;

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (!saved) {
                saved = true;
                saveGroupRename(groupId, input.value);
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            saved = true;
            cancelGroupRename(groupId);
        }
    });

    input.addEventListener('blur', function () {
        if (!saved) {
            saved = true;
            saveGroupRename(groupId, input.value);
        }
    });

    nameSpan.replaceWith(input);
    input.focus();
    input.select();
}

function saveGroupRename(groupId, newName) {
    const group = state.groups.find(g => g.id === groupId);
    if (!group) {
        renderGroupsPanel();
        return;
    }

    const trimmed = newName.trim();
    if (trimmed === '' || trimmed === group.name) {
        renderGroupsPanel();
        return;
    }

    // Check for duplicate name locally
    const duplicate = state.groups.find(g => g.id !== groupId && g.name === trimmed);
    if (duplicate) {
        showError('En grupp med det namnet finns redan.');
        renderGroupsPanel();
        return;
    }

    updateGroup(groupId, { name: trimmed });
}

function cancelGroupRename(groupId) {
    renderGroupsPanel();
}

// --- Create group inline input ---

function showCreateGroupInput() {
    const container = document.getElementById('groups-list');
    if (!container) return;

    // Remove any existing create input
    const existing = container.querySelector('.group-create-input');
    if (existing) existing.remove();

    const inputWrapper = document.createElement('div');
    inputWrapper.className = 'group-create-input';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'group-rename-input';
    input.placeholder = 'Gruppnamn...';
    let submitted = false;

    function submitInput() {
        if (submitted) return;
        submitted = true;
        const name = input.value.trim();
        if (name) {
            createGroup(name);
        }
        inputWrapper.remove();
    }

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            submitInput();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            submitted = true;
            inputWrapper.remove();
        }
    });

    input.addEventListener('blur', function () {
        submitInput();
    });

    inputWrapper.appendChild(input);
    container.insertBefore(inputWrapper, container.firstChild);
    input.focus();
}

// --- Visibility toggle ---

function toggleGroupVisibility(groupId) {
    if (state.hiddenGroupIds.has(groupId)) {
        state.hiddenGroupIds.delete(groupId);
    } else {
        state.hiddenGroupIds.add(groupId);
    }
    saveVisibilityState();
    render();
    renderGroupsPanel();
}

function saveVisibilityState() {
    sessionStorage.setItem(
        `groups-visibility-${state.attachmentId}`,
        JSON.stringify([...state.hiddenGroupIds])
    );
}

function loadVisibilityState() {
    const saved = sessionStorage.getItem(`groups-visibility-${state.attachmentId}`);
    if (saved) {
        try {
            state.hiddenGroupIds = new Set(JSON.parse(saved));
        } catch (e) {
            state.hiddenGroupIds = new Set();
        }
    }
}

// --- Color picker component ---

function closeColorPicker() {
    const existing = document.querySelector('.color-picker-popover');
    if (existing) existing.remove();
    // Remove the document-level listeners
    document.removeEventListener('click', closeColorPickerOnOutsideClick, true);
    document.removeEventListener('keydown', closeColorPickerOnEscape, true);
}

function closeColorPickerOnOutsideClick(e) {
    const picker = document.querySelector('.color-picker-popover');
    if (picker && !picker.contains(e.target)) {
        closeColorPicker();
    }
}

function closeColorPickerOnEscape(e) {
    if (e.key === 'Escape') {
        closeColorPicker();
    }
}

function showColorPicker(groupId, anchorElement) {
    // Close any existing picker first (only one at a time)
    closeColorPicker();

    const predefinedColors = [
        '#e74c3c', '#27ae60', '#2980b9', '#f39c12',
        '#9b59b6', '#1abc9c', '#e67e22', '#34495e',
    ];

    // Create popover container
    const popover = document.createElement('div');
    popover.className = 'color-picker-popover';

    // Swatches grid
    const swatchGrid = document.createElement('div');
    swatchGrid.className = 'color-picker-swatches';

    for (const color of predefinedColors) {
        const swatch = document.createElement('button');
        swatch.className = 'color-picker-swatch';
        swatch.style.background = color;
        swatch.title = color;
        swatch.addEventListener('click', function (e) {
            e.stopPropagation();
            updateGroup(groupId, { color: color });
            closeColorPicker();
        });
        swatchGrid.appendChild(swatch);
    }

    popover.appendChild(swatchGrid);

    // Custom hex input
    const hexWrapper = document.createElement('div');
    hexWrapper.className = 'color-picker-hex-wrapper';

    const hexInput = document.createElement('input');
    hexInput.type = 'text';
    hexInput.className = 'color-picker-hex-input';
    hexInput.placeholder = '#RRGGBB';
    hexInput.maxLength = 7;

    const hexHint = document.createElement('span');
    hexHint.className = 'color-picker-hex-hint';
    hexHint.textContent = '';

    hexInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            e.stopPropagation();
            const value = hexInput.value.trim();
            if (/^#[0-9A-Fa-f]{6}$/.test(value)) {
                updateGroup(groupId, { color: value.toLowerCase() });
                closeColorPicker();
            } else {
                hexHint.textContent = 'Ogiltigt format. Använd #RRGGBB';
                hexHint.classList.add('visible');
                setTimeout(() => {
                    hexHint.textContent = '';
                    hexHint.classList.remove('visible');
                }, 3000);
            }
        } else if (e.key === 'Escape') {
            e.stopPropagation();
            closeColorPicker();
        }
    });

    // Prevent click-outside handler from closing picker when clicking inside hex input
    hexInput.addEventListener('click', function (e) {
        e.stopPropagation();
    });

    hexWrapper.appendChild(hexInput);
    hexWrapper.appendChild(hexHint);
    popover.appendChild(hexWrapper);

    // Position the popover near/below the anchor element
    document.body.appendChild(popover);

    const anchorRect = anchorElement.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();

    let top = anchorRect.bottom + 4;
    let left = anchorRect.left;

    // Ensure popover doesn't overflow right side of viewport
    if (left + popoverRect.width > window.innerWidth) {
        left = window.innerWidth - popoverRect.width - 8;
    }
    // Ensure popover doesn't overflow bottom of viewport
    if (top + popoverRect.height > window.innerHeight) {
        top = anchorRect.top - popoverRect.height - 4;
    }

    popover.style.top = top + 'px';
    popover.style.left = left + 'px';

    // Add outside-click and escape listeners (delay to avoid immediate close from current click)
    setTimeout(() => {
        document.addEventListener('click', closeColorPickerOnOutsideClick, true);
        document.addEventListener('keydown', closeColorPickerOnEscape, true);
    }, 0);
}

// --- Mode switching ---

function setMode(mode) {
    state.mode = mode;
    state.selectedId = null;

    // Update toolbar button styles
    document.getElementById('btn-draw').classList.toggle('active', mode === 'draw');
    document.getElementById('btn-select').classList.toggle('active', mode === 'select');
    document.getElementById('btn-pan').classList.toggle('active', mode === 'pan');
    const exclusionBtn = document.getElementById('btn-exclusion');
    if (exclusionBtn) exclusionBtn.classList.toggle('active', mode === 'exclusion');

    // Update cursor
    if (mode === 'draw' || mode === 'exclusion') {
        state.canvas.style.cursor = 'crosshair';
    } else if (mode === 'pan') {
        state.canvas.style.cursor = 'grab';
    } else {
        state.canvas.style.cursor = 'default';
    }

    render();
}

// --- Page navigation ---

function prevPage() {
    if (state.currentPage > 1) {
        loadPage(state.currentPage - 1);
    }
}

function nextPage() {
    if (state.currentPage < state.totalPages) {
        loadPage(state.currentPage + 1);
    }
}

// --- Delete selected ---

function deleteSelected() {
    if (state.selectedExclusionZoneId !== null) {
        deleteExclusionZone(state.selectedExclusionZoneId);
        return;
    }
    if (state.selectedId !== null) {
        deleteAnnotation(state.selectedId);
    }
}

// --- Error handling ---

function showError(msg) {
    // Remove existing toast
    const existing = document.querySelector('.error-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'error-toast';
    toast.textContent = msg;
    document.body.appendChild(toast);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.add('error-toast-fade');
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

// --- Pan (drag to scroll) ---

function handlePanStart(e) {
    // Middle mouse button (button 1) or Space + left click
    if (e.button === 1 || (e.button === 0 && state._spaceHeld)) {
        e.preventDefault();
        const container = document.getElementById('editor-container');
        state.isPanning = true;
        state.panStart = {
            x: e.clientX,
            y: e.clientY,
            scrollLeft: container.scrollLeft,
            scrollTop: container.scrollTop,
        };
        container.style.cursor = 'grabbing';
    }
}

function handlePanMove(e) {
    if (!state.isPanning || !state.panStart) return;
    e.preventDefault();
    const container = document.getElementById('editor-container');
    const dx = e.clientX - state.panStart.x;
    const dy = e.clientY - state.panStart.y;
    container.scrollLeft = state.panStart.scrollLeft - dx;
    container.scrollTop = state.panStart.scrollTop - dy;
}

function handlePanEnd(e) {
    if (state.isPanning) {
        state.isPanning = false;
        state.panStart = null;
        const container = document.getElementById('editor-container');
        container.style.cursor = state._spaceHeld ? 'grab' : '';
    }
}

// --- Zoom controls ---

function setZoom(value) {
    state.zoom = Math.max(25, Math.min(800, parseInt(value, 10)));

    // Update slider and label
    const slider = document.getElementById('zoom-slider');
    const label = document.getElementById('zoom-level');
    if (slider) slider.value = state.zoom;
    if (label) label.textContent = state.zoom + '%';

    // Apply zoom using transform for crisp scaling without stretching
    const img = state.imageElement;
    const canvas = state.canvas;
    const scale = state.zoom / 100;

    // Use the image's natural dimensions to calculate correct display size
    const naturalWidth = img.naturalWidth || img.width;
    const naturalHeight = img.naturalHeight || img.height;
    const container = document.getElementById('editor-container');
    const containerWidth = container.clientWidth;

    // Base size: fit to container width at 100%
    const baseWidth = containerWidth;
    const baseHeight = (naturalHeight / naturalWidth) * baseWidth;

    const displayWidth = baseWidth * scale;
    const displayHeight = baseHeight * scale;

    img.style.width = displayWidth + 'px';
    img.style.height = displayHeight + 'px';
    img.style.maxWidth = 'none';

    // Match canvas to image display size
    canvas.style.width = displayWidth + 'px';
    canvas.style.height = displayHeight + 'px';
    canvas.width = displayWidth;
    canvas.height = displayHeight;

    render();
}

function zoomIn() {
    setZoom(state.zoom + 25);
}

function zoomOut() {
    setZoom(state.zoom - 25);
}

function handleWheel(e) {
    if (e.ctrlKey || e.metaKey) {
        // Ctrl+scroll = zoom
        e.preventDefault();
        if (e.deltaY < 0) {
            zoomIn();
        } else {
            zoomOut();
        }
    }
    // Without Ctrl: normal scroll (vertical pan) is handled by browser overflow
}

// --- Trigger auto-detection ---

function toggleDetectMenu() {
    const menu = document.getElementById('detect-menu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

// Close dropdown on outside click
document.addEventListener('click', function(e) {
    const dropdown = document.getElementById('detect-dropdown');
    if (dropdown && !dropdown.contains(e.target)) {
        document.getElementById('detect-menu').style.display = 'none';
    }
});

async function triggerDetection() {
    const btn = document.getElementById('btn-detect');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:-2px;margin-right:6px;"></span>Detekterar...';

    // Get exclusion zones for this page
    const exclusionZones = state.exclusionZones || [];

    const body = {
        page_number: state.currentPage,
        exclusion_zones: exclusionZones,
    };

    try {
        const response = await fetch(`/data/api/detect-v2/${state.attachmentId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (response.ok) {
            const data = await response.json();
            // Add annotations to local state
            if (data.annotations) {
                for (const ann of data.annotations) {
                    if (ann.page_number === state.currentPage) {
                        state.annotations.push(ann);
                    }
                }
            }
            await fetchGroups(state.attachmentId);
            render();
            renderGroupsPanel();

            const methods = data.methods_used ? data.methods_used.join(', ') : 'text';
            if (data.summary && data.summary.total_instances > 0) {
                showInfo(`${data.summary.total_instances} detaljer hittade i ${data.summary.total_types} grupper (metod: ${methods})`);
            } else {
                showInfo('Inga detaljer hittades på denna sida.');
            }
            if (data.warning) {
                showError(data.warning);
            }
        } else if (response.status === 503) {
            showError('Vision-tjänsten är inte tillgänglig.');
        } else {
            const err = await response.json().catch(() => null);
            showError(err?.error || 'Detekteringen misslyckades.');
        }
    } catch (err) {
        showError('Kunde inte ansluta till servern.');
    }

    btn.innerHTML = originalText;
    btn.disabled = false;
}

async function triggerBatchDetection() {
    const btn = document.getElementById('btn-detect');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:-2px;margin-right:6px;"></span>Detekterar alla sidor...';

    const exclusionZones = state.exclusionZones || [];
    const body = {
        batch: true,
        exclusion_zones: exclusionZones,
    };

    try {
        const response = await fetch(`/data/api/detect-v2/${state.attachmentId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (response.ok) {
            const data = await response.json();
            // Reload annotations for current page
            await fetchAnnotations(state.attachmentId, state.currentPage);
            await fetchGroups(state.attachmentId);
            render();
            renderGroupsPanel();

            if (data.summary) {
                showInfo(`${data.summary.total_instances} detaljer hittade i ${data.summary.total_types} grupper (${data.summary.pages_processed} sidor)`);
            }
        } else {
            const err = await response.json().catch(() => null);
            showError(err?.error || 'Batch-detekteringen misslyckades.');
        }
    } catch (err) {
        showError('Kunde inte ansluta till servern.');
    }

    btn.innerHTML = originalText;
    btn.disabled = false;
}

// --- Info notification ---

function showInfo(msg) {
    // Remove existing toast
    const existing = document.querySelector('.info-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'info-toast';
    toast.textContent = msg;
    document.body.appendChild(toast);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.add('info-toast-fade');
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

// --- Trigger analysis ---

async function triggerAnalysis() {
    const btn = document.getElementById('btn-analyze');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:-2px;margin-right:6px;"></span>Analyserar...';

    const container = document.getElementById('editor-container');
    const recordId = container.dataset.recordId;

    try {
        const formData = new FormData();
        formData.append('attachment_ids', state.attachmentId);

        const result = await fetch(`/data/record/${recordId}/analyze`, {
            method: 'POST',
            body: formData,
        });

        if (result.ok || result.redirected) {
            btn.innerHTML = '✓ Klar';
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-secondary');
            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.classList.remove('btn-secondary');
                btn.classList.add('btn-primary');
                btn.disabled = false;
            }, 3000);
        } else {
            showError('Analysen misslyckades.');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    } catch (err) {
        showError('Analysen misslyckades.');
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// --- Initialize on page load ---

document.addEventListener('DOMContentLoaded', function () {
    const container = document.getElementById('editor-container');
    if (container) {
        const attachmentId = parseInt(container.dataset.attachmentId, 10);
        if (attachmentId) {
            init(attachmentId);
        }
    }
});
