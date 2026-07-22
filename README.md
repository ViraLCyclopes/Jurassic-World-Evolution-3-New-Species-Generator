# 🦖 Jurassic World Evolution 3 - Species Generator Tool Suite

An advanced, GUI-driven species generator and database cloning toolsuite for Jurassic World Evolution 3 modding.

---

## 📋 Prerequisites & Installation

### 1. Install Python (3.8 or higher)
Ensure Python is installed on your system and added to your system `PATH`.

### 2. Install Required Modules
Open Command Prompt or PowerShell in this directory and run:

```bash
pip install -r requirements.txt
```

Alternatively, install the required packages manually:
```bash
pip install PyQt5 PyQtWebEngine
```

---

## 🚀 Quick Start Guide

### Launching the Application
- **Option 1 (Double-Click)**: Double-click `Run_Species_Generator.bat`.
- **Option 2 (Terminal)**: Run:
  ```bash
  python species_gen_ui.py
  ```

---

## 🧰 Features & Overview

1. **Species Roster Management (Page 1)**:
   - Add/remove multiple custom species to a mod project.
   - Configure Donor Species (`donor-search`), Species ID, Genetic Species ID, Genus, Display Name, Scale, Cosmetic Variant/Pattern counts, and Category Folders (`Land`, `Water`, `Air`, `Shared`).
   - Live roster sidebar updating.

2. **Data Cloning & Overrides (Page 2)**:
   - Select which FDB tables to clone (`Species`, `GeneticSpecies`, `SpeciesStats`, `Genome`, `SpeciesCosmeticSets`, etc.).
   - Define custom per-table value overrides.

3. **Prefab Builder & Render Scale Multipliers (Page 3)**:
   - Configure member prefabs (`Female`, `Male`, `Juvenile`).
   - Set individual Render Scale Multipliers per family member.
   - Edit root properties (`ModelName`, `AssetPackages`, `MaterialEffectsName`, etc.).
   - **⚡ Rebuild Prefab Index**: Generate an updated `prefab_index.json` from any new `JWE3_Prefabs.lua` game dump file.

4. **Cosmetics & Expeditions (Pages 4, 6 & 7)**:
   - View existing dig sites in built mods.
   - Add new dig sites (`SiteID`, `LocationID`, coordinates, capture vs dig types, fossil yields).
   - Edit & save database rows (`Genomes`, `Fossils`, `DigSites`, `Tasks`) in the Expeditions Table Editor with resizable table columns.

5. **Icon & Package Management (Page 5)**:
   - Manage PPUIPKG icon registrations (`icons.dinosaurSpecies.<Icon>`).
   - Add custom category asset package paths (`+ Add Category Asset Packages`).

6. **Review & Build / Update Existing (Page 8)**:
   - **Generate Mod Project**: Build clean new mod files (Lua scripts, FDB databases, Manifest XML, PPUIPKG icons).
   - **Update Existing Mod Files**: Instantly update properties and databases in an existing built mod without rebuilding from scratch.

7. **Activity & Session Debug Logs (Page 9)**:
   - View real-time user action logs, button clicks, API calls, and system errors.
   - Switch between session logs or clear logs on demand.

---

## ⚡ Rebuilding Prefab Index for New Game Updates
If a new game update or custom mod dump releases:
1. Open the **Prefab Builder** tab (Page 3).
2. Click **`⚡ Rebuild Prefab Index from Lua Dump`**.
3. Select your updated `JWE3_Prefabs.lua` file.
4. The tool will parse and generate a fresh, formatted `prefab_index.json` instantly!
