// Prefab Builder Handler & Inheritance Resolver

const ROOT_PROPERTIES_WHITELIST = [
    "ModelName",
    "AssetPackages",
    "MaterialEffectsName",
    "MotionGraphName",
    "MaterialLayersName",
    "MaterialAllowInferredFeathersIndexes",
    "DecalPrefabName",
    "DecalOffset"
];

// Mirror of `normalise_scale_range()` in core/generator.py. A scale entry may be
// a bare number (fixed size), a [min, max] pair, or a dict with min/max keys;
// keep the two in step or the UI will show something the generator does not write.
function readScaleBand(value, fallback) {
    const fb = (fallback !== undefined && fallback !== null) ? fallback : 1.0;
    let lo = null, hi = null;

    if (value !== null && typeof value === 'object') {
        if (Array.isArray(value)) {
            lo = value[0];
            hi = value.length >= 2 ? value[1] : value[0];
        } else {
            for (const k of ['min', 'fMin', 'Min', 'MinScale']) {
                if (value[k] !== undefined && value[k] !== null) { lo = value[k]; break; }
            }
            for (const k of ['max', 'fMax', 'Max', 'MaxScale']) {
                if (value[k] !== undefined && value[k] !== null) { hi = value[k]; break; }
            }
            // A dict carrying only one bound is a fixed size, not half a band.
            if (lo === null) lo = hi;
            if (hi === null) hi = lo;
        }
    } else if (value !== undefined && value !== null && value !== "") {
        lo = hi = value;
    }

    let nLo = parseFloat(lo), nHi = parseFloat(hi);
    if (isNaN(nLo) && isNaN(nHi)) { nLo = nHi = parseFloat(fb); }
    if (isNaN(nLo)) nLo = nHi;
    if (isNaN(nHi)) nHi = nLo;
    if (isNaN(nLo)) nLo = nHi = 1.0;
    return { min: nLo, max: nHi };
}

// Store a fixed size as a bare number so projects that never used a band keep
// their original JSON shape; only a real band writes the {min, max} dict.
function writeScaleBand(sp, memberKey, minVal, maxVal, vary) {
    if (!sp.scales) sp.scales = {};
    let lo = parseFloat(minVal), hi = parseFloat(maxVal);
    if (isNaN(lo) && isNaN(hi)) { lo = hi = 1.0; }
    if (isNaN(lo)) lo = hi;
    if (!vary || isNaN(hi)) hi = lo;
    sp.scales[memberKey] = (lo === hi) ? lo : { min: lo, max: hi };
}

// Show the max field only when varying, and keep the label and hint honest
// about which of the two modes is in force.
function updateScaleBandUI(panel) {
    const label = panel.querySelector('.prefab-scale-label');
    const hint = panel.querySelector('.prefab-scale-hint');
    const minInput = panel.querySelector('.prefab-scale-min-input');
    const maxInput = panel.querySelector('.prefab-scale-max-input');
    const varyBox = panel.querySelector('.prefab-scale-vary');
    if (!minInput || !maxInput || !varyBox) return;

    const vary = varyBox.checked;
    maxInput.style.display = vary ? '' : 'none';
    minInput.placeholder = vary ? 'Min' : '1.0';
    if (label) label.textContent = vary ? 'Render Scale Band (Min / Max):' : 'Render Scale Multiplier:';
    if (!hint) return;

    const lo = parseFloat(minInput.value), hi = parseFloat(maxInput.value);
    // max < min is legal input mid-typing; the backend swaps it, so only warn.
    if (vary && !isNaN(lo) && !isNaN(hi) && hi < lo) {
        hint.textContent = 'Max is below Min — the bounds will be swapped on generate.';
        hint.style.color = '#e0b34a';
    } else if (vary) {
        hint.textContent = 'Every animal rolls its own size inside this band.';
        hint.style.color = '';
    } else {
        hint.textContent = 'Every animal is this exact size.';
        hint.style.color = '';
    }
}

