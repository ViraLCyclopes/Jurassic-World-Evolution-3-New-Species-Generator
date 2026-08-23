// Roster State & Species Management Handler

let modProject = {
    mod_name: "",
    species: [],
    config: { asset_packages: {} }
};
let availableSpecies = [];
let prefabIndex = null;
let currentSpeciesIndex = -1;

function setElValue(id, val) {
    const el = document.getElementById(id);
    if (el) {
        if (el.type === 'checkbox') el.checked = !!val;
        else el.value = val !== undefined && val !== null ? val : "";
    }
}

function getElValue(id, defaultVal = "") {
    const el = document.getElementById(id);
    if (!el) return defaultVal;
    if (el.type === 'checkbox') return el.checked;
    return el.value.trim();
}

// The scaling card on the species page is a summary only - the bands themselves
// are edited per family member in the Prefab Builder, so there is one source of
// truth for them.
function renderFamilyScaleSummary(sp) {
    const box = document.getElementById('family-scales-inputs');
    if (!box) return;

    if (!sp && currentSpeciesIndex >= 0) sp = modProject.species[currentSpeciesIndex];
    box.innerHTML = '';
    if (!sp) return;

    const scales = sp.scales || {};
    const rows = ["Female", "Male", "Juvenile"].map(key => {
        const band = (typeof readScaleBand === 'function')
            ? readScaleBand(scales[key] !== undefined && scales[key] !== null ? scales[key] : sp.scale, 1.0)
            : { min: 1.0, max: 1.0 };
        const text = band.min === band.max
            ? `${band.min}× (fixed)`
            : `${band.min}× – ${band.max}× (varies)`;
        return `<div style="margin-right: 18px;"><strong>${key}:</strong> ${text}</div>`;
    });

    box.innerHTML = rows.join('')
        + '<p class="hint" style="width: 100%; margin: 6px 0 0 0;">Edit these on the Prefab Builder page.</p>';
}

function updateRosterUI() {
    const list = document.getElementById('species-roster') || document.getElementById('roster-list');
    if (!list) return;
    list.innerHTML = '';

    modProject.species.forEach((sp, idx) => {
        const item = document.createElement('li');
        item.className = `roster-item ${idx === currentSpeciesIndex ? 'active' : ''}`;
        item.style.cursor = 'pointer';
        item.style.padding = '8px 12px';
        item.style.marginBottom = '4px';
        item.style.borderRadius = '4px';
        item.style.display = 'flex';
        item.style.justifyContent = 'space-between';
        item.style.alignItems = 'center';
        item.style.background = idx === currentSpeciesIndex ? 'rgba(66, 153, 225, 0.25)' : 'rgba(255,255,255,0.03)';
        item.style.border = idx === currentSpeciesIndex ? '1px solid #4299e1' : '1px solid rgba(255,255,255,0.08)';

        const textSpan = document.createElement('span');
        textSpan.textContent = sp.name || sp.source || `Species #${idx + 1}`;
        textSpan.style.fontWeight = idx === currentSpeciesIndex ? 'bold' : 'normal';
        item.appendChild(textSpan);

        if (modProject.species.length > 1) {
            const delBtn = document.createElement('button');
            delBtn.className = 'btn-delete-species';
            delBtn.textContent = '✕';
            delBtn.style.background = 'transparent';
            delBtn.style.border = 'none';
            delBtn.style.color = '#ff6b6b';
            delBtn.style.cursor = 'pointer';
            delBtn.style.padding = '2px 6px';
            delBtn.onclick = (e) => {
                e.stopPropagation();
                removeSpeciesFromRoster(idx);
            };
            item.appendChild(delBtn);
        }

        item.onclick = () => selectSpeciesFromRoster(idx);
        list.appendChild(item);
    });

    const activeCard = document.getElementById('new-species-card') || document.getElementById('active-species-card');
    if (activeCard) {
        if (currentSpeciesIndex >= 0 && modProject.species[currentSpeciesIndex]) {
            activeCard.style.display = 'block';
            activeCard.style.opacity = '1';
            activeCard.style.pointerEvents = 'auto';
        } else {
            activeCard.style.opacity = '0.5';
            activeCard.style.pointerEvents = 'none';
        }
    }
}

function addSpeciesToRoster() {
    const newSp = {
        name: "",
        source: "",
        genus: "",
        display_name: "",
        scaling_enabled: false,
        scale: 1.0,
        asset_category: "",
        asset_packages: {},
        cosmetics: { variants: 1, patterns: 1, film_variants: false }
    };
    modProject.species.push(newSp);
    selectSpeciesFromRoster(modProject.species.length - 1);
}

