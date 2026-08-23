// Main Application Entry Point & WebChannel Initializer

function logButtonClick(btnId, actionName) {
    if (window.backend && backend.log_activity) {
        backend.log_activity("INFO", "BUTTON_CLICK", `[${btnId || 'BUTTON'}] ${actionName}`);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    new QWebChannel(qt.webChannelTransport, (channel) => {
        window.backend = channel.objects.backend;
        initApp();
    });
});


function initApp() {
    // Tab Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));

            item.classList.add('active');
            const pageId = item.dataset.page;
            const targetPage = document.getElementById(pageId);
            if (targetPage) targetPage.classList.add('active');

            if (pageId === 'page-editor' || pageId === 'page-expeditions') {
                refreshBuiltMods();
            } else if (pageId === 'page-logs') {
                setupLogsPage();
            } else if (pageId === 'page-data') {
                if (typeof renderDataOverridesPage === 'function') {
                    renderDataOverridesPage();
                }
            }

            // Scale bands are edited on the Prefab Builder page, so refresh the
            // read-only summary whenever the user navigates back.
            if (typeof renderFamilyScaleSummary === 'function') {
                renderFamilyScaleSummary();
            }

        });
    });

    // Roster wiring
    document.getElementById('btn-add-species').addEventListener('click', addSpeciesToRoster);

    // Mod Name syncing
    const modNameInput = document.getElementById('mod-name');
    modNameInput.addEventListener('input', () => {
        modProject.mod_name = modNameInput.value.trim();
    });

    // Active Species Input Syncing
    ['new-name', 'sp-name', 'new-species-id', 'new-genetic-id', 'sp-display-name', 'sp-genus', 'sp-scale', 'sp-variants', 'sp-patterns', 'sp-film-variants', 'sp-asset-category', 'chk-scaling'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', saveActiveSpeciesFromUI);
            el.addEventListener('change', saveActiveSpeciesFromUI);
        }
    });

    const scalingCheckbox = document.getElementById('chk-scaling');
    if (scalingCheckbox) {
        scalingCheckbox.addEventListener('change', () => {
            const group = document.getElementById('scale-value-group');
            if (group) group.style.display = scalingCheckbox.checked ? '' : 'none';
        });
    }


    if (typeof setupDataOverridesPage === 'function') {
        setupDataOverridesPage();
    }


    // Fetch species list for donor search
    backend.get_species_list((resStr) => {
        const res = JSON.parse(resStr);
        if (res.species) {
            availableSpecies = res.species;
            setupDonorSearch();
        }
    });

    // Fetch Prefab Index
    backend.get_prefab_index((indexStr) => {
        try {
            prefabIndex = JSON.parse(indexStr);
            populatePrefabTabs();
        } catch (e) {
            console.error("Failed to parse prefab_index.json", e);
        }
    });

    // Wire Prefab Loader & Rebuild buttons
    const btnRebuildIndex = document.getElementById('btn-rebuild-prefab-index');
    if (btnRebuildIndex) {
        btnRebuildIndex.addEventListener('click', rebuildPrefabIndexUI);
    }

    const btnLoadDonorPrefabs = document.getElementById('btn-load-donor-prefabs');

    if (btnLoadDonorPrefabs) {
        btnLoadDonorPrefabs.addEventListener('click', () => {
            if (currentSpeciesIndex < 0 || !modProject.species[currentSpeciesIndex]) {
                backend.show_error("Please select a species first.");
                return;
            }
            const sp = modProject.species[currentSpeciesIndex];
            if (!sp.source) {
                backend.show_error("Please select a Donor Species first.");
                return;
            }
            delete sp.prefab_overrides;
            backend.scan_donor(sp.source, (resStr) => {
                const res = JSON.parse(resStr);
                if (res.success && res.data) {
                    renderDonorSummary(res.data);
                    if (!sp.prefab_overrides) sp.prefab_overrides = {};

                    const memberMap = { 0: "Female", 1: "Male", 2: "Juvenile" };
                    const members = res.data.members || [];
                    members.forEach((m, idx) => {
                        const memberKey = memberMap[idx] || (idx === 0 ? "Female" : idx === 1 ? "Male" : "Juvenile");
                        const donorPrefab = m[1] || m[0];

                        if (!sp.prefab_overrides[memberKey]) sp.prefab_overrides[memberKey] = { Properties: {} };
                        sp.prefab_overrides[memberKey].Prefab = donorPrefab;

                        ROOT_PROPERTIES_WHITELIST.forEach(propName => {
                            let inheritedVal = getInheritedPropValue(donorPrefab, propName);
                            if (sp.source && sp.name && inheritedVal) {
                                const re = new RegExp(sp.source, 'gi');
                                if (Array.isArray(inheritedVal)) {
                                    inheritedVal = inheritedVal.map(s => typeof s === 'string' ? s.replace(re, sp.name) : s);
                                } else if (typeof inheritedVal === 'string') {
                                    inheritedVal = inheritedVal.replace(re, sp.name);
                                }
                            }
                            if (inheritedVal !== "" && inheritedVal !== null && inheritedVal !== undefined) {
                                sp.prefab_overrides[memberKey].Properties[propName] = { Default: inheritedVal };
                            }
                        });
                    });

                    populatePrefabTabs();
                    backend.show_info(`Re-loaded base game donor prefabs & defaults for '${sp.source}'!`);
                } else {
                    backend.show_error(res.error || "Failed to scan donor species.");
                }
            });
        });
    }


    const btnLoadModPrefabs = document.getElementById('btn-load-mod-prefabs');
    if (btnLoadModPrefabs) {
        btnLoadModPrefabs.addEventListener('click', () => {
            if (!modProject.mod_name) {
                backend.show_error("Please enter a Mod Project Name.");
                return;
            }
            if (currentSpeciesIndex < 0 || !modProject.species[currentSpeciesIndex]) {
                backend.show_error("Please select a species first.");
                return;
            }
            const sp = modProject.species[currentSpeciesIndex];
            backend.load_generated_mod_prefabs(modProject.mod_name, (resStr) => {
                const res = JSON.parse(resStr);
                if (res.success && res.family) {
                    if (!sp.prefab_overrides) sp.prefab_overrides = {};
                    const spName = (sp.name || "").trim();

                    res.family.forEach(member => {
                        let memberKey = "";
                        const mName = member.Name || "";

                        if (spName && (mName.toLowerCase() === spName.toLowerCase() || mName.toLowerCase() === (spName + "_female").toLowerCase())) {
                            memberKey = "Female";
                        } else if (spName && mName.toLowerCase().startsWith(spName.toLowerCase() + "_")) {
                            const suffix = mName.substring(spName.length + 1);
                            const sufLower = suffix.toLowerCase();
                            if (sufLower === "male") memberKey = "Male";
                            else if (sufLower === "juvenile") memberKey = "Juvenile";
                            else memberKey = suffix;
                        } else {
                            const lower = mName.toLowerCase();
                            if (lower.endsWith("_female") || lower === "female") memberKey = "Female";
                            else if (lower.endsWith("_male") || lower === "male") memberKey = "Male";
                            else if (lower.endsWith("_juvenile") || lower === "juvenile") memberKey = "Juvenile";
                        }

                        if (memberKey) {
                            sp.prefab_overrides[memberKey] = {
                                Prefab: member.Prefab,
                                Properties: member.Props || {}
                            };
                        }
                    });
                    populatePrefabTabs();
                    backend.show_info(`Loaded existing generated prefabs for '${modProject.mod_name}'!`);
                } else {
                    backend.show_error(res.error || "No generated mod prefabs found.");
                }
            });

        });
    }

    // Save / Load Project JSON
    document.getElementById('btn-save-project').addEventListener('click', () => {
        saveAllPrefabProperties();
        modProject.icons = currentIcons;
        if (!modProject.config) modProject.config = {};
        modProject.config.icons = currentIcons;
        backend.save_project(JSON.stringify(modProject, null, 2), (res) => { });
    });

    document.getElementById('btn-load-project').addEventListener('click', () => {
        backend.load_project((resStr) => {
            let res = JSON.parse(resStr);
            if (res.success && res.data) {
                try {
                    let loadedProject = JSON.parse(res.data);
                    modProject = loadedProject;

                    if (modProject.icons && Array.isArray(modProject.icons)) {
                        currentIcons = modProject.icons;
                    } else if (modProject.config && modProject.config.icons && Array.isArray(modProject.config.icons)) {
                        currentIcons = modProject.config.icons;
                    } else {
                        currentIcons = [];
                    }

                    if (modProject.species && Array.isArray(modProject.species)) {
                        modProject.species.forEach(sp => {
                            if (typeof sp.cosmetics === 'number') {
                                const val = sp.cosmetics;
                                sp.cosmetics = { variants: val, patterns: val, film_variants: false };
                            } else if (!sp.cosmetics) {
                                sp.cosmetics = { variants: 1, patterns: 1, film_variants: false };
                            }
                            if (sp.prefab_overrides) {
                                if (sp.prefab_overrides.Adult && !sp.prefab_overrides.Female) {
                                    sp.prefab_overrides.Female = sp.prefab_overrides.Adult;
                                }
                            }
                        });
                    } else {
                        modProject.species = [];
                    }

                    document.getElementById('mod-name').value = modProject.mod_name || "";

                    const defIconsBox = document.getElementById('chk-default-icons');
                    if (defIconsBox) defIconsBox.checked = modProject.default_icons === true;

                    updateRosterUI();

                    if (modProject.species.length > 0) {
                        selectSpeciesFromRoster(0);
                    } else {
                        currentSpeciesIndex = -1;
                        clearActiveSpeciesUI();
                    }

                    if (modProject.mod_name) {
                        // The project JSON is authoritative. Auto-scanning the
                        // previously generated folder resurrected stale icon
                        // packages after a user had deliberately removed every
                        // icon, turning the feature back on during project load.
                        renderIconList();
                        syncAssetPackagesFromMod(modProject.mod_name);
                    } else {
                        renderIconList();
                        renderAssetPackages();
                    }

                    backend.show_info(`Project '${modProject.mod_name || "Mod"}' loaded successfully!`);
                    backend.log_activity("INFO", "PROJECT", `Loaded project JSON '${modProject.mod_name || "Mod"}' containing ${modProject.species.length} species.`);
                } catch (err) {
                    backend.show_error("Failed to parse project JSON: " + err.message);
                }
            } else if (!res.cancelled) {
                backend.show_error(res.error || "Failed to load project file.");
            }
        });
    });


    // Asset Packages & Icons Buttons
    const btnAddCustomAp = document.getElementById('btn-add-custom-assetpkg') || document.getElementById('btn-add-asset-package');
    if (btnAddCustomAp) {
        btnAddCustomAp.addEventListener('click', () => {
            const nameInp = document.getElementById('txt-custom-ap-name');
            const pathInp = document.getElementById('txt-custom-ap-path');

            const name = nameInp ? nameInp.value.trim() : "";
            const path = pathInp ? pathInp.value.trim() : "";

            if (!modProject.config) modProject.config = {};
            if (!modProject.config.asset_packages) modProject.config.asset_packages = {};

            const finalName = name || ("CustomPackage_" + (Object.keys(modProject.config.asset_packages).length + 1));
            const finalPath = path || `ovldata\\${modProject.mod_name || 'MyMod'}\\Land\\${finalName}\\Female\\${finalName}`;

            modProject.config.asset_packages[finalName] = finalPath;

            if (nameInp) nameInp.value = "";
            if (pathInp) pathInp.value = "";

            renderAssetPackages();
        });
    }

    const btnAddCatAp = document.getElementById('btn-add-category-assetpkgs');
    if (btnAddCatAp) {
        btnAddCatAp.addEventListener('click', () => {
            const catSelect = document.getElementById('asset-category');
            const category = catSelect ? catSelect.value : "";
            if (!category) {
                backend.show_error("Please select a category first.");
                return;
            }

            const sp = (currentSpeciesIndex >= 0 && modProject.species[currentSpeciesIndex]) ? modProject.species[currentSpeciesIndex] : null;
            const spName = sp && sp.name ? sp.name : "Species";
            const modName = modProject.mod_name || "MyMod";

            if (!modProject.config) modProject.config = {};
            if (!modProject.config.asset_packages) modProject.config.asset_packages = {};

            const pkgs = modProject.config.asset_packages;

            const femaleKey = spName;
            const maleKey = `${spName}_Male`;
            const juvKey = `${spName}_Juvenile`;

            pkgs[femaleKey] = `ovldata\\${modName}\\Dinosaurs\\${category}\\${spName}\\Female\\${spName}`;
            pkgs[maleKey] = `ovldata\\${modName}\\Dinosaurs\\${category}\\${spName}\\Male\\${maleKey}`;
            pkgs[juvKey] = `ovldata\\${modName}\\Dinosaurs\\${category}\\${spName}\\Juvenile\\${juvKey}`;

            if (sp) {
                sp.asset_category = category;
                if (!sp.asset_packages) sp.asset_packages = {};
                sp.asset_packages[femaleKey] = pkgs[femaleKey];
                sp.asset_packages[maleKey] = pkgs[maleKey];
                sp.asset_packages[juvKey] = pkgs[juvKey];
            }

            renderAssetPackages();
            backend.show_info(`Added 3 ${category} Asset Packages for '${spName}'!`);
        });
    }

    const categorySelect = document.getElementById('asset-category');
    if (categorySelect) {
        categorySelect.addEventListener('change', () => {
            if (currentSpeciesIndex >= 0 && modProject.species[currentSpeciesIndex]) {
                const sp = modProject.species[currentSpeciesIndex];
                sp.asset_category = categorySelect.value;
                setElValue('sp-asset-category', sp.asset_category);

                const preview = document.getElementById('asset-path-preview');
                if (preview) {
                    const modName = modProject.mod_name || "MyMod";
                    const spName = sp.name || "Species";
                    const cat = sp.asset_category ? sp.asset_category + "\\" : "";
                    preview.textContent = sp.asset_category ? `ovldata\\${modName}\\Dinosaurs\\${cat}${spName}\\Female\\${spName}` : '—';
                }
            }
        });
    }


    const btnRefAp = document.getElementById('btn-refresh-asset-paths');
    if (btnRefAp) btnRefAp.addEventListener('click', () => {
        if (modProject.mod_name) syncAssetPackagesFromMod(modProject.mod_name);
    });

    const btnAddIcon = document.getElementById('btn-add-icon');
    if (btnAddIcon) btnAddIcon.addEventListener('click', addIconRow);

    const btnSaveIcons = document.getElementById('btn-save-icons-direct');
    if (btnSaveIcons) btnSaveIcons.addEventListener('click', saveIconsDirect);

    const btnRefIcons = document.getElementById('btn-refresh-icon-paths');
    if (btnRefIcons) btnRefIcons.addEventListener('click', () => {
        if (modProject.mod_name) syncIconsFromMod(modProject.mod_name);
    });

    // Build Buttons
    const btnBuild = document.getElementById('btn-generate') || document.getElementById('btn-build-mod');
    if (btnBuild) {
        btnBuild.addEventListener('click', () => {
            logButtonClick(btnBuild.id, "Clicked Generate Mod Project");
            generateProject();
        });
    }

    const btnUpdate = document.getElementById('btn-update-existing') || document.getElementById('btn-update-mod');
    if (btnUpdate) {
        btnUpdate.addEventListener('click', () => {
            logButtonClick(btnUpdate.id, "Clicked Update Existing Mod Files");
            updateExistingProject();
        });
    }




    // Setup Post-Build pages
    setupEditorPage();
    setupExpeditionsPage();
    setupLogsPage();

    // Start with one empty species
    addSpeciesToRoster();
}