function getInheritedPropValue(parentPrefabName, propName) {
    if (!prefabIndex || !parentPrefabName) return "";
    let current = parentPrefabName.toLowerCase();
    let visited = new Set();

    while (current && !visited.has(current)) {
        visited.add(current);
        const entry = prefabIndex.entries[current];
        if (!entry) break;

        if (entry.props && entry.props[propName] !== undefined && entry.props[propName] !== null) {
            return entry.props[propName];
        }

        if (entry.parent) {
            current = entry.parent.toLowerCase();
        } else {
            break;
        }
    }
    return "";
}

function resolveDefaultParentPrefab(sourceName, memberKey, suffix) {
    if (!sourceName) return "";
    const baseSrc = sourceName.trim().toLowerCase();

    if (prefabIndex && prefabIndex.entries) {
        if (memberKey === "Female" || suffix === "") {
            if (prefabIndex.entries[baseSrc]) {
                return prefabIndex.entries[baseSrc].name;
            }
            if (prefabIndex.entries[baseSrc + "_female"]) {
                return prefabIndex.entries[baseSrc + "_female"].name;
            }
        } else if (memberKey === "Male" || suffix === "_male") {
            if (prefabIndex.entries[baseSrc + "_male"]) {
                return prefabIndex.entries[baseSrc + "_male"].name;
            }
            if (prefabIndex.entries[baseSrc]) {
                return prefabIndex.entries[baseSrc].name;
            }
        } else if (memberKey === "Juvenile" || suffix === "_juvenile") {
            if (prefabIndex.entries[baseSrc + "_juvenile"]) {
                return prefabIndex.entries[baseSrc + "_juvenile"].name;
            }
            if (prefabIndex.entries[baseSrc]) {
                return prefabIndex.entries[baseSrc].name;
            }
        }
    }

    return sourceName + suffix;
}