function removeSpeciesFromRoster(index) {
    if (index < 0 || index >= modProject.species.length) return;
    modProject.species.splice(index, 1);
    if (currentSpeciesIndex >= modProject.species.length) {
        currentSpeciesIndex = modProject.species.length - 1;
    }
    if (currentSpeciesIndex >= 0) {
        selectSpeciesFromRoster(currentSpeciesIndex);
    } else {
        clearActiveSpeciesUI();
        updateRosterUI();
    }
}

function selectSpeciesFromRoster(index) {
    if (index < 0 || index >= modProject.species.length) return;
    currentSpeciesIndex = index;
    updateRosterUI();
    loadSpeciesIntoUI(modProject.species[currentSpeciesIndex]);
}

function clearActiveSpeciesUI() {
    setElValue('donor-search', '');
    setElValue('new-name', '');
    setElValue('sp-name', '');
    setElValue('new-species-id', '');
    setElValue('new-genetic-id', '');
    setElValue('sp-display-name', '');
    setElValue('sp-genus', '');
    setElValue('sp-scale', '1.0');
    setElValue('sp-variants', '1');
    setElValue('sp-patterns', '1');
    setElValue('sp-film-variants', false);
    setElValue('sp-custom-digsite', false);
    setElValue('sp-asset-category', '');

    setElValue('asset-category', '');

    const preview = document.getElementById('asset-path-preview');
    if (preview) preview.textContent = '—';

    const summary = document.getElementById('donor-summary');
    if (summary) summary.innerHTML = '<p class="hint">Search and select a donor species above...</p>';

    if (typeof renderDataOverridesPage === 'function') {
        renderDataOverridesPage([]);
    }
}

function loadSpeciesIntoUI(sp) {
    setElValue('donor-search', sp.source || '');
    setElValue('new-name', sp.name || '');
    setElValue('sp-name', sp.name || '');

    const speciesId = sp.species_id !== undefined && sp.species_id !== null ? sp.species_id : (sp.speciesId !== undefined ? sp.speciesId : '');
    const geneticId = sp.genetic_id !== undefined && sp.genetic_id !== null ? sp.genetic_id : (sp.genetic_species_id !== undefined ? sp.genetic_species_id : (sp.geneticId !== undefined ? sp.geneticId : ''));

    setElValue('new-species-id', speciesId);
    setElValue('new-genetic-id', geneticId);

    setElValue('sp-display-name', sp.display_name || '');
    setElValue('sp-genus', sp.genus || '');
    setElValue('sp-scale', (sp.scale !== undefined && sp.scale !== null) ? sp.scale : 1.0);
    setElValue('chk-scaling', sp.scaling_enabled === true);
    const scaleGroup = document.getElementById('scale-value-group');
    if (scaleGroup) scaleGroup.style.display = sp.scaling_enabled === true ? '' : 'none';
    renderFamilyScaleSummary(sp);

    let variants = 1, patterns = 1, film_variants = false;
    if (typeof sp.cosmetics === 'object' && sp.cosmetics !== null) {
        variants = sp.cosmetics.variants || 1;
        patterns = sp.cosmetics.patterns || 1;
        film_variants = !!sp.cosmetics.film_variants;
    } else if (typeof sp.cosmetics === 'number') {
        variants = sp.cosmetics;
        patterns = sp.cosmetics;
    }

    setElValue('sp-variants', variants);
    setElValue('sp-patterns', patterns);
    setElValue('sp-film-variants', film_variants);
    setElValue('sp-custom-digsite', !!sp.custom_digsite);

    const cat = sp.asset_category || '';

    setElValue('sp-asset-category', cat);
    setElValue('asset-category', cat);

    const preview = document.getElementById('asset-path-preview');
    if (preview) {
        if (cat && sp.name) {
            const modName = modProject.mod_name || "MyMod";
            preview.textContent = `ovldata\\${modName}\\Dinosaurs\\${cat}\\${sp.name}\\Female\\${sp.name}`;
        } else {
            preview.textContent = '—';
        }
    }

    const card = document.getElementById('new-species-card');
    if (card) {
        card.style.opacity = '1';
        card.style.pointerEvents = 'auto';
    }

    if (sp.source) {
        backend.scan_donor(sp.source, (resStr) => {
            const res = JSON.parse(resStr);
            if (res.success && res.data) {
                renderDonorSummary(res.data);

                const srcLower = sp.source ? sp.source.toLowerCase() : "";
                const baseSrc = srcLower.endsWith("_female") ? srcLower.slice(0, -7) : srcLower;

                const stdNames = new Set([
                    baseSrc,
                    baseSrc + "_female",
                    baseSrc + "_male",
                    baseSrc + "_juvenile"
                ]);

                const cleanFamily = (res.data.family || []).filter(famMember => {
                    const n = (famMember.Name || "").toLowerCase();
                    return stdNames.has(n);
                });

                sp.family_members = cleanFamily.length > 0 ? cleanFamily : (res.data.family || []);
                sp.donor_prefabs = {};

                sp.family_members.forEach(famMember => {
                    const nameLower = famMember.Name ? famMember.Name.toLowerCase() : "";
                    if (nameLower === baseSrc || nameLower === baseSrc + "_female") {
                        sp.donor_prefabs["Female"] = famMember.Prefab || famMember.Name;
                    } else if (nameLower === baseSrc + "_male") {
                        sp.donor_prefabs["Male"] = famMember.Prefab || famMember.Name;
                    } else if (nameLower === baseSrc + "_juvenile") {
                        sp.donor_prefabs["Juvenile"] = famMember.Prefab || famMember.Name;
                    }
                });


                if (typeof renderDataOverridesPage === 'function') {
                    renderDataOverridesPage(res.data.tables || res.data.donor_tables || []);
                }
                populatePrefabTabs();

            }
        });
    } else {
        const summary = document.getElementById('donor-summary');
        if (summary) summary.innerHTML = '<p class="hint">Search and select a donor species above...</p>';
        if (typeof renderDataOverridesPage === 'function') {
            renderDataOverridesPage([]);
        }
        populatePrefabTabs();
    }
}


