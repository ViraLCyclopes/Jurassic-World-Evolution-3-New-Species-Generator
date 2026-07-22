// Asset Packages and PPUIPKG Icons Management Handler

let currentIcons = [];

function renderAssetPackages() {
    const container = document.getElementById('asset-package-rows') || document.getElementById('asset-packages-list');
    if (!container) return;
    container.innerHTML = '';

    if (!modProject.config) modProject.config = {};
    if (!modProject.config.asset_packages) {
        modProject.config.asset_packages = modProject.asset_packages || {};
    }

    const packages = modProject.config.asset_packages;
    const pkgKeys = Object.keys(packages);

    if (pkgKeys.length === 0) {
        container.innerHTML = '<p class="hint">No custom asset packages registered.</p>';
        return;
    }

    pkgKeys.forEach(pkgName => {
        const template = document.getElementById('tpl-asset-package-item');
        let clone;
        if (template && template.content) {
            clone = template.content.cloneNode(true);
        } else {
            const div = document.createElement('div');
            div.innerHTML = `
                <div class="asset-package-item card mb-2 p-2" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); margin-bottom: 8px; padding: 8px; border-radius: 6px;">
                    <div class="form-row gap-2 align-items-center" style="display: flex; gap: 8px; align-items: center;">
                        <input type="text" class="ap-name form-control" placeholder="Package Name" style="flex: 1; padding: 6px 10px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.2); color: #fff;">
                        <input type="text" class="ap-path form-control" placeholder="Asset Path" style="flex: 2; padding: 6px 10px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.2); color: #fff;">
                        <span class="badge badge-secondary" style="padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; background: #4a5568; color: #fff;">Pending</span>
                        <button class="btn btn-small btn-secondary btn-remove-ap" style="padding: 4px 8px; cursor: pointer;">✕</button>
                    </div>
                </div>
            `;
            clone = div;
        }

        const nameInput = clone.querySelector('.ap-name');
        const pathInput = clone.querySelector('.ap-path');
        const badge = clone.querySelector('.badge');
        const removeBtn = clone.querySelector('.btn-remove-ap');

        nameInput.value = pkgName;
        pathInput.value = packages[pkgName];

        nameInput.addEventListener('input', () => {
            const oldVal = packages[pkgName];
            delete packages[pkgName];
            const newName = nameInput.value.trim();
            if (newName) packages[newName] = oldVal;
        });

        pathInput.addEventListener('input', () => {
            const key = nameInput.value.trim();
            if (key) packages[key] = pathInput.value.trim();
        });

        removeBtn.addEventListener('click', () => {
            delete packages[pkgName];
            renderAssetPackages();
        });

        container.appendChild(clone);
    });

    verifyAssetPackages();
}

function verifyAssetPackages() {
    if (!modProject.mod_name) return;
    if (!modProject.config || !modProject.config.asset_packages) return;

    backend.verify_asset_paths(modProject.mod_name, JSON.stringify(modProject.config.asset_packages), (resStr) => {
        const res = JSON.parse(resStr);
        if (!res.success || !res.results) return;

        const container = document.getElementById('asset-package-rows') || document.getElementById('asset-packages-list');
        if (!container) return;

        const items = container.querySelectorAll('.asset-package-item');
        items.forEach(item => {
            const nameInput = item.querySelector('.ap-name');
            if (!nameInput) return;
            const name = nameInput.value.trim();
            const badge = item.querySelector('.badge');

            if (res.results[name] && badge) {
                const info = res.results[name];
                if (info.exists) {
                    badge.className = 'badge badge-success';
                    badge.textContent = '✓ Verified';
                    badge.title = `Found on disk: ${info.target_folder}`;
                } else {
                    badge.className = 'badge badge-warning';
                    badge.textContent = '⚠️ Path Missing';
                    badge.title = `Expected folder not found: ${info.target_folder}`;
                }
            }
        });
    });
}

function addAssetPackageRow() {
    if (!modProject.config) modProject.config = {};
    if (!modProject.config.asset_packages) modProject.config.asset_packages = {};

    const newKey = "NewPackage_" + Object.keys(modProject.config.asset_packages).length;
    modProject.config.asset_packages[newKey] = `ovldata\\${modProject.mod_name || 'MyMod'}\\Land\\Species\\Species`;
    renderAssetPackages();
}

function syncAssetPackagesFromMod(modName) {
    if (!modName) return;
    backend.scan_mod_assetpkgs(modName, (resStr) => {
        const res = JSON.parse(resStr);
        if (res.success && res.packages) {
            if (!modProject.config) modProject.config = {};
            modProject.config.asset_packages = res.packages;
            renderAssetPackages();
        }
    });
}

// ----------------------------------------------------------- icons

