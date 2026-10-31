/* Dependency-free smoke and spoiler regression checks. Run: node web/tests/check-ui.cjs */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length, 'HTML IDs must be unique');
for (const match of source.matchAll(/\$\('([^']+)'\)/g)) assert(ids.includes(match[1]), `Missing HTML ID: ${match[1]}`);
assert(!source.includes('localStorage') && !source.includes('sessionStorage'), 'Tokens must stay in memory');
assert(!html.includes('https://'), 'No external assets');
class Element {
  constructor() { this.children = []; this.dataset = {}; this.classList = {add(){}, remove(){}, toggle(){}}; this.textContent = ''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.textContent = ''; this.children = items; }
  addEventListener() {}
  querySelector() { return new Element(); }
}
const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
const document = {
  getElementById: id => nodes[id], createElement: () => new Element(), createTextNode: text => ({textContent:text}),
  querySelector: () => new Element(), querySelectorAll: () => [],
};
const sandbox = {document, URLSearchParams, window:{location:{search:''}}, console};
vm.createContext(sandbox);
vm.runInContext(source.replace('  renderGames(); setBusy(false);', '  globalThis.ui = {renderAchievements, renderSaves, renderSettings, renderSaveSummary}; renderGames(); setBusy(false);'), sandbox);
const text = node => [node.textContent, ...node.children.map(text)].join(' ');
sandbox.ui.renderAchievements({observation:{data:{achievements:[
  {achieved:false,name:'SECRET FUTURE BOSS',apiname:'LOCKED_SECRET'},
  {achieved:true,name:'Already earned',apiname:'API_CODE',unlock_time:123456},
  {achieved:'true',name:'UNTRUSTED STRING'},
]}}});
assert.equal(nodes['achievement-value'].textContent, '1');
assert(text(nodes.achievements).includes('Already earned'));
assert(!/SECRET|LOCKED|UNTRUSTED|API_CODE/.test(text(nodes.achievements)));
assert(!text(nodes['achievement-value']).includes('/'), 'No hidden achievement denominator');
sandbox.ui.renderSaves({observation:{data:{file_count:1,total_bytes:1024,last_modified_ns:123456000000000,files:[{name:'secret-ending.sav',sha256:'secret-hash'}]}}});
assert.equal(nodes['save-value'].textContent, '1');
assert(!/secret-ending|secret-hash/.test(text(nodes.saves)), 'No save names or hashes');
sandbox.ui.renderSaves({observation:{data:{files:[{name:'legacy-spoiler.sav'}]}}});
assert.equal(nodes['save-value'].textContent, '—');
assert(!text(nodes.saves).includes('legacy-spoiler'));
sandbox.ui.renderSettings({assistance:'guided',spoiler_policy:'strict'});
assert.equal(nodes['assistance-fields'].dataset.loaded, 'yes');
assert(text(nodes['settings-status']).includes('Спойлеры запрещены'));
sandbox.ui.renderSettings({assistance:'minimal',spoiler_policy:'strict',neutral_reminders:false});
assert.equal(nodes['neutral-reminders'].checked, false, 'Reminder opt-out must load');
sandbox.ui.renderSaveSummary({observation:{data:{format_version:'1.1.3',player_scalars:{
  healthUpgradeFragmentCount:{status:'known',value:0},
  manaUpgradeFragmentCount:{status:'missing',value:null},
  currentHealth:{status:'unknown',value:null},
  currentMana:{status:'known',value:7},
  spoilerField:{status:'known',value:'FUTURE BOSS'},
},world_id:'SECRET LOCATION'}}});
const summaryText = text(nodes['save-summary']);
assert(summaryText.includes('0'), 'Known zero must be preserved');
assert(summaryText.includes('Поле отсутствует'), 'Missing must differ from zero');
assert(summaryText.includes('Неизвестно'), 'Unknown must differ from missing and zero');
assert(summaryText.includes('Текущее здоровье — не максимум'));
assert(!/FUTURE BOSS|SECRET LOCATION|spoilerField/.test(summaryText), 'Strict four-field allowlist');
sandbox.ui.renderSaveSummary({observation:{data:{format_version:'2.0',player_scalars:{currentMana:{status:'known',value:987654}}}}});
assert(!text(nodes['save-summary']).includes('987'), 'Unsupported version must fail closed');
sandbox.ui.renderSaveSummary({observation:null});
assert(text(nodes['save-summary']).includes('ещё не получена'));
console.log('PASS: HTML references, memory-only token, achieved-only records, no totals, aggregate-only saves, strict assistance UI, reminder opt-out, safe four-scalar summary and unsupported-version rejection.');