function setupDonorSearch() {
    const input = document.getElementById('donor-search');
    const dropdown = document.getElementById('donor-dropdown');

    input.addEventListener('input', (e) => {
        const val = e.target.value.toLowerCase();
        dropdown.innerHTML = '';
        if (!val) { dropdown.style.display = 'none'; return; }

        const matches = availableSpecies.filter(s => s.Name.toLowerCase().includes(val)).slice(0, 10);
        matches.forEach(s => {
            const li = document.createElement('li');
            li.textContent = s.Name;
            li.addEventListener('click', () => {
                input.value = s.Name;
                dropdown.style.display = 'none';
                if (currentSpeciesIndex >= 0) {
                    const sp = modProject.species[currentSpeciesIndex];
                    sp.source = s.Name;
                    if (!sp.name) sp.name = "My" + s.Name;
                    if (!sp.display_name) sp.display_name = s.Name;
                    loadSpeciesIntoUI(sp);
                    updateRosterUI();
                }
            });
            dropdown.appendChild(li);
        });
        dropdown.style.display = matches.length ? 'block' : 'none';
    });
}

function generateProject() {
    if (!modProject.mod_name) {
        backend.show_error("Please enter a Mod Project Name.");
        return;
    }

    if (modProject.species.length === 0) {
        backend.show_error("Please add at least one species to the project.");
        return;
    }

    saveAllPrefabProperties();

    for (let i = 0; i < modProject.species.length; i++) {
        if (!modProject.species[i].source || !modProject.species[i].name) {
            backend.show_error(`Species #${i + 1} requires both a Donor Species and a Species Name.`);
            return;
        }
    }

    modProject.icons = currentIcons;
    if (!modProject.config) modProject.config = {};
    modProject.config.icons = currentIcons;

    // Mod-level, so it rides on the payload root rather than a species object
    // (the §5a-2 trap: a setting written only onto a species is ignored).
    const defIcons = document.getElementById('chk-default-icons');
    modProject.default_icons = defIcons ? defIcons.checked : false;

    const jsonStr = JSON.stringify(modProject);
    backend.generate(jsonStr, (resStr) => {
        try {
            const res = JSON.parse(resStr);
            const resCard = document.getElementById('build-results-card');
            const resBox = document.getElementById('build-results-content');
            if (resCard) resCard.style.display = 'block';

            if (res.success) {
                let outText = `=== MOD GENERATED SUCCESSFULLY ===\n\n`;
                outText += `Mod Name: ${modProject.mod_name}\n`;
                outText += `Generated Files:\n`;
                for (let k in res.paths) {
                    outText += ` - ${k}: ${res.paths[k]}\n`;
                }

                if (res.report && res.report.warnings && res.report.warnings.length) {
                    outText += `\nWarnings:\n`;
                    res.report.warnings.forEach(w => outText += ` ⚠️ ${w}\n`);
                }

                if (resBox) resBox.textContent = outText;
                backend.show_info(`Mod '${modProject.mod_name}' generated successfully!`);
                backend.log_activity("INFO", "BUILD", `Successfully generated mod '${modProject.mod_name}'.`);
            } else {
                if (resBox) resBox.textContent = `=== GENERATION FAILED ===\n\nError: ${res.error || "Unknown error"}`;
                backend.show_error(res.error || "Generation failed.");
                backend.log_activity("ERROR", "BUILD", `Failed to generate mod '${modProject.mod_name}': ${res.error}`);
            }
        } catch (err) {
            backend.show_error("Failed to parse generation response: " + err.message);
        }
    });
}

