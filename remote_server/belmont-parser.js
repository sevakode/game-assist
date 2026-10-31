/* Strict local-only Belmont 1.1.3 parser. No network, storage or raw-data logging. */
(function (root) {
  'use strict';
  const MAX_BYTES = 2 * 1024 * 1024, MAX_DEPTH = 64, MAX_NODES = 500000;
  const NUMBER = Symbol('validated JSON number');
  class InvalidSave extends Error { constructor(code) { super(code); this.name = 'InvalidSave'; } }
  const fail = code => { throw new InvalidSave(code); };
  const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v) && !v[NUMBER];
  const own = (o,k) => Object.prototype.hasOwnProperty.call(o,k);
  function decimal(text) {
    const m = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(text);
    if (!m || (m[2].length + (m[3] || '').length) > 1000) fail('number_precision');
    let digits = (m[2] + (m[3] || '')).replace(/^0+/, '');
    if (!digits) return '0';
    let exponent = Number(m[4] || 0) - (m[3] || '').length;
    if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 10000) fail('number_precision');
    while (digits.endsWith('0')) { digits = digits.slice(0,-1); exponent++; }
    return m[1] + digits + 'e' + exponent;
  }
  function parseJSON(text, budget) {
    let p = 0;
    const space = () => { while (p < text.length && /[\x20\t\r\n]/.test(text[p])) p++; };
    function string() {
      const start = p++;
      let escaped = false;
      while (p < text.length) {
        const c = text[p++];
        if (!escaped && c === '"') {
          let value;
          try { value = JSON.parse(text.slice(start,p)); } catch (_) { fail('invalid_json'); }
          // Reject unpaired surrogates rather than silently replacing UTF-8 bytes.
          for (let i=0;i<value.length;i++) {
            const n=value.charCodeAt(i);
            if (n>=0xd800 && n<=0xdbff) { const next=value.charCodeAt(++i); if (!(next>=0xdc00 && next<=0xdfff)) fail('invalid_unicode'); }
            else if (n>=0xdc00 && n<=0xdfff) fail('invalid_unicode');
          }
          return value;
        }
        if (!escaped && c === '\\') escaped=true; else escaped=false;
      }
      fail('invalid_json');
    }
    function value(depth) {
      if (depth > MAX_DEPTH || --budget.nodes < 0) fail('complexity');
      space(); const c=text[p];
      if (c === '"') return string();
      if (c === '{') {
        p++; space(); const result=Object.create(null);
        if (text[p]==='}') { p++; return result; }
        for (;;) {
          space(); if(text[p]!=='"') fail('invalid_json'); const key=string();
          if(own(result,key)) fail('duplicate_key');
          space(); if(text[p++]!==':') fail('invalid_json'); result[key]=value(depth+1);
          space(); const end=text[p++]; if(end==='}') return result; if(end!==',') fail('invalid_json');
        }
      }
      if (c === '[') {
        p++; space(); const result=[];
        if(text[p]===']') { p++; return result; }
        for (;;) { result.push(value(depth+1)); space(); const end=text[p++]; if(end===']') return result; if(end!==',') fail('invalid_json'); }
      }
      for (const [literal,result] of [['true',true],['false',false],['null',null]]) {
        if(text.slice(p,p+literal.length)===literal) { p+=literal.length; return result; }
      }
      const number=/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(p));
      if(number) {
        p+=number[0].length;
        const exponent=/[eE]([+-]?\d+)$/.exec(number[0]);
        if(number[0].length>1000 || (exponent && Math.abs(Number(exponent[1]))>10000)) fail('complexity');
        const integer=!/[.eE]/.test(number[0]);
        // Preserve the numeric lexeme. Opaque world fields are never projected;
        // Python permits arbitrary-size integers and rounds finite JSON floats.
        // Reject float overflow globally, but apply exactness only to shared scalars.
        if(!integer && !Number.isFinite(Number(number[0]))) fail('nonfinite');
        return {[NUMBER]:true, lexeme:number[0], integer};
      }
      if (/^(?:NaN|-?Infinity)/.test(text.slice(p))) fail('nonfinite');
      fail('invalid_json');
    }
    const result=value(0); space(); if(p!==text.length) fail('invalid_json'); return result;
  }
  function parallel(v) {
    if(!isObject(v) || !Array.isArray(v.m_keys) || !Array.isArray(v.m_values) || v.m_keys.length!==v.m_values.length || v.m_keys.length>100000 || v.m_keys.some(k=>typeof k!=='string') || new Set(v.m_keys).size!==v.m_keys.length) fail('invalid_structure');
    return v.m_values;
  }
  function decodeText(text) {
    if(typeof text!=='string' || new TextEncoder().encode(text).length>MAX_BYTES) fail('too_large');
    const budget={nodes:MAX_NODES}; const data=parseJSON(text,budget);
    if(!isObject(data) || data.version!=='1.1.3') fail('unsupported_version');
    const player=own(data,'playerSave') ? data.playerSave : Object.create(null);
    if(!isObject(player)) fail('invalid_structure');
    const fields=['healthUpgradeFragmentCount','manaUpgradeFragmentCount','currentHealth','currentMana'];
    const scalars=Object.create(null);
    for(const key of fields) {
      if(!own(player,key)) scalars[key]={status:'missing',value:null};
      else if(player[key]===null) scalars[key]={status:'unknown',value:null};
      else {
        const n=player[key];
        if(!n || !n[NUMBER] || (key.endsWith('FragmentCount') && !n.integer)) fail('invalid_scalar');
        const value=Number(n.lexeme);
        if(!Number.isFinite(value) || value<0) fail('invalid_scalar');
        if(value>Number.MAX_SAFE_INTEGER || decimal(n.lexeme)!==decimal(String(value))) fail('number_precision');
        scalars[key]={status:'known',value};
      }
    }
    const hasWorld=own(data,'worldSaves'); let entities=0;
    if(hasWorld) for(const world of parallel(data.worldSaves)) {
      if(!isObject(world) || !own(world,'savableEntityStates')) fail('invalid_structure');
      for(const encoded of parallel(world.savableEntityStates)) {
        if(++entities>100000 || typeof encoded!=='string' || new TextEncoder().encode(encoded).length>256*1024) fail('invalid_structure');
        try { parseJSON(encoded,budget); }
        catch(error) { if(!(error instanceof InvalidSave) || error.message!=='invalid_json' || /^[\s]*[\[{]/.test(encoded)) throw error; }
      }
    }
    return {format_version:'1.1.3',player_scalars:scalars,semantic_caveats:[
      'Fragment counters are raw values; cumulative versus remainder semantics are unknown.',
      'currentHealth and currentMana are current values, not maxima.',
      'No HP/mana pickup classification, collected-state semantics, or location mapping is established.'
    ],decoder_coverage:{player_scalars:'four_raw_fields_only',world_structure:hasWorld?'validated_structural_only':'missing',collectible_semantics:'unknown',location_mapping:'unknown'}};
  }
  const api={MAX_BYTES,decodeText,InvalidSave};
  if(typeof module==='object' && module.exports) module.exports=api;
  else root.BelmontLocalParser=api;
})(typeof globalThis!=='undefined'?globalThis:this);