function populatePrefabTabs() {
    const tabsContainer = document.getElementById('prefab-tabs');
    const contentContainer = document.getElementById('prefab-tab-content');
    if (!tabsContainer || !contentContainer) return;

    tabsContainer.innerHTML = '';
    contentContainer.innerHTML = '';

    if (currentSpeciesIndex < 0 || !modProject.species[currentSpeciesIndex]) {
        contentContainer.innerHTML = '<p class="hint">Please select or add a species in the Roster first.</p>';
        return;
    }

    const sp = modProject.species[currentSpeciesIndex];
    if (!sp.name) {
        contentContainer.innerHTML = '<p class="hint">Species needs a name to build prefabs.</p>';
        return;
    }

    const members = [
        { key: "Female", label: "Female (Base Adult)", suffix: "" },
        { key: "Male", label: "Male", suffix: "_male" },
        { key: "Juvenile", label: "Juvenile", suffix: "_juvenile" }
    ];

    members.forEach((m, idx) => {
        const memberKey = m.key;
        const tab = document.createElement('div');
        tab.className = `tab ${idx === 0 ? 'active' : ''}`;
        tab.textContent = m.label;
        tabsContainer.appendChild(tab);

        const template = document.getElementById('tpl-prefab-tab-panel');
        let clone;
        if (template && template.content) {
            clone = template.content.cloneNode(true);
        } else {
            const div = document.createElement('div');
            div.innerHTML = `
                <div class="prefab-panel">
                    <div class="form-group search-container mb-3" style="position: relative;">
                        <label class="small text-muted" style="display: block; margin-bottom: 4px; font-weight: bold;">Inherit From (Parent Prefab):</label>
                        <input type="text" class="prefab-parent-input form-control" placeholder="Search parent prefab... (e.g. Triceratops)" autocomplete="off">
                        <ul class="search-dropdown dropdown-menu" style="display: none; position: absolute; z-index: 1000; left: 0; right: 0; max-height: 200px; overflow-y: auto;"></ul>
                    </div>
                    <div class="properties-list"></div>
                </div>
            `;
            clone = div;
        }

        const panel = clone.querySelector('.prefab-panel');

        panel.style.display = idx === 0 ? 'block' : 'none';
        panel.dataset.memberKey = memberKey;

        contentContainer.appendChild(clone);

        const parentInput = panel.querySelector('.prefab-parent-input');
        const scaleMinInput = panel.querySelector('.prefab-scale-min-input');
        const scaleMaxInput = panel.querySelector('.prefab-scale-max-input');
        const dropdown = panel.querySelector('.search-dropdown');
        const propList = panel.querySelector('.properties-list');

        let parentPrefabName = "";
        if (sp.prefab_overrides && sp.prefab_overrides[memberKey] && sp.prefab_overrides[memberKey].Prefab) {
            parentPrefabName = sp.prefab_overrides[memberKey].Prefab;
        } else if (sp.donor_prefabs && sp.donor_prefabs[memberKey]) {
            parentPrefabName = sp.donor_prefabs[memberKey];
        } else {
            parentPrefabName = resolveDefaultParentPrefab(sp.source, memberKey, m.suffix);
        }
        parentInput.value = parentPrefabName;





        if (!sp.scales) sp.scales = {};
        const memberScale = (sp.scales[memberKey] !== undefined && sp.scales[memberKey] !== null) ? sp.scales[memberKey] : sp.scale;
        const band = readScaleBand(memberScale, 1.0);
        const varyBox = panel.querySelector('.prefab-scale-vary');
        if (scaleMinInput && scaleMaxInput) {
            scaleMinInput.value = band.min;
            scaleMaxInput.value = band.max;
            // A stored band with two different bounds is what "varying" means,
            // so an existing project re-opens with the box already ticked.
            if (varyBox) varyBox.checked = band.min !== band.max;
            updateScaleBandUI(panel);

            const commitScale = () => {
                writeScaleBand(sp, memberKey, scaleMinInput.value, scaleMaxInput.value,
                               varyBox ? varyBox.checked : false);
                updateScaleBandUI(panel);
                savePrefabProperties(memberKey, panel, sp);
            };

            [scaleMinInput, scaleMaxInput].forEach(input => {
                input.addEventListener('input', commitScale);
            });
            if (varyBox) {
                varyBox.addEventListener('change', () => {
                    // Turning variation on with both bounds equal reads as "no
                    // variation" to the backend, so seed a visible band.
                    if (varyBox.checked && scaleMaxInput.value === scaleMinInput.value) {
                        const lo = parseFloat(scaleMinInput.value);
                        if (!isNaN(lo)) scaleMaxInput.value = (Math.round(lo * 1.2 * 100) / 100);
                    }
                    commitScale();
                });
            }
        }

        renderPrefabProperties(memberKey, parentInput.value, propList, sp);


        parentInput.addEventListener('input', (e) => {
            const val = e.target.value.toLowerCase();
            dropdown.innerHTML = '';
            if (!val || !prefabIndex) { dropdown.style.display = 'none'; return; }

            const entries = Object.keys(prefabIndex.entries)
                .filter(k => k.includes(val))
                .slice(0, 15);

            entries.forEach(k => {
                const entry = prefabIndex.entries[k];
                const li = document.createElement('li');
                li.textContent = entry.name;
                li.addEventListener('click', () => {
                    parentInput.value = entry.name;
                    dropdown.style.display = 'none';
                    renderPrefabProperties(memberKey, entry.name, propList, sp);
                });
                dropdown.appendChild(li);
            });
            dropdown.style.display = entries.length ? 'block' : 'none';
        });

        tab.addEventListener('click', () => {
            tabsContainer.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            contentContainer.querySelectorAll('.prefab-panel').forEach(p => p.style.display = 'none');
            tab.classList.add('active');
            panel.style.display = 'block';
        });
    });
}