function saveActiveSpeciesFromUI() {
    if (currentSpeciesIndex < 0 || !modProject.species[currentSpeciesIndex]) return;
    const sp = modProject.species[currentSpeciesIndex];

    const newNameVal = getElValue('new-name') || getElValue('sp-name');
    sp.name = newNameVal;

    const sidVal = getElValue('new-species-id');
    if (sidVal !== "") {
        const parsedSid = parseInt(sidVal, 10);
        if (!isNaN(parsedSid)) sp.species_id = parsedSid;
    } else {
        delete sp.species_id;
    }

    const gidVal = getElValue('new-genetic-id');
    if (gidVal !== "") {
        const parsedGid = parseInt(gidVal, 10);
        if (!isNaN(parsedGid)) sp.genetic_id = parsedGid;
    } else {
        delete sp.genetic_id;
    }

    sp.display_name = getElValue('sp-display-name') || sp.name;
    sp.genus = getElValue('sp-genus');
    sp.scaling_enabled = !!getElValue('chk-scaling', false);
    // Only overwrite the species-level fallback when that field is actually on
    // the page. There is no `sp-scale` input any more - bands are edited per
    // family member in the Prefab Builder - and blindly reading it flattened a
    // loaded project's band back to 1.0.
    if (document.getElementById('sp-scale')) {
        sp.scale = parseFloat(getElValue('sp-scale', 1.0)) || 1.0;
    } else if (sp.scale === undefined || sp.scale === null) {
        sp.scale = 1.0;
    }
    sp.asset_category = getElValue('asset-category') || getElValue('sp-asset-category');
    sp.custom_digsite = !!getElValue('sp-custom-digsite', false);

    if (!sp.cosmetics || typeof sp.cosmetics !== 'object') sp.cosmetics = {};

    sp.cosmetics.variants = parseInt(getElValue('sp-variants', 1)) || 1;
    sp.cosmetics.patterns = parseInt(getElValue('sp-patterns', 1)) || 1;
    sp.cosmetics.film_variants = !!getElValue('sp-film-variants', false);

    updateRosterUI();
    populatePrefabTabs();
}

