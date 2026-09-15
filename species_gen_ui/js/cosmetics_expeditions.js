// Database Editor & Expeditions Grid Handler

let editorTable = null;
let expEditorTable = null;
let builtMods = [];
let editorRequestToken = 0;
let expEditorRequestToken = 0;

function modPathForSelect(mod, selectId) {
    return selectId === 'exp-mod' ? mod.exp_fdb : (mod.dino_fdb || mod.fdb);
}

function selectHasOptionValue(select, value) {
    const options = select.options || select.querySelectorAll('option');
    return Array.from(options || []).some(option => option.value === value);
}

function refreshBuiltMods() {
    backend.list_built_mods((resStr) => {
        const res = JSON.parse(resStr);
        if (!res.success) { backend.show_error(res.error); return; }
        const rawData = res.data || [];
        builtMods = rawData.map(m => {
            if (typeof m === 'string') {
                const dino = `SpeciesGenerator/Generated/${m}/Main/${m.toLowerCase()}dinosaurs.fdb`;
                const exp = `SpeciesGenerator/Generated/${m}/Main/${m.toLowerCase()}expeditions.fdb`;
                return {
                    name: m,
                    fdb: dino,
                    dino_fdb: dino,
                    exp_fdb: exp
                };
            }
            if (m && typeof m === 'object') {
                m.fdb = m.fdb || m.dino_fdb;
                m.dino_fdb = m.dino_fdb || m.fdb;
            }
            return m;
        });


        ['editor-mod', 'exp-mod'].forEach(id => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const prev = sel.value;
            sel.innerHTML = '';

            const defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = '-- Select a Generated Mod --';
            sel.appendChild(defaultOpt);

            builtMods.forEach((m) => {
                const o = document.createElement('option');
                o.value = modPathForSelect(m, id) || '';
                o.textContent = m.name + (id === 'exp-mod' && !m.exp_fdb ? '  (no expeditions FDB)' : '');
                o.disabled = !o.value;
                sel.appendChild(o);
            });

            if (prev !== "" && prev !== null && selectHasOptionValue(sel, prev)) {
                sel.value = prev;
            } else {
                sel.value = '';
            }
        });

        if (builtMods.length === 0) {
            const g = document.getElementById('editor-grid');
            if (g) g.innerHTML = '<p class="hint">No generated mods found yet. Build one first.</p>';
        } else {
            loadExistingDigsites();
        }
    });
}

function selectedMod(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel || sel.value === "" || sel.value === null) return null;
    return builtMods.find(m => modPathForSelect(m, selectId) === sel.value) || null;
}

function setGridSaveEnabled(gridId, enabled) {
    const id = gridId === 'exp-editor-grid' ? 'btn-exp-editor-save' : 'btn-editor-save';
    const button = document.getElementById(id);
    if (button) button.disabled = !enabled;
}

function invalidateGrid(gridId) {
    if (gridId === 'exp-editor-grid') {
        expEditorRequestToken += 1;
        expEditorTable = null;
    } else {
        editorRequestToken += 1;
        editorTable = null;
    }
    setGridSaveEnabled(gridId, false);
    const container = document.getElementById(gridId);
    if (container) {
        container.innerHTML = '<p class="hint">Load the selected table to edit it.</p>';
    }
}

function guardGridSelectionChange(gridId, changedSelect) {
    const tableData = gridId === 'exp-editor-grid' ? expEditorTable : editorTable;
    if (tableData && tableData.dirty && typeof confirm === 'function' &&
            !confirm('This grid has unsaved edits. Discard them and change selection?')) {
        if (changedSelect.id === 'editor-mod' || changedSelect.id === 'exp-mod') {
            changedSelect.value = tableData.databasePath;
        } else {
            changedSelect.value = tableData.tableName;
        }
        return false;
    }
    invalidateGrid(gridId);
    return true;
}