function renderPrefabProperties(memberKey, parentPrefabName, container, sp) {
    container.innerHTML = '';

    const hasOverrideObj = !!(sp.prefab_overrides && sp.prefab_overrides[memberKey]);
    if (!sp.prefab_overrides) sp.prefab_overrides = {};
    if (!sp.prefab_overrides[memberKey]) sp.prefab_overrides[memberKey] = { Properties: {} };
    const savedProps = sp.prefab_overrides[memberKey].Properties || {};

    ROOT_PROPERTIES_WHITELIST.forEach(propName => {
        const template = document.getElementById('tpl-property-row');
        const clone = template.content.cloneNode(true);
        const row = clone.querySelector('.property-row');

        const cbEnable = row.querySelector('.prop-enable');
        const lblName = row.querySelector('.prop-name');
        const valInput = row.querySelector('.prop-val');

        lblName.textContent = propName;

        let val;
        let isSaved = savedProps && savedProps[propName] !== undefined;

        if (isSaved) {
            const rawProp = savedProps[propName];
            val = (rawProp && typeof rawProp === 'object' && !Array.isArray(rawProp) && rawProp.Default !== undefined)
                  ? rawProp.Default
                  : rawProp;
            cbEnable.checked = true;
        } else if (hasOverrideObj) {
            val = getInheritedPropValue(parentPrefabName, propName);

            if (sp.source && sp.name && val) {
                const re = new RegExp(sp.source, 'gi');
                if (Array.isArray(val)) {
                    val = val.map(s => typeof s === 'string' ? s.replace(re, sp.name) : s);
                } else if (typeof val === 'string') {
                    val = val.replace(re, sp.name);
                }
            }
            cbEnable.checked = false;
        } else {
            val = getInheritedPropValue(parentPrefabName, propName);

            if (sp.source && sp.name && val) {
                const re = new RegExp(sp.source, 'gi');
                if (Array.isArray(val)) {
                    val = val.map(s => typeof s === 'string' ? s.replace(re, sp.name) : s);
                } else if (typeof val === 'string') {
                    val = val.replace(re, sp.name);
                }
            }

            const hasVal = (Array.isArray(val) ? val.length > 0 : (val !== "" && val !== null && val !== undefined));
            cbEnable.checked = hasVal;
        }


        let inheritedVal = val;
        let activeVal = cbEnable.checked ? val : "";

        if (propName === 'AssetPackages' || Array.isArray(inheritedVal)) {
            valInput.style.display = 'none';
            row.dataset.isArray = "true";

            const arrayContainer = document.createElement('div');
            arrayContainer.className = 'prop-array-container';
            arrayContainer.style.flex = '1';
            row.appendChild(arrayContainer);

            const getArrayValues = () => {
                return Array.from(arrayContainer.querySelectorAll('.ap-value')).map(inp => inp.value.trim()).filter(v => v);
            };

            row.getArrayValues = getArrayValues;

            const renderArray = (arr) => {
                arrayContainer.innerHTML = '';
                arr.forEach((item) => {
                    const apTemplate = document.getElementById('tpl-asset-package-row');
                    const apClone = apTemplate.content.cloneNode(true);
                    const apRow = apClone.querySelector('.asset-package-row');
                    const inp = apRow.querySelector('.ap-value');
                    inp.value = item;

                    inp.addEventListener('input', () => {
                        if (inp.value.trim() !== "") cbEnable.checked = true;
                        savePrefabProperties(memberKey, container, sp);
                    });

                    apRow.querySelector('.btn-remove-ap').addEventListener('click', () => {
                        apRow.remove();
                        savePrefabProperties(memberKey, container, sp);
                    });

                    arrayContainer.appendChild(apClone);
                });

                const addBtn = document.createElement('button');
                addBtn.className = 'btn btn-small btn-secondary mt-10';
                addBtn.textContent = '+ Add Item';
                addBtn.style.marginBottom = '10px';
                addBtn.onclick = () => {
                    cbEnable.checked = true;
                    renderArray([...getArrayValues(), ""]);
                };
                arrayContainer.appendChild(addBtn);
            };

            let arr = [];
            if (cbEnable.checked) {
                arr = Array.isArray(val) ? val : (val ? String(val).split(',').map(s => s.trim()).filter(s => s) : []);
                if (arr.length === 0) arr = [""];
            }

            renderArray(arr);

        } else {
            valInput.value = cbEnable.checked ? (val !== undefined && val !== null ? val : "") : "";
            valInput.placeholder = inheritedVal ? `(Inherited: ${inheritedVal})` : "";
            valInput.addEventListener('input', () => {
                if (valInput.value.trim() !== "") cbEnable.checked = true;
                savePrefabProperties(memberKey, container, sp);
            });
        }

        cbEnable.addEventListener('change', () => {
            if (!cbEnable.checked) {
                valInput.value = "";
                if (row.dataset.isArray === "true") {
                    const arrContainer = row.querySelector('.prop-array-container');
                    if (arrContainer) {
                        const items = arrContainer.querySelectorAll('.asset-package-row');
                        items.forEach(it => it.remove());
                    }
                }
            } else if (!valInput.value && inheritedVal && !Array.isArray(inheritedVal)) {
                valInput.value = inheritedVal;
            }
            savePrefabProperties(memberKey, container, sp);
        });

        container.appendChild(clone);
    });
}