function updateExistingProject() {
    if (!modProject.mod_name) {
        backend.show_error("Please enter a Mod Project Name.");
        return;
    }

    if (modProject.species.length === 0) {
        backend.show_error("Please add at least one species to the project.");
        return;
    }

    saveAllPrefabProperties();

    modProject.icons = currentIcons;
    if (!modProject.config) modProject.config = {};
    modProject.config.icons = currentIcons;

    // Mod-level, so it rides on the payload root rather than a species object
    // (the §5a-2 trap: a setting written only onto a species is ignored).
    const defIcons = document.getElementById('chk-default-icons');
    modProject.default_icons = defIcons ? defIcons.checked : false;

    const jsonStr = JSON.stringify(modProject);
    backend.generate(jsonStr, (resStr) => {
        try {
            const res = JSON.parse(resStr);
            const card = document.getElementById('build-results-card');
            const content = document.getElementById('build-results-content');
            if (card) card.style.display = 'block';

            if (res.success) {
                renderAssetPackages();
                renderIconList();
                if (content) {
                    content.textContent = `Updated mod files for '${modProject.mod_name}' successfully!`;
                }
                backend.show_info(`Updated existing files for '${modProject.mod_name}'!`);
                backend.log_activity("INFO", "BUILD", `Successfully updated existing files for mod '${modProject.mod_name}'.`);
            } else {
                if (content) content.textContent = `=== UPDATE FAILED ===\n\nError: ${res.error || "Unknown error"}`;
                backend.show_error(res.error || "Update failed.");
                backend.log_activity("ERROR", "BUILD", `Failed to update mod '${modProject.mod_name}': ${res.error}`);
            }
        } catch (e) {
            backend.show_error("Failed to parse update response: " + e.message);
        }
    });
}