function syncGridModel(gridId) {
    const tableData = gridId === 'exp-editor-grid' ? expEditorTable : editorTable;
    const container = document.getElementById(gridId);
    if (!tableData || !container) return;
    const rows = [];
    container.querySelectorAll('tbody tr[data-row-idx]').forEach(tr => {
        rows.push(Array.from(tr.querySelectorAll('input')).map(input =>
            input.value === '' ? null : input.value));
    });
    tableData.rows = rows;
}


function setupEditorPage() {
    const load = document.getElementById('btn-editor-load');
    const save = document.getElementById('btn-editor-save');
    const add = document.getElementById('btn-editor-addrow');
    if (!load) return;

    const modSelect = document.getElementById('editor-mod');
    const tableSelect = document.getElementById('editor-table');
    [modSelect, tableSelect].forEach(select => {
        if (select) select.addEventListener('change', () =>
            guardGridSelectionChange('editor-grid', select));
    });
    setGridSaveEnabled('editor-grid', false);

    load.onclick = () => {
        if (typeof logButtonClick === 'function') logButtonClick('btn-editor-load', 'Load Mod Table');
        const mod = selectedMod('editor-mod');
        if (!mod) { backend.show_error("Pick a generated mod first."); return; }
        const table = document.getElementById('editor-table').value;
        const fdbPath = mod.dino_fdb || mod.fdb;
        invalidateGrid('editor-grid');
        const token = ++editorRequestToken;
        backend.load_mod_table(fdbPath, table, (resStr) => {
            const res = JSON.parse(resStr);
            if (token !== editorRequestToken) return;
            if (!res.success) {
                invalidateGrid('editor-grid');
                backend.show_error(res.error);
                return;
            }
            editorTable = Object.assign({}, res.data, {
                databasePath: fdbPath, tableName: table, requestToken: token, dirty: false
            });
            renderEditorGrid(editorTable, 'editor-grid');
            setGridSaveEnabled('editor-grid', true);
            checkEditorProblems(fdbPath);
        });
    };

    save.onclick = () => {
        if (typeof logButtonClick === 'function') logButtonClick('btn-editor-save', 'Save Mod Table');
        if (!editorTable) return;
        syncGridModel('editor-grid');
        const fdbPath = editorTable.databasePath;
        const table = editorTable.tableName;
        backend.save_mod_table(fdbPath, table, JSON.stringify(editorTable), (resStr) => {
            const res = JSON.parse(resStr);
            if (!res.success) {
                backend.show_error(res.error);
                return;
            }
            showEditorProblems(res.problems || []);
            editorTable.dirty = false;
            alert(`Saved ${res.written} rows to ${table}.`);
        });
    };


    add.onclick = () => {
        if (typeof logButtonClick === 'function') logButtonClick('btn-editor-addrow', 'Add Row to Mod Table');
        if (!editorTable) return;
        syncGridModel('editor-grid');
        const emptyRow = editorTable.columns.map(() => null);
        editorTable.rows.push(emptyRow);
        editorTable.dirty = true;
        renderEditorGrid(editorTable, 'editor-grid');
    };
}

