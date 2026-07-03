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

    // Load first page
    loadPage(1);
}

function resizeCanvas() {
    const img = state.imageElement;
    state.canvas.width = img.clientWidth;
    state.canvas.height = img.clientHeight;
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
            resizeCanvas();
            render();
        };
        state.imageElement.src = objectUrl;

        // Update page nav UI
        updatePageNav();

        // Fetch annotations for this page
        await fetchAnnotations(state.attachmentId, pageNumber);
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
        const px = fromRatio(ann.x, w);
        const py = fromRatio(ann.y, h);
        const pw = fromRatio(ann.width, w);
        const ph = fromRatio(ann.height, h);

        const isSelected = (ann.id === state.selectedId);

        // Fill
        ctx.fillStyle = isSelected ? 'rgba(52, 152, 219, 0.25)' : 'rgba(52, 152, 219, 0.15)';
        ctx.fillRect(px, py, pw, ph);

        // Border
        ctx.strokeStyle = isSelected ? '#2980b9' : '#3498db';
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.strokeRect(px, py, pw, ph);

        // Resize handles for selected
        if (isSelected) {
            const handleSize = 8;
            const hs = handleSize / 2;
            ctx.fillStyle = '#2980b9';
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
            render();

            // Start move
            state.isDragging = true;
            state.dragAction = 'move';
            state.dragStart = pos;
            state.dragAnnotation = hit;
            state.originalAnnotation = { ...hit };
        } else {
            // Deselect
            state.selectedId = null;
            render();
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
        if (state.mode === 'draw') {
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
            createAnnotation(ann);
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

// --- Mode switching ---

function setMode(mode) {
    state.mode = mode;
    state.selectedId = null;

    // Update toolbar button styles
    document.getElementById('btn-draw').classList.toggle('active', mode === 'draw');
    document.getElementById('btn-select').classList.toggle('active', mode === 'select');
    document.getElementById('btn-pan').classList.toggle('active', mode === 'pan');

    // Update cursor
    if (mode === 'draw') {
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
    state.zoom = Math.max(25, Math.min(300, parseInt(value, 10)));

    // Update slider and label
    const slider = document.getElementById('zoom-slider');
    const label = document.getElementById('zoom-level');
    if (slider) slider.value = state.zoom;
    if (label) label.textContent = state.zoom + '%';

    // Apply zoom by scaling the editor container contents
    const img = state.imageElement;
    const container = document.getElementById('editor-container');

    const scale = state.zoom / 100;
    img.style.width = (scale * 100) + '%';
    img.style.maxWidth = 'none';

    // Resize canvas to match
    resizeCanvas();
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