function savePrefabProperties(memberKey, container, sp) {
    if (!sp) return;
    if (!sp.prefab_overrides) sp.prefab_overrides = {};
    if (!sp.prefab_overrides[memberKey]) sp.prefab_overrides[memberKey] = { Properties: {} };

    const panel = container.classList.contains('prefab-panel') ? container : container.closest('.prefab-panel');
    if (panel) {
        const parentInput = panel.querySelector('.prefab-parent-input');
        if (parentInput && parentInput.value.trim()) {
            const pVal = parentInput.value.trim();
            sp.prefab_overrides[memberKey].Prefab = pVal;
            if (!sp.donor_prefabs) sp.donor_prefabs = {};
            sp.donor_prefabs[memberKey] = pVal;
        }
        const scaleMinInput = panel.querySelector('.prefab-scale-min-input');
        const scaleMaxInput = panel.querySelector('.prefab-scale-max-input');
        const varyBox = panel.querySelector('.prefab-scale-vary');
        if (scaleMinInput && scaleMaxInput
            && (scaleMinInput.value.trim() || scaleMaxInput.value.trim())) {
            writeScaleBand(sp, memberKey, scaleMinInput.value.trim(), scaleMaxInput.value.trim(),
                           varyBox ? varyBox.checked : false);
        }

    }


    const props = {};
    const rows = container.querySelectorAll('.property-row');
    rows.forEach(row => {
        const cbEnable = row.querySelector('.prop-enable');
        const lblName = row.querySelector('.prop-name');
        if (!cbEnable || !lblName) return;

        const name = lblName.textContent.trim();
        if (cbEnable.checked) {
            if (row.dataset.isArray === "true") {
                const arr = row.getArrayValues ? row.getArrayValues() : [];
                if (arr.length > 0) {
                    props[name] = { Default: arr };
                }
            } else {
                const valInput = row.querySelector('.prop-val');
                const valStr = valInput ? valInput.value.trim() : "";
                let val;
                if (valStr.includes(',') && name === 'AssetPackages') {
                    val = valStr.split(',').map(s => s.trim()).filter(s => s);
                } else if (valStr === "true") {
                    val = true;
                } else if (valStr === "false") {
                    val = false;
                } else if (valStr !== "" && !isNaN(valStr)) {
                    val = parseFloat(valStr);
                } else {
                    val = valStr;
                }
                if (val !== "" && val !== null && val !== undefined) {
                    props[name] = { Default: val };
                }
            }
        }
    });


    sp.prefab_overrides[memberKey].Properties = props;
}

function saveAllPrefabProperties() {
    if (currentSpeciesIndex < 0) return;
    const sp = modProject.species[currentSpeciesIndex];
    if (!sp) return;

    const contentContainer = document.getElementById('prefab-tab-content');
    if (!contentContainer) return;

    const panels = contentContainer.querySelectorAll('.prefab-panel');
    panels.forEach(panel => {
        const memberKey = panel.dataset.memberKey;
        if (memberKey) {
            savePrefabProperties(memberKey, panel, sp);
        }
    });
}

function rebuildPrefabIndexUI() {
    if (typeof logButtonClick === 'function') logButtonClick('btn-rebuild-prefab-index', 'Rebuild Prefab Index from Lua Dump');
    if (!backend || !backend.browse_and_rebuild_prefab_index) {
        alert("Backend method not available.");
        return;
    }
    backend.browse_and_rebuild_prefab_index((resStr) => {
        const res = JSON.parse(resStr);
        if (res.cancelled) return;
        if (!res.success) {
            backend.show_error(res.error || "Failed to rebuild prefab index.");
            return;
        }
        backend.show_info(`Successfully indexed ${res.count} prefabs from '${res.lua_file}'!`);
        backend.get_prefab_index((indexStr) => {
            try {
                prefabIndex = JSON.parse(indexStr);
                populatePrefabTabs();
            } catch (e) {
                console.error("Failed to reload prefab index", e);
            }
        });
    });
}

