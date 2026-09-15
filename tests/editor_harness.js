'use strict';

const assert = require('assert');
const editor = require('../species_gen_ui/js/cosmetics_expeditions.js');

function element(extra = {}) {
    return Object.assign({
        value: '', disabled: false, innerHTML: '', style: {},
        addEventListener() {},
        querySelectorAll() { return []; },
    }, extra);
}

const elements = {
    'btn-editor-load': element(),
    'btn-editor-save': element(),
    'btn-editor-addrow': element(),
    'editor-mod': element({value: 'A.fdb'}),
    'editor-table': element({value: 'Species'}),
    'editor-grid': element(),
    'editor-problems': element({appendChild() {}}),
};

global.document = {
    getElementById(id) { return elements[id] || null; },
    createElement() { return element(); },
    addEventListener() {},
    removeEventListener() {},
};
global.alert = () => {};
let saved = null;
const pendingLoads = [];
global.backend = {
    show_error(message) { throw new Error(message); },
    load_mod_table(path, table, callback) { pendingLoads.push({path, table, callback}); },
    save_mod_table(path, table, payload, callback) {
        saved = {path, table, payload: JSON.parse(payload)};
        callback(JSON.stringify({success: true, written: 1, problems: []}));
    },
    check_table_problems(path, callback) {
        callback(JSON.stringify({success: true, problems: []}));
    },
};

editor._setBuiltMods([
    {name: 'A', dino_fdb: 'A.fdb'},
    {name: 'B', dino_fdb: 'B.fdb'},
]);
editor.setupEditorPage();

// Save remains bound to the loaded database/table, not current selectors.
editor._setEditorTable({
    databasePath: 'A.fdb', tableName: 'Species', columns: ['Name'], rows: [['Alpha']]
});
elements['editor-mod'].value = 'B.fdb';
elements['editor-table'].value = 'SpeciesStats';
elements['btn-editor-save'].onclick();
assert.strictEqual(saved.path, 'A.fdb');
assert.strictEqual(saved.table, 'Species');

// Out-of-order load callbacks: only the newest request is retained.
elements['editor-mod'].value = 'A.fdb';
elements['editor-table'].value = 'Species';
elements['btn-editor-load'].onclick();
elements['editor-mod'].value = 'B.fdb';
elements['editor-table'].value = 'SpeciesStats';
elements['btn-editor-load'].onclick();
pendingLoads[1].callback(JSON.stringify({success: true, data: {columns: ['B'], rows: [['new']]}}));
pendingLoads[0].callback(JSON.stringify({success: true, data: {columns: ['A'], rows: [['old']]}}));
assert.strictEqual(editor._getEditorTable().databasePath, 'B.fdb');
assert.strictEqual(editor._getEditorTable().tableName, 'SpeciesStats');

// Current input values are captured before add/delete re-renders.
const row = value => ({querySelectorAll() { return [{value}]; }});
elements['editor-grid'].querySelectorAll = () => [row('edited'), row('remove-me')];
editor._setEditorTable({
    databasePath: 'A.fdb', tableName: 'Species', columns: ['Name'],
    rows: [['stale'], ['remove-me']]
});
elements['btn-editor-addrow'].onclick();
assert.deepStrictEqual(editor._getEditorTable().rows[0], ['edited']);
editor.deleteEditorRow('editor-grid', 1);
assert.deepStrictEqual(editor._getEditorTable().rows[0], ['edited']);

elements['exp-editor-grid'] = element({querySelectorAll() { return [row('exp-edited')]; }});
editor._setExpEditorTable({
    databasePath: 'E.fdb', tableName: 'Genomes', columns: ['GenomeID'], rows: [['stale']]
});
editor.deleteEditorRow('exp-editor-grid', 0);
assert.deepStrictEqual(editor._getExpEditorTable().rows, []);

// Stable path lookup survives list reordering, and HTML values are complete escaped.
editor._setBuiltMods([
    {name: 'Earlier', dino_fdb: 'Earlier.fdb'},
    {name: 'B', dino_fdb: 'B.fdb'},
]);
assert.strictEqual(editor.selectedMod('editor-mod').name, 'B');
assert.strictEqual(editor.escapeEditorHtml('&<\"\'>'), '&amp;&lt;&quot;&#39;&gt;');
assert.strictEqual(editor.selectHasOptionValue({options: [
    {value: 'D:\\Generated\\One\\Main\\one.fdb'},
]}, 'D:\\Generated\\One\\Main\\one.fdb'), true);
assert.strictEqual(editor.selectHasOptionValue({options: [
    {value: 'D:\\Generated\\One\\Main\\one.fdb'},
]}, 'D:\\Generated\\Two\\Main\\two.fdb'), false);

// Loading JSON can merge supported manual prefab edits back into project state.
global.modProject = {species: [
    {name: 'Rex', prefab_overrides: {}},
    {name: 'RexPrime', prefab_overrides: {}},
]};
const app = require('../species_gen_ui/app.js');
assert.strictEqual(app.mergeGeneratedPrefabsIntoProject([
    {Name: 'rexprime_male', Prefab: 'EditedDonor', Props: {ModelName: 'EditedModel'}},
]), 1);
assert.strictEqual(global.modProject.species[1].prefab_overrides.Male.Prefab, 'EditedDonor');

const categoryPackages = app.buildCategoryAssetPackages('MyMod', 'Land', {
    name: 'Dynamoterror', source: 'Dimetrodon',
    donor_prefabs: {Female: 'Dimetrodon_Female'},
});
assert.deepStrictEqual(categoryPackages, {
    Dynamoterror_Female: 'ovldata\\MyMod\\Dinosaurs\\Land\\Dynamoterror\\Female\\Dynamoterror_Female',
    Dynamoterror_Male: 'ovldata\\MyMod\\Dinosaurs\\Land\\Dynamoterror\\Male\\Dynamoterror_Male',
    Dynamoterror_Juvenile: 'ovldata\\MyMod\\Dinosaurs\\Land\\Dynamoterror\\Juvenile\\Dynamoterror_Juvenile',
});
assert.strictEqual(app.generatedFemalePackageName({
    name: 'Rex', source: 'IndominusRex',
}), 'Rex');
assert.strictEqual(app.projectMatchesGenerationSnapshot(
    JSON.stringify({mod_name: 'Original'}), {mod_name: 'Original'}), true);
assert.strictEqual(app.projectMatchesGenerationSnapshot(
    JSON.stringify({mod_name: 'Original'}), {mod_name: 'NewerEdit'}), false);
const enabledControl = {disabled: false};
const alreadyDisabledControl = {disabled: true};
document.querySelectorAll = () => [enabledControl, alreadyDisabledControl];
app.setGenerationControlsEnabled(false);
assert.strictEqual(enabledControl.disabled, true);
assert.strictEqual(alreadyDisabledControl.disabled, true);
app.setGenerationControlsEnabled(true);
assert.strictEqual(enabledControl.disabled, false);
assert.strictEqual(alreadyDisabledControl.disabled, true);

console.log('editor harness: ok');
