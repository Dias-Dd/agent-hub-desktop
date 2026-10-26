"use strict";
(()=>{
 const H=window.HubDesktop,{$,text,bind}=H;
 let selected=null,loaded=null,pending=null,ticket=0,dirty=false;
 const controls=new Map();
 const status=s=>text('moduleConfigurationStatus',s);
 function setValue(field,value){const el=controls.get(field.name);if(!el)return;if(field.type==='boolean')el.checked=!!value;else el.value=Array.isArray(value)?value.join(', '):value??'';}
 function display(value){
  loaded=value;dirty=false;controls.clear();const root=$('moduleConfigurationFields');root.replaceChildren();
  const spec=value.schema; if(!spec)throw Error('模块未返回配置表单声明');
  text('moduleConfigurationTitle',spec.title||'接入配置');
  for(const field of spec.fields){
   const label=document.createElement('label');label.textContent=field.label||field.name;
   const el=document.createElement(field.type==='select'?'select':'input');el.id='moduleField-'+field.name;
   if(field.type==='select')for(const choice of field.options||[]){const option=document.createElement('option');option.value=choice.value;option.textContent=choice.label;el.append(option);}
   else{el.type=({secret:'password',url:'url',integer:'number',boolean:'checkbox'})[field.type]||'text';el.autocomplete=field.type==='secret'?'new-password':'off';if(field.min!==undefined)el.min=field.min;if(field.max!==undefined)el.max=field.max;}
   el.placeholder=field.placeholder||'';if(field.max_length)el.maxLength=field.max_length;
   label.append(el);if(field.help){const help=document.createElement('small');help.textContent=field.help;label.append(help);}root.append(label);controls.set(field.name,el);
   setValue(field,field.type==='secret'?'':value.config?.[field.name]??field.default);
   el.addEventListener(field.type==='select'?'change':'input',()=>{
    dirty=true;const defaults=field.options?.find(o=>o.value===el.value)?.defaults;
    if(defaults)for(const other of spec.fields)if(Object.hasOwn(defaults,other.name))setValue(other,defaults[other.name]);
   });
  }
  status(value.note||((value.key_saved||Object.values(value.secrets||{}).some(Boolean))?'已加密保存密钥。':'填写配置后保存；密钥留空会保留原值。'));
 }
 H.selectModuleConfiguration=c=>{
  const active=!!c?.module_configuration;$('moduleConfiguration').hidden=!active;
  if(!active){selected=null;loaded=null;ticket++;controls.forEach(el=>{if(el.type==='password')el.value='';});return;}
  if(selected===c.id)return;selected=c.id;loaded=null;dirty=false;const current=++ticket;
  controls.clear();$('moduleConfigurationFields').replaceChildren();status('正在读取接入配置…');
  pending=H.client.postAction('integration_module_config',{connection_id:c.id}).then(value=>{if(current===ticket)display(value);}).catch(error=>{if(current===ticket)status(error.message);});
 };
 H.saveModuleConfiguration=async c=>{
  if(pending)await pending;if(selected!==c.id||!loaded)throw Error('请等待接入配置加载完成');
  if(!dirty)return loaded;const config={};
  for(const field of loaded.schema.fields){const el=controls.get(field.name);let value=el.value;
   if(field.type==='boolean')value=el.checked;else if(field.type==='integer')value=Number(value);else if(field.type==='string_list')value=value.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean);else value=value.trim();config[field.name]=value;
  }
  const current=ticket,result=await H.action('integration_module_config',{connection_id:c.id,config});
  if(current===ticket){display(result);if(result.models)c.models=result.models;}return result;
 };
 bind('moduleConfigurationSave','click',async()=>{const button=$('moduleConfigurationSave');button.disabled=true;try{await H.saveModuleConfiguration({id:selected});}catch(error){status(error.message);}finally{button.disabled=false;}});
 bind('closeIntegrations','click',()=>{ticket++;selected=null;loaded=null;controls.forEach(el=>{if(el.type==='password')el.value='';});});
})();
