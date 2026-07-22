// Data Cloning Tables & Overrides Page Handler

let activeDonorTables = [];

function setupDataOverridesPage() {
    const btnSelectAll = document.getElementById('btn-select-all-tables');
    const btnSelectNone = document.getElementById('btn-select-none-tables');
    const btnAddOverride = document.getElementById('btn-add-override');

    if (btnSelectAll) {
        btnSelectAll.onclick = () => {
            const checklist = document.getElementById('table-list');
            if (!checklist) return;
            checklist.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            saveDataOverridesState();
        };
    }

    if (btnSelectNone) {
        btnSelectNone.onclick = () => {
            const checklist = document.getElementById('table-list');
            if (!checklist) return;
            checklist.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            saveDataOverridesState();
        };
    }

    if (btnAddOverride) {
        btnAddOverride.onclick = () => addOverrideRow();
    }
}

function renderDataOverridesPage(donorTables) {
    const sp = (currentSpeciesIndex >= 0 && modProject.species[currentSpeciesIndex]) ? modProject.species[currentSpeciesIndex] : null;

    if (donorTables) {
        if (Array.isArray(donorTables)) {
            activeDonorTables = donorTables;
        } else if (typeof donorTables === 'object') {
            activeDonorTables = Object.keys(donorTables);
        }
    }

    if (sp && sp.source && activeDonorTables.length === 0) {
        backend.scan_donor(sp.source, (resStr) => {
            const res = JSON.parse(resStr);
            if (res.success && res.data && res.data.tables) {
                activeDonorTables = Object.keys(res.data.tables);
                renderTableChecklist(sp);
                renderOverridesList(sp);
            }
        });
        return;
    }

    renderTableChecklist(sp);
    renderOverridesList(sp);
}

function renderTableChecklist(sp) {
    const container = document.getElementById('table-list');
    if (!container) return;
    container.innerHTML = '';

    if (!sp || !sp.source || activeDonorTables.length === 0) {
        container.innerHTML = '<li class="placeholder">Select a donor species first...</li>';
        return;
    }

    const skippedSet = new Set((sp.skip || []).map(s => s.toLowerCase()));
    const onlySet = new Set((sp.only || []).map(s => s.toLowerCase()));
    const hasOnly = sp.only && sp.only.length > 0;

    activeDonorTables.forEach(tableName => {
        const li = document.createElement('li');
        li.className = 'checkbox-item';
        li.style.display = 'flex';
        li.style.alignItems = 'center';
        li.style.gap = '8px';
        li.style.padding = '4px 0';

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.dataset.tableName = tableName;

        const lowerName = tableName.toLowerCase();
        if (hasOnly) {
            cb.checked = onlySet.has(lowerName);
        } else {
            cb.checked = !skippedSet.has(lowerName);
        }

        cb.addEventListener('change', saveDataOverridesState);

        const lbl = document.createElement('label');
        lbl.textContent = tableName;
        lbl.style.cursor = 'pointer';
        lbl.onclick = () => { cb.checked = !cb.checked; saveDataOverridesState(); };

        li.appendChild(cb);
        li.appendChild(lbl);
        container.appendChild(li);
    });
}

function saveDataOverridesState() {
    if (currentSpeciesIndex < 0 || !modProject.species[currentSpeciesIndex]) return;
    const sp = modProject.species[currentSpeciesIndex];

    const container = document.getElementById('table-list');
    if (!container) return;

    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    const checkedTables = [];
    const uncheckedTables = [];

    checkboxes.forEach(cb => {
        const name = cb.dataset.tableName;
        if (cb.checked) checkedTables.push(name);
        else uncheckedTables.push(name);
    });

    if (uncheckedTables.length > 0) {
        sp.skip = uncheckedTables;
        sp.only = [];
    } else {
        sp.skip = [];
        sp.only = [];
    }

    saveOverridesFromUI(sp);
}

function renderOverridesList(sp) {
    const container = document.getElementById('overrides-list');
    if (!container) return;
    container.innerHTML = '';

    if (!sp) return;

    if (!sp.overrides) sp.overrides = {};

    const overrideKeys = Object.keys(sp.overrides);
    if (overrideKeys.length === 0) {
        addOverrideRow("", "", "");
        return;
    }

    overrideKeys.forEach(tableCol => {
        let tableName = tableCol;
        let colName = "";
        if (tableCol.includes(".")) {
            const parts = tableCol.split(".");
            tableName = parts[0];
            colName = parts[1];
        }
        const val = sp.overrides[tableCol];
        addOverrideRow(tableName, colName, val);
    });
}

function addOverrideRow(tableVal = "", colVal = "", valVal = "") {
    const container = document.getElementById('overrides-list');
    if (!container) return;

    const template = document.getElementById('tpl-override-row');
    let clone;
    if (template && template.content) {
        clone = template.content.cloneNode(true);
    } else {
        const div = document.createElement('div');
        div.innerHTML = `
            <div class="override-row" style="display: flex; gap: 6px; align-items: center; margin-bottom: 8px;">
                <input type="text" class="ov-table form-control" placeholder="Table (e.g. SpeciesStats)" style="flex: 1; padding: 6px;">
                <span class="dot">.</span>
                <input type="text" class="ov-column form-control" placeholder="Column" style="flex: 1; padding: 6px;">
                <span class="equals">=</span>
                <input type="text" class="ov-value form-control" placeholder="Value" style="flex: 1; padding: 6px;">
                <button class="btn-icon btn-remove-override" style="padding: 4px 8px; cursor: pointer;">✕</button>
            </div>
        `;
        clone = div;
    }

    const row = clone.querySelector('.override-row');
    const tableInput = row.querySelector('.ov-table');
    const colInput = row.querySelector('.ov-column');
    const valInput = row.querySelector('.ov-value');
    const removeBtn = row.querySelector('.btn-remove-override');

    tableInput.value = tableVal;
    colInput.value = colVal;
    valInput.value = valVal;

    [tableInput, colInput, valInput].forEach(inp => {
        inp.addEventListener('input', () => {
            if (currentSpeciesIndex >= 0 && modProject.species[currentSpeciesIndex]) {
                saveOverridesFromUI(modProject.species[currentSpeciesIndex]);
            }
        });
    });

    removeBtn.addEventListener('click', () => {
        row.remove();
        if (currentSpeciesIndex >= 0 && modProject.species[currentSpeciesIndex]) {
            saveOverridesFromUI(modProject.species[currentSpeciesIndex]);
        }
    });

    container.appendChild(clone);
}

function saveOverridesFromUI(sp) {
    if (!sp) return;
    const container = document.getElementById('overrides-list');
    if (!container) return;

    const rows = container.querySelectorAll('.override-row');
    const overrides = {};

    rows.forEach(row => {
        const table = row.querySelector('.ov-table').value.trim();
        const col = row.querySelector('.ov-column').value.trim();
        const valStr = row.querySelector('.ov-value').value.trim();

        if (table && col && valStr !== "") {
            let val;
            if (valStr === "true") val = true;
            else if (valStr === "false") val = false;
            else if (!isNaN(valStr)) val = parseFloat(valStr);
            else val = valStr;

            const key = `${table}.${col}`;
            overrides[key] = val;
        }
    });

    sp.overrides = overrides;
}
