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
                if (typeof renderDataOverridesPage === 'function') {
                    renderDataOverridesPage(res.data.tables || res.data.donor_tables || []);
                }
            }
        });
    } else {
        const summary = document.getElementById('donor-summary');
        if (summary) summary.innerHTML = '<p class="hint">Search and select a donor species above...</p>';
        if (typeof renderDataOverridesPage === 'function') {
            renderDataOverridesPage([]);
        }
    }

    populatePrefabTabs();
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
    sp.scale = parseFloat(getElValue('sp-scale', 1.0)) || 1.0;
    sp.asset_category = getElValue('asset-category') || getElValue('sp-asset-category');

    if (!sp.cosmetics || typeof sp.cosmetics !== 'object') sp.cosmetics = {};
    sp.cosmetics.variants = parseInt(getElValue('sp-variants', 1)) || 1;
    sp.cosmetics.patterns = parseInt(getElValue('sp-patterns', 1)) || 1;
    sp.cosmetics.film_variants = !!getElValue('sp-film-variants', false);

    updateRosterUI();
    populatePrefabTabs();
}

function renderDonorSummary(data) {
    const summary = document.getElementById('donor-summary');
    if (!summary) return;

    let html = `<div class="donor-details">`;
    html += `<p><strong>Base Donor:</strong> ${data.donor_name} (ID: ${data.species_id}, Genetic ID: ${data.genetic_species_id})</p>`;
    html += `<p><strong>Family Members (${data.members ? data.members.length : 0}):</strong></p><ul>`;
    if (data.members) {
        data.members.forEach(m => {
            html += `<li><code>${m[0]}</code> &rarr; inherits <code>${m[1]}</code></li>`;
        });
    }
    html += `</ul>`;
    if (data.default_asset_packages && data.default_asset_packages.length) {
        html += `<p><strong>Default Asset Packages:</strong> ${data.default_asset_packages.join(', ')}</p>`;
    }
    html += `</div>`;
    summary.innerHTML = html;
}