function renderDonorSummary(data) {
    const donorInfoBox = document.getElementById('donor-info');
    if (!data) return;

    const sourceName = data.source ? data.source.name : (data.donor_name || '');
    const speciesId = data.source ? data.source.SpeciesID : (data.species_id || '');
    const geneticId = data.source ? data.source.GeneticSpeciesID : (data.genetic_species_id || '');
    const familyList = data.family || data.members || [];

    const lblDonorName = document.getElementById('lbl-donor-name');
    const lblFamilyCount = document.getElementById('lbl-donor-family-count');
    if (lblDonorName) lblDonorName.textContent = `${sourceName} (ID: ${speciesId}, Genetic ID: ${geneticId})`;
    if (lblFamilyCount) lblFamilyCount.textContent = `${familyList.length} member(s) scanned`;
    if (donorInfoBox) donorInfoBox.style.display = 'block';

    const sp = modProject.species[currentSpeciesIndex];
    if (!sp) return;

    const basePrefix = sourceName.endsWith('_Female') ? sourceName.slice(0, -7) : sourceName;
    const isBaseMember = (mName) => {
        if (!mName) return false;
        return mName === sourceName || mName === basePrefix || mName === `${basePrefix}_Female` || mName === `${basePrefix}_Male` || mName === `${basePrefix}_Juvenile`;
    };

    if (!sp.family_members || sp.family_members.length === 0) {
        sp.family_members = familyList.filter(m => {
            const name = typeof m === 'object' ? (m.Name || m.name) : m;
            return isBaseMember(name);
        }).map(m => {
            const name = typeof m === 'object' ? (m.Name || m.name) : m;
            const pref = typeof m === 'object' ? (m.Prefab || m.prefab || name) : name;
            return { Name: name, Prefab: pref, enabled: true };
        });

        if (sp.family_members.length === 0 && familyList.length > 0) {
            sp.family_members = familyList.map(m => {
                const name = typeof m === 'object' ? (m.Name || m.name) : m;
                const pref = typeof m === 'object' ? (m.Prefab || m.prefab || name) : name;
                return { Name: name, Prefab: pref, enabled: true };
            });
        }
    }

    renderFamilyMemberList(familyList);
}

function renderFamilyMemberList(allScannedFamily) {
    const container = document.getElementById('family-member-list');
    if (!container) return;
    container.innerHTML = '';

    const sp = modProject.species[currentSpeciesIndex];
    if (!sp || !sp.family_members) return;

    sp.family_members.forEach((member, idx) => {
        const row = document.createElement('div');
        row.className = 'family-member-row';
        row.style.cssText = 'display: flex; gap: 8px; align-items: center; background: rgba(0,0,0,0.2); padding: 6px 10px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.08);';

        const chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.checked = member.enabled !== false;
        chk.onchange = () => {
            member.enabled = chk.checked;
            populatePrefabTabs();
        };

        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.className = 'form-control';
        nameInput.value = member.Name || member.name || '';
        nameInput.placeholder = 'Member Name (e.g. Male)';
        nameInput.style.cssText = 'flex: 1; padding: 4px 8px; font-size: 0.85rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.3); color: #fff;';
        nameInput.oninput = () => {
            member.Name = nameInput.value.trim();
            populatePrefabTabs();
        };

        const prefSelect = document.createElement('select');
        prefSelect.className = 'form-control';
        prefSelect.style.cssText = 'flex: 1.5; padding: 4px 8px; font-size: 0.85rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); background: #1e2430; color: #fff; cursor: pointer;';

        const familyItems = allScannedFamily || [];
        familyItems.forEach(famMember => {
            const fName = typeof famMember === 'object' ? (famMember.Name || famMember.name) : famMember;
            const fPref = typeof famMember === 'object' ? (famMember.Prefab || famMember.prefab || fName) : fName;
            const opt = document.createElement('option');
            opt.value = fPref || fName;
            opt.textContent = `Donor: ${fName} (${fPref || fName})`;
            if ((member.Prefab || member.prefab) === opt.value || (member.Prefab || member.prefab) === fName) {
                opt.selected = true;
            }
            prefSelect.appendChild(opt);
        });

        prefSelect.onchange = () => {
            member.Prefab = prefSelect.value;
            if (!sp.donor_prefabs) sp.donor_prefabs = {};
            const key = member.Name.includes('_Male') || member.Name.endsWith('Male') ? 'Male' : (member.Name.includes('_Juvenile') || member.Name.endsWith('Juvenile') ? 'Juvenile' : 'Female');
            sp.donor_prefabs[key] = prefSelect.value;
            populatePrefabTabs();
        };

        const btnRemove = document.createElement('button');
        btnRemove.className = 'btn-icon';
        btnRemove.textContent = '✕';
        btnRemove.title = 'Remove Family Member';
        btnRemove.style.cssText = 'padding: 4px 8px; cursor: pointer; color: #fc8181; border: none; background: transparent; font-size: 1rem;';
        btnRemove.onclick = () => {
            sp.family_members.splice(idx, 1);
            renderFamilyMemberList(allScannedFamily);
            populatePrefabTabs();
        };

        row.appendChild(chk);
        row.appendChild(nameInput);
        row.appendChild(prefSelect);
        row.appendChild(btnRemove);
        container.appendChild(row);
    });

    const btnAdd = document.getElementById('btn-add-family-member');
    if (btnAdd) {
        btnAdd.onclick = () => {
            const count = sp.family_members.length + 1;
            sp.family_members.push({
                Name: `${sp.name}_Variant${count}`,
                Prefab: sp.source,
                enabled: true
            });
            renderFamilyMemberList(allScannedFamily);
            populatePrefabTabs();
        };
    }
}


