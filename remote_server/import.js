/* The only request contains the explicit four-field projection. File stays local. */
(function(root){
  'use strict';
  function createController({parser,readFile,send,uuid,render}) {
    let generation=0, state={phase:'empty',payload:null,eventId:null,message:''};
    const update=next=>{state={...state,...next};render({...state});};
    function clear(){generation++;update({phase:'empty',payload:null,eventId:null,message:'Локальный выбор очищен.'});}
    async function select(file){
      if(state.phase==='sending') return;
      const epoch=++generation;
      update({phase:'reading',payload:null,eventId:null,message:'Проверяем файл на этом устройстве…'});
      if(!file){clear();return;}
      if(!Number.isSafeInteger(file.size)||file.size<1||file.size>parser.MAX_BYTES){update({phase:'error',message:'Файл пуст или больше 2 МиБ. Ничего не отправлено.'});return;}
      try {
        const text=await readFile(file);
        if(epoch!==generation)return;
        const payload=parser.decodeText(text);
        if(epoch!==generation)return;
        update({phase:'preview',payload,eventId:uuid(),message:'Проверь сводку. Она ещё не отправлена.'});
      } catch(_){if(epoch===generation)update({phase:'error',payload:null,eventId:null,message:'Файл не прошёл строгую проверку Belmont 1.1.3. Возможно, формат, числа или размер не поддерживаются. Ничего не отправлено.'});}
    }
    async function submit(){
      if(!['preview','retry'].includes(state.phase)||!state.payload)return;
      const epoch=generation, payload=state.payload, eventId=state.eventId;
      update({phase:'sending',message:'Передаём только показанную сводку…'});
      try{
        const response=await send(payload,eventId);
        if(epoch!==generation)return;
        if(response.status===401||response.status===403){update({phase:'blocked',payload:null,eventId:null,message:'Сеанс или разрешение недействительны. Вернись к игре, проверь доступ и выбери файл заново.'});return;}
        if(response.ok&&response.accepted===true)update({phase:'success',payload:null,eventId:null,message:'Сводка сохранена как ручной импорт. Это не автоматическая синхронизация.'});
        else if([400,409,413,422].includes(response.status))update({phase:'error',payload:null,eventId:null,message:'Сервер отклонил сводку. Проверь разрешение и выбери файл заново.'});
        else update({phase:'retry',message:'Не удалось подтвердить получение. Можно повторить отправку этой же сводки. Передаются только четыре значения и сведения о формате, не файл.'});
      }catch(_){if(epoch===generation)update({phase:'retry',message:'Связь прервалась. Можно повторить отправку той же сводки без создания дубликата.'});}
    }
    update(state); return {select,clear,submit,getState:()=>({...state})};
  }
  function mount(document){
    const panel=document.getElementById('manual-import'); if(!panel)return;
    const picker=document.getElementById('import-file'),confirm=document.getElementById('import-send'),cancel=document.getElementById('import-clear'),status=document.getElementById('import-status'),preview=document.getElementById('import-preview');
    if(!picker||!root.BelmontLocalParser||!root.crypto?.randomUUID||!root.TextDecoder||!root.fetch)return;
    const permitted=panel.dataset.permitted==='yes';
    const csrf=document.getElementById('import-csrf').value;
    const controller=createController({parser:root.BelmontLocalParser,uuid:()=>root.crypto.randomUUID(),
      readFile:async file=>new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(await file.arrayBuffer()),
      send:async(payload,eventId)=>{
        const response=await root.fetch('/v1/browser/observations',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf,event_id:eventId,appid:4231820,kind:'save_summary',payload})});
        let result={}; try{result=await response.json();}catch(_){}
        return {status:response.status,ok:response.ok,accepted:result.accepted===true};
      },render:state=>{
        picker.disabled=!permitted||state.phase==='sending'; confirm.disabled=!permitted||!['preview','retry'].includes(state.phase); cancel.disabled=state.phase==='sending';
        preview.hidden=!state.payload;status.textContent=state.message||'Выбери локальный файл. Отправка начнётся только после проверки и подтверждения.';
        for(const key of ['healthUpgradeFragmentCount','manaUpgradeFragmentCount','currentHealth','currentMana']){
          const cell=document.getElementById('preview-'+key);const scalar=state.payload?.player_scalars[key];cell.textContent=scalar?.status==='known'?String(scalar.value):'Неизвестно';
        }
        if(['empty','success','blocked','error'].includes(state.phase))picker.value='';
      }});
    picker.addEventListener('change',()=>controller.select(picker.files?.[0]));
    picker.addEventListener('cancel',()=>controller.clear());
    cancel.addEventListener('click',()=>controller.clear());
    confirm.addEventListener('click',()=>controller.submit());
    root.addEventListener('pagehide',()=>controller.clear());
    root.addEventListener('pageshow',()=>controller.clear());
    const unsupported=document.getElementById('import-unsupported');unsupported.hidden=true;
  }
  if(typeof module==='object'&&module.exports)module.exports={createController};
  else if(root.document)mount(root.document);
})(typeof globalThis!=='undefined'?globalThis:this);