function renderIconList() {
    const container = document.getElementById('icon-list') || document.getElementById('icons-list');
    if (!container) return;
    container.innerHTML = '';

    if (currentIcons.length === 0) {
        container.innerHTML = '<p class="hint">No UI icons registered.</p>';
        return;
    }

    currentIcons.forEach((icon, idx) => {
        const template = document.getElementById('tpl-icon-item');
        let clone;
        if (template && template.content) {
            clone = template.content.cloneNode(true);
        } else {
            const div = document.createElement('div');
            div.innerHTML = `
                <div class="icon-item card mb-2 p-2" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); margin-bottom: 8px; padding: 8px; border-radius: 6px;">
                    <div class="form-row gap-2 align-items-center" style="display: flex; gap: 8px; align-items: center;">
                        <input type="text" class="icon-id form-control" placeholder="Icon ID" style="flex: 1; padding: 6px 10px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.2); color: #fff;">
                        <input type="text" class="icon-path form-control" placeholder="Image Path (uigameface/...)" style="flex: 2; padding: 6px 10px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.2); color: #fff;">
                        <input type="text" class="icon-pkg form-control" placeholder="Asset Package" style="flex: 1; padding: 6px 10px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.2); color: #fff;">
                        <span class="badge badge-secondary" style="padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; background: #4a5568; color: #fff;">Pending</span>
                        <button class="btn btn-small btn-secondary btn-remove-icon" style="padding: 4px 8px; cursor: pointer;">✕</button>
                    </div>
                </div>
            `;
            clone = div;
        }

        const idInput = clone.querySelector('.icon-id');
        const pathInput = clone.querySelector('.icon-path');
        const pkgInput = clone.querySelector('.icon-pkg');
        const removeBtn = clone.querySelector('.btn-remove-icon');

        idInput.value = icon.id || icon.name || "";
        pathInput.value = icon.path || icon.image_name || "";
        pkgInput.value = icon.assetPackage || icon.asset_package || modProject.mod_name || "";

        idInput.addEventListener('input', () => { currentIcons[idx].id = idInput.value.trim(); });
        pathInput.addEventListener('input', () => { currentIcons[idx].path = pathInput.value.trim(); });
        pkgInput.addEventListener('input', () => { currentIcons[idx].assetPackage = pkgInput.value.trim(); });

        removeBtn.addEventListener('click', () => {
            currentIcons.splice(idx, 1);
            renderIconList();
        });

        container.appendChild(clone);
    });

    verifyIconsPpuipkg();
}

function verifyIconsPpuipkg() {
    if (!modProject.mod_name || currentIcons.length === 0) return;

    backend.verify_ppuipkg_paths(modProject.mod_name, JSON.stringify(currentIcons), (resStr) => {
        const res = JSON.parse(resStr);
        if (!res.success || !res.results) return;

        const container = document.getElementById('icon-list') || document.getElementById('icons-list');
        if (!container) return;

        const items = container.querySelectorAll('.icon-item');
        items.forEach(item => {
            const idInput = item.querySelector('.icon-id');
            if (!idInput) return;
            const iconId = idInput.value.trim();
            const badge = item.querySelector('.badge');

            if (res.results[iconId] && badge) {
                const info = res.results[iconId];
                if (info.exists) {
                    badge.className = 'badge badge-success';
                    badge.textContent = '✓ Verified';
                    badge.title = `PPUIPKG & folder exist:\n${info.ppuipkg_file}\n${info.image_folder}`;
                } else if (!info.file_exists) {
                    badge.className = 'badge badge-warning';
                    badge.textContent = '⚠️ PPUIPKG Missing';
                    badge.title = `Missing file: ${info.ppuipkg_file}`;
                } else {
                    badge.className = 'badge badge-warning';
                    badge.textContent = '⚠️ Image Dir Missing';
                    badge.title = `Missing directory: ${info.image_folder}`;
                }
            }
        });
    });
}

function addIconRow() {
    const defaultMod = modProject.mod_name || "MyMod";
    const defaultSpecies = (modProject.species[0] && modProject.species[0].name) ? modProject.species[0].name.toLowerCase() : "species";
    currentIcons.push({
        id: defaultSpecies + "_icon",
        path: `uigameface/img/dinosaurs/${defaultSpecies}.png`,
        assetPackage: defaultMod
    });
    renderIconList();
}

function syncIconsFromMod(modName) {
    if (!modName) return;
    backend.scan_mod_ppuipkg(modName, (resStr) => {
        const res = JSON.parse(resStr);
        if (res.success && res.icons) {
            currentIcons = res.icons;
            renderIconList();
        }
    });
}

function saveIconsDirect() {
    if (!modProject.mod_name) {
        backend.show_error("Please enter a Mod Project Name.");
        return;
    }
    backend.save_mod_ppuipkg(modProject.mod_name, JSON.stringify(currentIcons), (resStr) => {
        const res = JSON.parse(resStr);
        if (res.success) {
            backend.show_info(`Saved ${res.count} icons into userinterfaceimages${modProject.mod_name.toLowerCase()}.ppuipkg!`);
            verifyIconsPpuipkg();
        } else {
            backend.show_error(res.error || "Failed to save PPUIPKG XML.");
        }
    });
}