function renderEditorGrid(tableData = editorTable, gridId = 'editor-grid') {
    const container = document.getElementById(gridId);
    if (!container || !tableData) return;

    let html = `<div class="editor-grid-container" style="overflow-x: auto; max-height: 60vh;"><table class="editor-table" id="${gridId}-table"><thead><tr>`;
    tableData.columns.forEach((col, idx) => {
        html += `<th style="position: relative; padding: 8px 12px; background: rgba(30, 38, 50, 0.9); border: 1px solid rgba(255,255,255,0.1); color: #40a0ff; font-size: 0.85rem; text-align: left; min-width: 120px;" data-col-idx="${idx}">
            <span class="col-title">${col}</span>
            <div class="resizer" style="position: absolute; right: 0; top: 0; bottom: 0; width: 6px; cursor: col-resize; background: rgba(64, 160, 255, 0.2);"></div>
        </th>`;
    });
    html += '<th style="padding: 8px 12px; background: rgba(30, 38, 50, 0.9); border: 1px solid rgba(255,255,255,0.1); color: #ff6060; width: 40px;"></th>';
    html += '</tr></thead><tbody>';

    if (tableData.rows && tableData.rows.length > 0) {
        tableData.rows.forEach((row, rIdx) => {
            html += `<tr data-row-idx="${rIdx}">`;
            tableData.columns.forEach((col, cIdx) => {
                const val = row[cIdx] !== null && row[cIdx] !== undefined ? String(row[cIdx]) : "";
                html += `<td style="padding: 4px; border: 1px solid rgba(255,255,255,0.06);"><input type="text" class="form-control prop-grid-input" value="${escapeEditorHtml(val)}" data-col-idx="${cIdx}" style="width: 100%; padding: 4px 8px; font-size: 0.85rem; border-radius: 3px; border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.2); color: #e0e6ed;"></td>`;
            });
            html += `<td style="padding: 4px; text-align: center; border: 1px solid rgba(255,255,255,0.06);"><button class="btn-icon btn-del-grid-row" onclick="deleteEditorRow('${gridId}', ${rIdx})" style="color: #ff6060; cursor: pointer; border: none; background: transparent;">✕</button></td>`;
            html += '</tr>';
        });
    } else {
        html += `<tr><td colspan="${tableData.columns.length + 1}" style="padding: 12px; text-align: center; color: #8a96a8;">No rows found in table. Click '+ Add Row' to insert one.</td></tr>`;
    }
    html += '</tbody></table></div>';
    container.innerHTML = html;

    const tableEl = document.getElementById(`${gridId}-table`);
    if (tableEl) {
        initTableResizers(tableEl);
        tableEl.querySelectorAll('tbody input').forEach(input => {
            input.addEventListener('input', () => {
                const target = gridId === 'exp-editor-grid' ? expEditorTable : editorTable;
                if (!target) return;
                const rowIndex = parseInt(input.closest('tr').dataset.rowIdx, 10);
                const colIndex = parseInt(input.dataset.colIdx, 10);
                target.rows[rowIndex][colIndex] = input.value === '' ? null : input.value;
                target.dirty = true;
            });
        });
    }
}

function escapeEditorHtml(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function initTableResizers(table) {
    const cols = table.querySelectorAll('th');
    cols.forEach(col => {
        const resizer = col.querySelector('.resizer');
        if (!resizer) return;

        let startX, startWidth;

        const onMouseMove = (e) => {
            const width = startWidth + (e.clientX - startX);
            if (width > 40) {
                col.style.width = `${width}px`;
                col.style.minWidth = `${width}px`;
            }
        };

        const onMouseUp = () => {
            resizer.classList.remove('resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };

        resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            startX = e.clientX;
            startWidth = col.offsetWidth;
            resizer.classList.add('resizing');
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    });
}

function deleteEditorRow(gridId, rIdx) {
    const tableData = gridId === 'exp-editor-grid' ? expEditorTable : editorTable;
    if (!tableData || !tableData.rows) return;
    syncGridModel(gridId);
    tableData.rows.splice(rIdx, 1);
    tableData.dirty = true;
    renderEditorGrid(tableData, gridId);
}

function checkEditorProblems(fdbPath) {
    backend.check_table_problems(fdbPath, (resStr) => {
        const res = JSON.parse(resStr);
        showEditorProblems(res.problems || []);
    });
}

function showEditorProblems(problems) {
    const list = document.getElementById('editor-problems');
    if (!list) return;
    list.innerHTML = '';
    problems.forEach(p => {
        const li = document.createElement('li');
        li.textContent = `⚠️ ${p}`;
        list.appendChild(li);
    });
}

// ----------------------------------------------------------- expeditions

function setupExpeditionsPage() {
    const btn = document.getElementById('btn-exp-add');
    const expModSel = document.getElementById('exp-mod');

    const capture = document.getElementById('exp-capture');
    const marine = document.getElementById('exp-marine');
    const yields = document.getElementById('exp-yield-group');

    if (capture && yields && marine) {
        const syncCapture = () => {
            yields.style.display = capture.checked ? 'none' : '';
            marine.disabled = !capture.checked;
            if (!capture.checked) marine.checked = false;
        };
        capture.onchange = syncCapture;
        syncCapture();
    }

    if (expModSel) {
        expModSel.onchange = () => {
            if (guardGridSelectionChange('exp-editor-grid', expModSel)) {
                loadExistingDigsites();
            }
        };
    }
    const expTableSel = document.getElementById('exp-table-select');
    if (expTableSel) {
        expTableSel.onchange = () =>
            guardGridSelectionChange('exp-editor-grid', expTableSel);
    }
    setGridSaveEnabled('exp-editor-grid', false);

    if (btn) {
        btn.onclick = () => {
            if (typeof logButtonClick === 'function') logButtonClick('btn-exp-add', 'Add Dig Site');
            const mod = selectedMod('exp-mod');
            if (!mod) { backend.show_error("Pick a generated mod first."); return; }
            if (!mod.exp_fdb) {
                backend.show_error("This mod has no expeditions FDB, so dig sites cannot be added.");
                return;
            }
            const cap = capture ? capture.checked : false;
            const site = {
                SiteID: document.getElementById('exp-siteid').value.trim(),
                LocationID: parseInt(document.getElementById('exp-locid').value),
                Territory: document.getElementById('exp-territory').value.trim() || null,
                CountryLocString: document.getElementById('exp-country').value.trim() || null,
                LocationLocString: document.getElementById('exp-location').value.trim() || null,
                Lattitude: parseFloat(document.getElementById('exp-lat').value),
                Longitude: parseFloat(document.getElementById('exp-long').value),
                CaptureSite: cap ? 1 : 0,
                MarineLocation: (cap && marine && marine.checked) ? 1 : 0,
                NormalFossilYield: cap ? null : (document.getElementById('exp-normal').value.trim() || null),
                TargetFossilYield: cap ? null : (document.getElementById('exp-junk') ? document.getElementById('exp-junk').value.trim() : null),
            };
            if (!site.SiteID || isNaN(site.LocationID)) {
                backend.show_error("Site ID and Location ID are required.");
                return;
            }

            const fossilRows = [];
            document.querySelectorAll('.exp-fossil-row').forEach(row => {
                const fid = row.querySelector('.exp-fid').value.trim();
                if (!fid) return;
                fossilRows.push({
                    FossilID: fid,
                    Size: parseInt(row.querySelector('.exp-fsize').value),
                    Quantity: parseInt(row.querySelector('.exp-fqty').value),
                });
            });

            const payload = JSON.stringify({
                site: site,
                fossils: fossilRows,
                mirror: document.getElementById('exp-mirror') ? document.getElementById('exp-mirror').checked : true,
            });

            backend.add_digsite(mod.exp_fdb, payload, (resStr) => {
                const res = JSON.parse(resStr);
                if (!res.success) { backend.show_error(res.error); return; }
                alert(`Dig site added! Modified tables: ${res.tables ? res.tables.join(', ') : ''}`);
                loadExistingDigsites();
            });
        };
    }

    const addFossil = document.getElementById('btn-exp-add-fossil');
    if (addFossil) {
        addFossil.onclick = () => {
            if (typeof logButtonClick === 'function') logButtonClick('btn-exp-add-fossil', 'Add Fossil Row');
            const host = document.getElementById('exp-fossils-list');
            const template = document.getElementById('tpl-exp-fossil-row');
            if (host && template && template.content) {
                const clone = template.content.cloneNode(true);
                clone.querySelector('.btn-remove-fossil').onclick = (e) => {
                    e.target.closest('.exp-fossil-row').remove();
                };
                host.appendChild(clone);
            }
        };
    }

    // Expeditions Table Editor Wiring
    const expLoad = document.getElementById('btn-exp-editor-load');
    if (expLoad) {
        expLoad.onclick = () => {
            if (typeof logButtonClick === 'function') logButtonClick('btn-exp-editor-load', 'Load Expeditions Table');
            loadExpeditionTable();
        };
    }

    const expAddRow = document.getElementById('btn-exp-editor-addrow');
    if (expAddRow) {
        expAddRow.onclick = () => {
            if (typeof logButtonClick === 'function') logButtonClick('btn-exp-editor-addrow', 'Add Expeditions Table Row');
            addExpeditionRow();
        };
    }

    const expSave = document.getElementById('btn-exp-editor-save');
    if (expSave) {
        expSave.onclick = () => {
            if (typeof logButtonClick === 'function') logButtonClick('btn-exp-editor-save', 'Save Expeditions Table');
            saveExpeditionTable();
        };
    }
}

function loadExistingDigsites() {
    const mod = selectedMod('exp-mod');
    const listEl = document.getElementById('exp-list');
    const tableSelect = document.getElementById('exp-table-select');

    if (!mod || !mod.exp_fdb) {
        invalidateGrid('exp-editor-grid');
        if (listEl) listEl.innerHTML = '<p class="hint">Select a generated mod with an expeditions FDB first.</p>';
        const grid = document.getElementById('exp-editor-grid');
        if (grid) grid.innerHTML = '<p class="hint">Select a generated mod with an expeditions FDB first.</p>';
        return;
    }

    // 1. Fetch & Render Existing Dig Sites into #exp-list
    backend.load_mod_table(mod.exp_fdb, 'DigSites', (resStr) => {
        const res = JSON.parse(resStr);
        if (!res.success || !res.data) {
            if (listEl) listEl.innerHTML = `<p class="hint">Could not load DigSites: ${res.error || 'Unknown error'}</p>`;
            return;
        }

        const cols = res.data.columns || [];
        const rows = res.data.rows || [];

        if (rows.length === 0) {
            if (listEl) listEl.innerHTML = '<p class="hint">No dig sites configured in this mod yet.</p>';
        } else {
            const siteIdIdx = cols.indexOf('SiteID');
            const locIdIdx = cols.indexOf('LocationID');
            const countryIdx = cols.indexOf('CountryLocString');
            const locStrIdx = cols.indexOf('LocationLocString');
            const capIdx = cols.indexOf('CaptureSite');
            const yieldIdx = cols.indexOf('NormalFossilYield');

            let html = '<div style="overflow-x:auto;"><table class="editor-table" style="width:100%; border-collapse:collapse; margin-top:8px;">';
            html += '<thead><tr><th style="padding:6px 10px; background:rgba(30,38,50,0.8); text-align:left; border:1px solid rgba(255,255,255,0.1); color:#40a0ff;">Site ID</th>';
            html += '<th style="padding:6px 10px; background:rgba(30,38,50,0.8); text-align:left; border:1px solid rgba(255,255,255,0.1); color:#40a0ff;">Loc ID</th>';
            html += '<th style="padding:6px 10px; background:rgba(30,38,50,0.8); text-align:left; border:1px solid rgba(255,255,255,0.1); color:#40a0ff;">Location</th>';
            html += '<th style="padding:6px 10px; background:rgba(30,38,50,0.8); text-align:left; border:1px solid rgba(255,255,255,0.1); color:#40a0ff;">Type</th>';
            html += '<th style="padding:6px 10px; background:rgba(30,38,50,0.8); text-align:left; border:1px solid rgba(255,255,255,0.1); color:#40a0ff;">Yield</th></tr></thead><tbody>';

            rows.forEach(r => {
                const sid = siteIdIdx >= 0 ? r[siteIdIdx] : '—';
                const lid = locIdIdx >= 0 ? r[locIdIdx] : '—';
                const ctr = countryIdx >= 0 ? r[countryIdx] : '';
                const lstr = locStrIdx >= 0 ? r[locStrIdx] : '';
                const locationText = [ctr, lstr].filter(Boolean).join(', ') || 'Default Location';
                const isCap = capIdx >= 0 && r[capIdx] === 1;
                const yld = yieldIdx >= 0 ? (r[yieldIdx] || '—') : '—';

                html += `<tr><td style="padding:6px 10px; border:1px solid rgba(255,255,255,0.06);"><strong>${sid}</strong></td>`;
                html += `<td style="padding:6px 10px; border:1px solid rgba(255,255,255,0.06);">${lid}</td>`;
                html += `<td style="padding:6px 10px; border:1px solid rgba(255,255,255,0.06);">${locationText}</td>`;
                html += `<td style="padding:6px 10px; border:1px solid rgba(255,255,255,0.06);">${isCap ? '<span style="color:#60c0ff;">Capture Site</span>' : '<span style="color:#ffd275;">Dig Site</span>'}</td>`;
                html += `<td style="padding:6px 10px; border:1px solid rgba(255,255,255,0.06);">${yld}</td></tr>`;
            });
            html += '</tbody></table></div>';
            if (listEl) listEl.innerHTML = html;
        }
    });

    // 2. Load Selected Expeditions Table into Editor Grid
    if (tableSelect) {
        const table = tableSelect.value;
        invalidateGrid('exp-editor-grid');
        const token = ++expEditorRequestToken;
        const fdbPath = mod.exp_fdb;
        backend.load_mod_table(mod.exp_fdb, table, (resStr) => {
            const res = JSON.parse(resStr);
            if (token !== expEditorRequestToken) return;
            if (!res.success) {
                invalidateGrid('exp-editor-grid');
                const grid = document.getElementById('exp-editor-grid');
                if (grid) grid.innerHTML = `<p class="hint">${res.error}</p>`;
                return;
            }
            expEditorTable = Object.assign({}, res.data, {
                databasePath: fdbPath, tableName: table, requestToken: token, dirty: false
            });
            renderEditorGrid(expEditorTable, 'exp-editor-grid');
            setGridSaveEnabled('exp-editor-grid', true);
        });
    }
}

function loadExpeditionTable() {
    loadExistingDigsites();
}

function addExpeditionRow() {
    if (!expEditorTable) {
        backend.show_error("Load an Expeditions table first.");
        return;
    }
    syncGridModel('exp-editor-grid');
    const emptyRow = expEditorTable.columns.map(() => null);
    expEditorTable.rows.push(emptyRow);
    expEditorTable.dirty = true;
    renderEditorGrid(expEditorTable, 'exp-editor-grid');
}

function saveExpeditionTable() {
    if (!expEditorTable) {
        backend.show_error("Load an Expeditions table first.");
        return;
    }
    syncGridModel('exp-editor-grid');
    const table = expEditorTable.tableName;
    const fdbPath = expEditorTable.databasePath;
    const newRows = expEditorTable.rows;
    backend.save_mod_table(fdbPath, table, JSON.stringify(expEditorTable), (resStr) => {
        const res = JSON.parse(resStr);
        if (!res.success) {
            backend.show_error(res.error);
            return;
        }
        expEditorTable.dirty = false;
        alert(`Saved ${res.written || newRows.length} rows to ${table}.`);
    });
}

// Small CommonJS surface for the headless regression harness. Browsers ignore
// this block; production state remains owned by this file.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        setupEditorPage,
        selectedMod,
        deleteEditorRow,
        escapeEditorHtml,
        selectHasOptionValue,
        _setBuiltMods: value => { builtMods = value; },
        _setEditorTable: value => { editorTable = value; },
        _setExpEditorTable: value => { expEditorTable = value; },
        _getEditorTable: () => editorTable,
        _getExpEditorTable: () => expEditorTable,
    };
}
